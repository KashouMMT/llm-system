import { useState } from "react";

import LoginPage from "./LoginPage";
import SignUpPage from "./SignUpPage";

/**
 * The signed-out screen: the sign-in form, with a link to switch to a
 * sign-up form and back.
 *
 * There is no router here — BrowserRouter is mounted inside AuthGate,
 * below the authenticated boundary — so the two forms are toggled with
 * local state rather than routes.
 */
const AuthPanel = () => {
	const [view, setView] = useState<"login" | "signup">("login");
	// Set to the new email after a successful sign-up, so the login form
	// can prefill it and explain why the screen changed.
	const [signedUpEmail, setSignedUpEmail] = useState<string | null>(null);

	if (view === "signup") {
		return (
			<SignUpPage
				onShowLogin={() => setView("login")}
				onSignedUp={(email) => {
					setSignedUpEmail(email);
					setView("login");
				}}
			/>
		);
	}

	return (
		<LoginPage
			initialEmail={signedUpEmail ?? ""}
			notice={
				signedUpEmail ? "Account created — please sign in." : null
			}
			onShowSignUp={() => {
				setSignedUpEmail(null);
				setView("signup");
			}}
		/>
	);
};

export default AuthPanel;
