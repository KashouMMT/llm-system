import type { ReactNode } from "react";

import AuthPanel from "../layout/AuthPanel";
import ForbiddenPage from "../layout/ForbiddenPage";
import { useAuth } from "./AuthContext";

/**
 * Decides what the whole app renders based on sign-in state:
 * a brief loading line, the login page, the 403 page, or the app itself.
 */
export const AuthGate = ({ children }: { children: ReactNode }) => {
	const auth = useAuth();

	// A 403 takes precedence over everything: nothing else will work until
	// the CSRF token is refreshed by a reload.
	if (auth.httpError === 403) {
		return <ForbiddenPage onDismiss={auth.dismissHttpError} />;
	}

	if (auth.status === "loading") {
		return (
			<div className="auth-loading" role="status" aria-live="polite">
				Loading…
			</div>
		);
	}

	if (auth.status === "unauthenticated") {
		return <AuthPanel />;
	}

	return <>{children}</>;
};
