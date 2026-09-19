import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";

import { CATEGORY_ORDER, sectionPath, type SettingsSection } from "./sections";

type SettingsSidebarProps = {
	/** Already filtered to what the current user may see. */
	sections: readonly SettingsSection[];
};

const SettingsSidebar = ({ sections }: SettingsSidebarProps) => {
	const { t } = useTranslation();

	return (
		<nav className="settings-sidebar" aria-label={t("settings.navLabel")}>
			{CATEGORY_ORDER.map((category) => {
				const inCategory = sections.filter(
					(section) => section.category === category,
				);

				if (inCategory.length === 0) {
					return null;
				}

				return (
					<div key={category} className="settings-category">
						<p className="settings-category-heading">
							{t(`settings.categories.${category}`)}
						</p>

						{inCategory.map((section) => (
							<NavLink
								key={section.id}
								to={sectionPath(section)}
								className={({ isActive }) =>
									`settings-link${isActive ? " active" : ""}`
								}
							>
								{t(section.labelKey)}
							</NavLink>
						))}
					</div>
				);
			})}
		</nav>
	);
};

export default SettingsSidebar;
