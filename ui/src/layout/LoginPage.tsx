import { type FormEvent, useState } from "react";

import { ApiError } from "../api/client";
import { useAuth } from "../auth/AuthContext";

const LoginPage = () => {
	const { login } = useAuth();

	const [username, setUsername] = useState("");
	const [password, setPassword] = useState("");
	const [error, setError] = useState<string | null>(null);
	const [submitting, setSubmitting] = useState(false);

	const onSubmit = async (event: FormEvent) => {
		event.preventDefault();
		setError(null);
		setSubmitting(true);

		try {
			await login(username, password);
		} catch (caught) {
			setError(
				caught instanceof ApiError && caught.status === 401
					? "Incorrect username or password."
					: "Could not sign in. Is the API running?",
			);
		} finally {
			setSubmitting(false);
		}
	};

	return (
		<main className="login-page">
			<form className="login-card" onSubmit={onSubmit}>
				<h1 className="login-title">LLM System</h1>

				<label className="form-label" htmlFor="login-username">
					Username
				</label>
				<input
					id="login-username"
					className="form-control"
					autoComplete="username"
					value={username}
					onChange={(event) => setUsername(event.target.value)}
					autoFocus
					required
				/>

				<label className="form-label mt-3" htmlFor="login-password">
					Password
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
					disabled={submitting || !username || !password}
				>
					{submitting ? "Signing in…" : "Sign in"}
				</button>
			</form>
		</main>
	);
};

export default LoginPage;
