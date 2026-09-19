import { useTranslation } from "react-i18next";

import "./blankForms.css";
import { BLANK_FORMS, blankDocumentUrl } from "./forms";

/** The chat sidebar's list of blank forms (chatSidebar slot). */
const BlankForms = () => {
	const { t } = useTranslation();

	return (
		<div className="blank-forms">
			<p className="blank-forms-heading">
				{t("plugins.recruitment.blankForms")}
			</p>

			{BLANK_FORMS.map((form) => (
				<a
					key={form.docType}
					className="blank-form"
					href={blankDocumentUrl(form.docType)}
				>
					<span>{form.label}</span>

					<span className="blank-form-hint">{form.hint}</span>
				</a>
			))}
		</div>
	);
};

export default BlankForms;
