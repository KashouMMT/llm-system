import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, register } from "../api/client";

type SignUpPageProps = {
	/** Called with the normalised email after the account is created. */
	onSignedUp: (email: string) => void;
	/** Switch back to the sign-in form. */
	onShowLogin: () => void;
};

const SignUpPage = ({ onSignedUp, onShowLogin }: SignUpPageProps) => {
	const { t } = useTranslation();

	const [email, setEmail] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);

	const onSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setError(null);
		setSubmitting(true);

		try {
			await register({ email, password });
			// The backend lower-cases and trims the email; mirror that so
			// the value handed to the login form matches.
			onSignedUp(email.trim().toLowerCase());
		} catch (caught) {
			setError(
				caught instanceof ApiError && caught.status === 409
					? t("auth.errEmailTaken")
					: t("auth.errSignUpGeneric"),
			);
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<main className="login-page">
			<form className="login-card" onSubmit={onSubmit}>
				<h1 className="login-title">{t("auth.signUpTitle")}</h1>

				<label className="form-label" htmlFor="signup-email">
					{t("auth.email")}
				</label>
				<input
					id="signup-email"
					type="email"
					className="form-control"
					autoComplete="email"
					value={email}
					onChange={(event) => setEmail(event.target.value)}
					autoFocus
					required
				/>

				<label className="form-label mt-3" htmlFor="signup-password">
					{t("auth.password")}
				</label>
				<input
					id="signup-password"
					type="password"
					className="form-control"
					autoComplete="new-password"
					value={password}
					onChange={(event) => setPassword(event.target.value)}
					required
				/>

				{error && (
					<p className="login-error" role="alert">
						{error}
					</p>
				)}

				<button
					type="submit"
					className="btn btn-primary w-100 mt-4"
					disabled={submitting || !email || !password}
				>
					{submitting ? t("auth.creatingAccount") : t("auth.signUp")}
				</button>

				<p className="login-alt">
					{t("auth.haveAccount")}{" "}
					<button
						type="button"
						className="login-link"
						onClick={onShowLogin}
					>
						{t("auth.signIn")}
					</button>
				</p>
			</form>
		</main>
	);
};

export default SignUpPage;
