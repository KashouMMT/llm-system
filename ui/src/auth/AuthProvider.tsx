import { type ReactNode, useCallback, useEffect, useMemo } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
	ApiError,
	getCurrentUser,
	login as loginRequest,
	logout as logoutRequest,
} from "../api/client";
import type { AuthUser } from "../api/types";
import { AuthContext, type AuthContextValue, authKey } from "./AuthContext";

export const AuthProvider = ({ children }: { children: ReactNode }) => {
	const queryClient = useQueryClient();

	const query = useQuery({
		queryKey: authKey,
		queryFn: async ({ signal }): Promise<AuthUser | null> => {
			try {
				return await getCurrentUser(signal);
			} catch (error) {
				// A 401 is a definitive "not signed in", not a failure to
				// retry. Anything else is a real error and propagates.
				if (error instanceof ApiError && error.status === 401) {
					return null;
				}
				throw error;
			}
		},
		// Login and logout drive this cache directly; it never goes stale
		// on its own.
		staleTime: Number.POSITIVE_INFINITY,
	});

	// If any request 401s mid-session — a cookie that expired or was
	// cleared — flip to signed-out so the gate shows the login page. The
	// /auth/me query itself never lands here: its queryFn turns a 401 into
	// a null result, not an error.
	useEffect(() => {
		const onError = (error: unknown) => {
			if (error instanceof ApiError && error.status === 401) {
				queryClient.setQueryData(authKey, null);
			}
		};

		const unsubscribeQueries = queryClient
			.getQueryCache()
			.subscribe((event) => {
				if (event.type === "updated" && event.action.type === "error") {
					onError(event.action.error);
				}
			});

		const unsubscribeMutations = queryClient
			.getMutationCache()
			.subscribe((event) => {
				if (event.type === "updated" && event.action.type === "error") {
					onError(event.action.error);
				}
			});

		return () => {
			unsubscribeQueries();
			unsubscribeMutations();
		};
	}, [queryClient]);

	const login = useCallback(
		async (username: string, password: string) => {
			const user = await loginRequest({ username, password });
			queryClient.setQueryData(authKey, user);
		},
		[queryClient],
	);

	const logout = useCallback(async () => {
		try {
			await logoutRequest();
		} finally {
			// Whatever the server said, drop this session locally: mark
			// ourselves signed out and evict every other cached query so
			// nothing from the old session shows behind the login screen.
			queryClient.setQueryData(authKey, null);
			queryClient.removeQueries({
				predicate: (cached) => cached.queryKey[0] !== "auth",
			});
		}
	}, [queryClient]);

	const value = useMemo<AuthContextValue>(() => {
		const actions = { login, logout };

		if (query.isPending) {
			return { status: "loading", ...actions };
		}

		if (query.data) {
			return { status: "authenticated", user: query.data, ...actions };
		}

		return { status: "unauthenticated", ...actions };
	}, [query.isPending, query.data, login, logout]);

	return (
		<AuthContext.Provider value={value}>{children}</AuthContext.Provider>
	);
};
