import { useTranslation } from "react-i18next";

import ErrorScreen from "../components/ErrorScreen";

/** Fallback rendered by ErrorBoundary when a render throws. */
const ServerErrorPage = () => {
	const { t } = useTranslation();

	return (
		<ErrorScreen
			code="500"
			title={t("error.serverErrorTitle")}
			body={t("error.serverErrorBody")}
			primaryAction={{
				label: t("error.reload"),
				onClick: () => window.location.reload(),
			}}
		/>
	);
};

export default ServerErrorPage;
