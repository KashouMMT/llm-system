import { useTranslation } from "react-i18next";

import { type Language, setLanguage } from "../i18n";

const OPTIONS: { code: Language; label: string }[] = [
	{ code: "en", label: "English" },
	{ code: "ja", label: "日本語" },
];

/**
 * Globe-icon dropdown for switching between English and Japanese. Uses
 * Bootstrap's dropdown (its JS bundle is already loaded in main.tsx), and
 * the same `.theme-toggle` button style as the navbar's theme button so
 * the two sit together consistently.
 */
const LanguageSwitcher = () => {
	const { t, i18n } = useTranslation();

	const current: Language = i18n.language.startsWith("ja") ? "ja" : "en";

	return (
		<div className="dropdown">
			<button
				type="button"
				className="theme-toggle"
				data-bs-toggle="dropdown"
				aria-expanded="false"
				aria-label={t("lang.label")}
			>
				<i className="bi bi-globe2" aria-hidden="true" />
			</button>

			<ul className="dropdown-menu dropdown-menu-end">
				{OPTIONS.map((option) => (
					<li key={option.code}>
						<button
							type="button"
							className={
								current === option.code
									? "dropdown-item active"
									: "dropdown-item"
							}
							onClick={() => setLanguage(option.code)}
						>
							{option.label}
						</button>
					</li>
				))}
			</ul>
		</div>
	);
};

export default LanguageSwitcher;
