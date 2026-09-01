import { useCallback, useEffect, useRef, useState } from "react";

import { eventsUrl } from "../api/client";
import {
	EVENT_CONVERSATION_UPDATED,
	EVENT_MESSAGE_CANCELLED,
	EVENT_MESSAGE_COMPLETED,
	EVENT_MESSAGE_CREATED,
	EVENT_MESSAGE_DELTA,
	EVENT_MESSAGE_FAILED,
} from "../api/types";
import type {
	MessageCreatedPayload,
	MessageDeltaPayload,
	MessageTerminalPayload,
	ServerEventEnvelope,
} from "../api/types";
import { useConversationsRefresh } from "./useConversations";
import { useMessageCache } from "./useMessages";

// A conversation that is clicked past within this window never costs a
// connection. Short enough to be invisible on a deliberate selection.
const STREAM_CONNECT_DELAY_MS = 150;

export type StreamStatus = "idle" | "connecting" | "open" | "closed";

/**
 * Live state for one conversation's event stream.
 *
 * conversationId is part of the state on purpose. Status, drafts and
 * joinedLate only mean anything together with the conversation they were
 * produced for, so they are stored as one value and replaced as one value.
 * That is what lets a conversation switch be handled by comparison during
 * render instead of by a reset effect, which would have shown one frame of
 * the previous conversation's text first.
 */
export type ConversationStream = {
	conversationId: string | undefined;
	status: StreamStatus;
	/** assistant message id -> text streamed so far on this connection. */
	drafts: Record<number, string>;
	/** True when this client connected after generation had begun. */
	joinedLate: boolean;
};

const initialState = (
	conversationId: string | undefined,
): ConversationStream => ({
	conversationId,
	// The subscribing effect runs immediately after this render, so a
	// conversation is "connecting" from the moment it is selected.
	status: conversationId ? "connecting" : "idle",
	drafts: {},
	joinedLate: false,
});

/**
 * Subscribes to one conversation's event stream for as long as that
 * conversation is on screen.
 *
 * The stream is tied to the conversation, not to sending — the server
 * treats the sender as an ordinary subscriber, so a tab that never sends
 * anything must still receive the same tokens.
 */
export const useConversationStream = (
	conversationId: string | undefined,
): ConversationStream => {
	const { upsertMessage, patchMessage, refresh } =
		useMessageCache(conversationId);
	const refreshConversations = useConversationsRefresh();

	const [state, setState] = useState<ConversationStream>(() =>
		initialState(conversationId),
	);

	// Tokens accumulate in a ref and are published to React state at most
	// once per animation frame. Calling setState per token would re-render
	// the whole transcript at the model's output rate.
	const draftsRef = useRef<Record<number, string>>({});
	const frameRef = useRef<number | null>(null);

	// Messages we have already seen a delta for, so the first delta of each
	// message can be checked for a seq gap.
	const startedRef = useRef<Set<number>>(new Set());

	/**
	 * Applies a change on behalf of one conversation.
	 *
	 * `owner` is captured by the effect that produced the callback, so a
	 * write belonging to a conversation that is no longer current rebases
	 * onto that conversation's own initial state rather than corrupting the
	 * current one — and the read below then discards it.
	 */
	const update = useCallback(
		(
			owner: string,
			change: Partial<Omit<ConversationStream, "conversationId">>,
		) => {
			setState((previous) =>
				previous.conversationId === owner
					? { ...previous, ...change }
					: { ...initialState(owner), ...change },
			);
		},
		[],
	);

	const scheduleFlush = useCallback(
		(owner: string) => {
			if (frameRef.current !== null) {
				return;
			}

			frameRef.current = window.requestAnimationFrame(() => {
				frameRef.current = null;

				update(owner, { drafts: { ...draftsRef.current } });
			});
		},
		[update],
	);

	const handleCreated = useCallback(
		(payload: MessageCreatedPayload) => {
			upsertMessage({
				id: payload.message_id,
				role: payload.role,
				content: payload.content,
				created_at: payload.created_at,
				status: payload.status,
			});
		},
		[upsertMessage],
	);

	const handleDelta = useCallback(
		(owner: string, payload: MessageDeltaPayload) => {
			if (!startedRef.current.has(payload.message_id)) {
				startedRef.current.add(payload.message_id);

				// Deltas are not replayable. seq > 1 on the first one we see
				// means earlier tokens were published before we connected;
				// the terminal event will deliver the full text.
				if (payload.seq > 1) {
					update(owner, { joinedLate: true });
				}
			}

			draftsRef.current[payload.message_id] =
				(draftsRef.current[payload.message_id] ?? "") + payload.text;

			scheduleFlush(owner);
		},
		[scheduleFlush, update],
	);

	const handleTerminal = useCallback(
		(owner: string, payload: MessageTerminalPayload) => {
			// The terminal event carries the authoritative full content, so
			// the draft is replaced rather than reconciled.
			patchMessage(payload.message_id, {
				content: payload.content,
				status: payload.status,
			});
			
			// The terminal event is published only after the row is
			// committed, so a refetch issued now cannot be beaten by one
			// that was already in flight before the commit.
			refresh();

			delete draftsRef.current[payload.message_id];
			startedRef.current.delete(payload.message_id);

			update(owner, {
				drafts: { ...draftsRef.current },
				joinedLate: false,
			});
		},
		[patchMessage, refresh, update],
	);

	useEffect(() => {
		if (!conversationId) {
			return;
		}

		draftsRef.current = {};
		startedRef.current.clear();

		// Held in a mutable binding so the cleanup can close a stream that
		// may not exist yet at the moment the cleanup runs.
		let connection: EventSource | null = null;

		const timer = window.setTimeout(() => {
			const source = new EventSource(eventsUrl(conversationId), {
				withCredentials: true,
			});

			connection = source;

			source.onopen = () => {
				update(conversationId, { status: "open" });

				// Read the transcript only once the stream is live. Fetching
				// first would leave a window in which a message is created,
				// missed by the fetch, and its event never received.
				refresh();
				refreshConversations();
			};

			source.onerror = () => {
				// EventSource reconnects by itself and reports errors along
				// the way; only a CLOSED readyState is final.
				update(conversationId, {
					status:
						source.readyState === EventSource.CLOSED
							? "closed"
							: "connecting",
				});
			};

			const on = <TPayload>(
				type: string,
				handle: (payload: TPayload) => void,
			) => {
				source.addEventListener(type, (event) => {
					try {
						const envelope = JSON.parse(
							(event as MessageEvent<string>).data,
						) as ServerEventEnvelope<TPayload>;

						handle(envelope.payload);
					} catch (error) {
						console.error("Malformed server event", type, error);
					}
				});
			};

			on<MessageCreatedPayload>(EVENT_MESSAGE_CREATED, handleCreated);

			on<MessageDeltaPayload>(EVENT_MESSAGE_DELTA, (payload) =>
				handleDelta(conversationId, payload),
			);

			for (const type of [
				EVENT_MESSAGE_COMPLETED,
				EVENT_MESSAGE_CANCELLED,
				EVENT_MESSAGE_FAILED,
			]) {
				on<MessageTerminalPayload>(type, (payload) =>
					handleTerminal(conversationId, payload),
				);
			}

			on(EVENT_CONVERSATION_UPDATED, refreshConversations);
		}, STREAM_CONNECT_DELAY_MS);

		return () => {
			window.clearTimeout(timer);

			// StrictMode mounts effects twice in development; without this
			// close() the second mount would leave a stream open and every
			// token would appear duplicated.
			connection?.close();

			if (frameRef.current !== null) {
				window.cancelAnimationFrame(frameRef.current);
				frameRef.current = null;
			}
		};
		// Every callback here is memoised against a stable queryClient and
		// this conversation id, so the stream reconnects only when the
		// conversation changes. Keep it that way.
	}, [
		conversationId,
		handleCreated,
		handleDelta,
		handleTerminal,
		refresh,
		refreshConversations,
		update,
	]);

	// The state is only valid for the conversation it was produced for.
	// Deriving the read this way means a switch takes effect in the same
	// render as the prop change, with no intermediate frame and no reset.
	return state.conversationId === conversationId
		? state
		: initialState(conversationId);
};
