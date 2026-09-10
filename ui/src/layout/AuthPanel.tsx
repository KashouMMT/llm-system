import { useState } from "react";
import { useTranslation } from "react-i18next";

import LanguageSwitcher from "../components/LanguageSwitcher";
import LoginPage from "./LoginPage";
import SignUpPage from "./SignUpPage";

/**
 * The signed-out screen: the sign-in form, with a link to switch to a
 * sign-up form and back, plus a language switcher pinned to the corner
 * (there is no navbar here to hold it).
 *
 * There is no router here — BrowserRouter is mounted inside AuthGate,
 * below the authenticated boundary — so the two forms are toggled with
 * local state rather than routes.
 */
const AuthPanel = () => {
	const { t } = useTranslation();

	const [view, setView] = useState<"login" | "signup">("login");
	// Set to the new email after a successful sign-up, so the login form
	// can prefill it and explain why the screen changed.
	const [signedUpEmail, setSignedUpEmail] = useState<string | null>(null);

	const page =
		view === "signup" ? (
			<SignUpPage
				onShowLogin={() => setView("login")}
				onSignedUp={(email) => {
					setSignedUpEmail(email);
					setView("login");
				}}
			/>
		) : (
			<LoginPage
				initialEmail={signedUpEmail ?? ""}
				notice={signedUpEmail ? t("auth.accountCreated") : null}
				onShowSignUp={() => {
					setSignedUpEmail(null);
					setView("signup");
				}}
			/>
		);

	return (
		<>
			<div className="auth-lang-switch">
				<LanguageSwitcher />
			</div>
			{page}
		</>
	);
};

export default AuthPanel;
