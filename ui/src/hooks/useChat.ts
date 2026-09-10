import { useCallback, useRef, useState } from "react";

import { ApiError, sendMessage } from "../api/client";
import type { SendMessageResponse } from "../api/types";

export type ChatError =
	| { kind: "busy"; assistantMessageId: number | null }
	| { kind: "missing" }
	| { kind: "invalid"; message: string }
	| { kind: "network" }
	| { kind: "unknown"; message: string };

type Attempt = {
	clientMessageId: string;
	message: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * FastAPI's `detail` is a string for HTTPException(detail="..."), an object
 * for the 409 lock case, and a list for request validation errors — so it
 * is only ever read behind a guard.
 */
function describe(detail: unknown): string {
	return typeof detail === "string" ? detail : JSON.stringify(detail);
}

/**
 * A v4 UUID that also works outside a secure context.
 *
 * crypto.randomUUID() is only defined on HTTPS and http://localhost, so a
 * bare-IP HTTP deployment must fall back. crypto.getRandomValues() carries
 * no such restriction.
 */
function newClientMessageId(): string {
	if (typeof crypto.randomUUID === "function") {
		return crypto.randomUUID();
	}

	const bytes = crypto.getRandomValues(new Uint8Array(16));
	const hex: string[] = [];

	for (let i = 0; i < 16; i += 1) {
		let byte = bytes[i] ?? 0;

		if (i === 6) byte = (byte & 0x0f) | 0x40; // version 4
		if (i === 8) byte = (byte & 0x3f) | 0x80; // variant 10

		hex.push(byte.toString(16).padStart(2, "0"));
	}

	const s = hex.join("");

	return `${s.slice(0, 8)}-${s.slice(8, 12)}-${s.slice(12, 16)}-${s.slice(16, 20)}-${s.slice(20)}`;
}

function toChatError(caught: unknown): ChatError {
	if (!(caught instanceof ApiError)) {
		return { kind: "network" };
	}

	if (caught.status === 404) {
		return { kind: "missing" };
	}

	if (caught.status === 409) {
		const detail = caught.detail;

		if (isRecord(detail) && detail.reason === "generation_in_progress") {
			const assistantMessageId = detail.assistant_message_id;

			return {
				kind: "busy",
				assistantMessageId:
					typeof assistantMessageId === "number"
						? assistantMessageId
						: null,
			};
		}

		// The other 409: this client_message_id belongs to a different
		// conversation.
		return { kind: "unknown", message: describe(detail) };
	}

	if (caught.status === 422) {
		return { kind: "invalid", message: "That message could not be sent." };
	}

	return { kind: "unknown", message: caught.message };
}

/**
 * Sends a turn and reports why one was refused.
 *
 * It deliberately owns no message state. The POST only opens the turn; the
 * user's own message comes back over the event stream like everyone
 * else's, so there is one rendering path rather than two.
 */
export const useChat = (conversationId: string | undefined) => {
	const [isSending, setIsSending] = useState(false);
	const [error, setError] = useState<ChatError | null>(null);

	// A guard in a ref, not in state: keeping it out of the dependency list
	// lets send() stay referentially stable across renders.
	const inFlightRef = useRef(false);
	const lastAttemptRef = useRef<Attempt | null>(null);

	const post = useCallback(
		async (attempt: Attempt): Promise<SendMessageResponse | null> => {
			if (!conversationId || inFlightRef.current) {
				return null;
			}

			inFlightRef.current = true;
			lastAttemptRef.current = attempt;

			setIsSending(true);
			setError(null);

			try {
				return await sendMessage(conversationId, {
					client_message_id: attempt.clientMessageId,
					message: attempt.message,
				});
			} catch (caught) {
				setError(toChatError(caught));

				return null;
			} finally {
				inFlightRef.current = false;

				setIsSending(false);
			}
		},
		[conversationId],
	);

	const send = useCallback(
		(text: string) => {
			const message = text.trim();

			if (!message) {
				return Promise.resolve(null);
			}

			return post({
				clientMessageId: newClientMessageId(),
				message,
			});
		},
		[post],
	);

	/**
	 * Re-sends the last attempt under its original client_message_id, so a
	 * send that actually reached the server returns the existing ids
	 * instead of generating a second answer.
	 */
	const retry = useCallback(() => {
		const attempt = lastAttemptRef.current;

		if (!attempt) {
			return Promise.resolve(null);
		}

		return post(attempt);
	}, [post]);

	const clearError = useCallback(() => setError(null), []);

	return { send, retry, isSending, error, clearError };
};
