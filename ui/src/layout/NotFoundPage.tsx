import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import ErrorScreen from "../components/ErrorScreen";

/** Rendered by the catch-all route in App.tsx for any unmatched path. */
const NotFoundPage = () => {
	const { t } = useTranslation();
	const navigate = useNavigate();

	return (
		<ErrorScreen
			code="404"
			title={t("error.notFoundTitle")}
			body={t("error.notFoundBody")}
			primaryAction={{
				label: t("error.backHome"),
				onClick: () => navigate("/"),
			}}
		/>
	);
};

export default NotFoundPage;
