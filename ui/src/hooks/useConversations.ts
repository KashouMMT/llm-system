import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createConversation, listConversations } from "../api/client";

export const conversationsKey = ["conversations"] as const;

export const useConversations = () => {
	return useQuery({
		queryKey: conversationsKey,
		queryFn: ({ signal }) => listConversations(signal),
		// The list only changes when a conversation is created or a turn
		// finishes, and both of those invalidate it explicitly.
		staleTime: 60_000,
	});
};

export const useCreateConversation = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: createConversation,
		onSuccess: () => {
			queryClient.invalidateQueries({ queryKey: conversationsKey });
		},
	});
};

/**
 * Lets the event stream refresh the sidebar without importing React Query
 * itself, keeping the streaming path free of cache-library concerns.
 */
export const useConversationsRefresh = () => {
	const queryClient = useQueryClient();

	return useCallback(() => {
		queryClient.invalidateQueries({ queryKey: conversationsKey });
	}, [queryClient]);
};
