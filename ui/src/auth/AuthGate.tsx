import type { ReactNode } from "react";

import LoginPage from "../layout/LoginPage";
import { useAuth } from "./AuthContext";

/**
 * Decides what the whole app renders based on sign-in state:
 * a brief loading line, the login page, or the app itself.
 */
export const AuthGate = ({ children }: { children: ReactNode }) => {
	const auth = useAuth();

	if (auth.status === "loading") {
		return (
			<div className="auth-loading" role="status" aria-live="polite">
				Loading…
			</div>
		);
	}

	if (auth.status === "unauthenticated") {
		return <LoginPage />;
	}

	return <>{children}</>;
};
