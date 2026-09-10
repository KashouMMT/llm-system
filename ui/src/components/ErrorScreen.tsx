type ErrorAction = { label: string; onClick: () => void };

type ErrorScreenProps = {
	/** The HTTP status shown large, e.g. "404". */
	code: string;
	title: string;
	body: string;
	primaryAction?: ErrorAction;
	secondaryAction?: ErrorAction;
};

/**
 * Presentational full-screen error card. Router-agnostic on purpose —
 * actions are plain callbacks, so this renders the same whether it is
 * inside <BrowserRouter> (NotFound, the error boundary) or outside it
 * (the 403 takeover in AuthGate).
 */
const ErrorScreen = ({
	code,
	title,
	body,
	primaryAction,
	secondaryAction,
}: ErrorScreenProps) => (
	<main className="error-page">
		<div className="error-card">
			<p className="error-code">{code}</p>
			<h1 className="error-title">{title}</h1>
			<p className="error-body">{body}</p>

			{(primaryAction || secondaryAction) && (
				<div className="error-actions">
					{primaryAction && (
						<button
							type="button"
							className="btn btn-primary"
							onClick={primaryAction.onClick}
						>
							{primaryAction.label}
						</button>
					)}
					{secondaryAction && (
						<button
							type="button"
							className="btn btn-outline-secondary"
							onClick={secondaryAction.onClick}
						>
							{secondaryAction.label}
						</button>
					)}
				</div>
			)}
		</div>
	</main>
);

export default ErrorScreen;
