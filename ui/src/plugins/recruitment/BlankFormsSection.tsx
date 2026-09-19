import { useTranslation } from "react-i18next";

import { BLANK_FORMS, blankDocumentUrl } from "./forms";

/** The plugin's settings page: a download button per blank form. */
const BlankFormsSection = () => {
	const { t } = useTranslation();

	return (
		<>
			<p className="settings-status">{t("plugins.recruitment.sectionIntro")}</p>

			<div className="settings-actions">
				{BLANK_FORMS.map((form) => (
					<a
						key={form.docType}
						className="btn btn-outline-secondary"
						href={blankDocumentUrl(form.docType)}
					>
						<i className="bi bi-download me-2" aria-hidden="true" />
						{form.label}
					</a>
				))}
			</div>
		</>
	);
};

export default BlankFormsSection;
