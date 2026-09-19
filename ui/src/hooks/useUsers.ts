import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createUser, deleteUser, listUsers, updateUser } from "../api/client";
import type { UpdateUserRequest } from "../api/types";

const usersKey = ["users"] as const;

export const useUsers = () => {
	return useQuery({
		queryKey: usersKey,
		queryFn: ({ signal }) => listUsers(signal),
	});
};

// Every change refetches the list rather than patching the cache: it is
// small, and the server's order (root first, then oldest) stays authoritative.
const useUsersMutation = <TVariables, TResult>(
	mutationFn: (variables: TVariables) => Promise<TResult>,
) => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn,
		onSuccess: () => {
			void queryClient.invalidateQueries({ queryKey: usersKey });
		},
	});
};

export const useCreateUser = () => useUsersMutation(createUser);

export const useUpdateUser = () =>
	useUsersMutation(({ id, body }: { id: string; body: UpdateUserRequest }) =>
		updateUser(id, body),
	);

export const useDeleteUser = () => useUsersMutation(deleteUser);
