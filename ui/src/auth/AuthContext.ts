import { createContext, useContext } from "react";

import type { AuthUser } from "../api/types";

export const authKey = ["auth", "me"] as const;

export type AuthState =
	| { status: "loading" }
	| { status: "authenticated"; user: AuthUser }
	| { status: "unauthenticated" };

export type AuthContextValue = AuthState & {
	login: (username: string, password: string) => Promise<void>;
	logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export const useAuth = (): AuthContextValue => {
	const value = useContext(AuthContext);

	if (value === null) {
		throw new Error("useAuth must be used within <AuthProvider>");
	}

	return value;
};
