import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

type LoginPageProps = {
	/** Prefilled email, e.g. straight after creating an account. */
	initialEmail?: string;
	/** One-line info shown above the form, e.g. "Account created." */
	notice?: string | null;
	/** Switch to the sign-up form. */
	onShowSignUp: () => void;
};

const LoginPage = ({
	initialEmail = "",
	notice = null,
	onShowSignUp,
}: LoginPageProps) => {
	const { t } = useTranslation();
	const { login } = useAuth();

	const [email, setEmail] = useState(initialEmail);
	const [password, setPassword] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);

	const onSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setError(null);
		setSubmitting(true);

		try {
			await login(email, password);
		} catch (caught) {
			setError(
				caught instanceof ApiError && caught.status === 401
					? t("auth.errWrongCredentials")
					: t("auth.errSignInGeneric"),
			);
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<main className="login-page">
			<form className="login-card" onSubmit={onSubmit}>
				<h1 className="login-title">LLM System</h1>

				{notice && (
					<p className="login-notice" role="status">
						{notice}
					</p>
				)}

				<label className="form-label" htmlFor="login-email">
					{t("auth.email")}
				</label>
				<input
					id="login-email"
					type="email"
					className="form-control"
					autoComplete="email"
					value={email}
					onChange={(event) => setEmail(event.target.value)}
					autoFocus
					required
				/>

				<label className="form-label mt-3" htmlFor="login-password">
					{t("auth.password")}
				</label>
				<input
					id="login-password"
					type="password"
					className="form-control"
					autoComplete="current-password"
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
					{submitting ? t("auth.signingIn") : t("auth.signIn")}
				</button>

				<p className="login-alt">
					{t("auth.needAccount")}{" "}
					<button
						type="button"
						className="login-link"
						onClick={onShowSignUp}
					>
						{t("auth.signUp")}
					</button>
				</p>
			</form>
		</main>
	);
};

export default LoginPage;
