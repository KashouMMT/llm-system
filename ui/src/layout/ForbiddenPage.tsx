import { useTranslation } from "react-i18next";

import ErrorScreen from "../components/ErrorScreen";

type ForbiddenPageProps = {
	/** Clear the 403 flag and return to the app without a full reload. */
	onDismiss: () => void;
};

/**
 * Shown by AuthGate when an API call returns 403. In practice that means
 * the CSRF token went stale (e.g. the server restarted without a fixed
 * CSRF_SECRET); a reload hits GET /auth/me, which re-issues the token
 * cookie, so "Reload" is the real fix and "Dismiss" is the escape hatch.
 */
const ForbiddenPage = ({ onDismiss }: ForbiddenPageProps) => {
	const { t } = useTranslation();

	return (
		<ErrorScreen
			code="403"
			title={t("error.forbiddenTitle")}
			body={t("error.forbiddenBody")}
			primaryAction={{
				label: t("error.reload"),
				onClick: () => window.location.reload(),
			}}
			secondaryAction={{
				label: t("error.dismiss"),
				onClick: onDismiss,
			}}
		/>
	);
};

export default ForbiddenPage;
