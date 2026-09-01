import { useCallback, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { listMessages } from "../api/client";
import type { Message } from "../api/types";

export const messagesKey = (conversationId: string | undefined) =>
	["conversations", conversationId, "messages"] as const;

export const useMessages = (conversationId: string | undefined) => {
	return useQuery({
		queryKey: messagesKey(conversationId),
		queryFn: ({ signal }) => {
			if (!conversationId) {
				throw new Error("useMessages ran without a conversation id");
			}

			return listMessages(conversationId, signal);
		},
		enabled: Boolean(conversationId),
		// Left stale on purpose: the event stream is the update channel,
		// and it re-reads the transcript itself whenever it (re)connects.
		staleTime: 0,
		refetchOnWindowFocus: false,
	});
};

export type MessageCache = {
	upsertMessage: (message: Message) => void;
	patchMessage: (messageId: number, patch: Partial<Message>) => void;
	refresh: () => void;
};

/**
 * Write access to the cached transcript, for the event stream.
 *
 * Every writer falls back to a refetch when the message it is asked to
 * change is not cached, rather than inventing a row. A partially known
 * message rendered from an event is worse than one honest round trip.
 */
export const useMessageCache = (
	conversationId: string | undefined,
): MessageCache => {
	const queryClient = useQueryClient();

	const refresh = useCallback(() => {
		if (!conversationId) {
			return;
		}

		queryClient.invalidateQueries({
			queryKey: messagesKey(conversationId),
		});
	}, [conversationId, queryClient]);

	const upsertMessage = useCallback(
		(message: Message) => {
			if (!conversationId) {
				return;
			}

			const key = messagesKey(conversationId);
			const current = queryClient.getQueryData<Message[]>(key);

			if (current === undefined) {
				refresh();

				return;
			}

			const index = current.findIndex((item) => item.id === message.id);

			if (index === -1) {
				// Ids are assigned by a sequence, so a new row always sorts
				// last and appending keeps the list ordered.
				queryClient.setQueryData<Message[]>(key, [...current, message]);

				return;
			}

			const next = current.slice();
			next[index] = { ...next[index], ...message };

			queryClient.setQueryData<Message[]>(key, next);
		},
		[conversationId, queryClient, refresh],
	);

	const patchMessage = useCallback(
		(messageId: number, patch: Partial<Message>) => {
			if (!conversationId) {
				return;
			}

			const key = messagesKey(conversationId);
			const current = queryClient.getQueryData<Message[]>(key);

			if (current === undefined) {
				refresh();

				return;
			}

			const index = current.findIndex((item) => item.id === messageId);

			if (index === -1) {
				refresh();

				return;
			}

			const next = current.slice();
			next[index] = { ...next[index], ...patch };

			queryClient.setQueryData<Message[]>(key, next);
		},
		[conversationId, queryClient, refresh],
	);

	return useMemo(
		() => ({ upsertMessage, patchMessage, refresh }),
		[upsertMessage, patchMessage, refresh],
	);
};
