import { Navigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import "../assets/css/settings.css";
import { useAuth } from "../auth/AuthContext";
import Navbar from "../components/Navbar";
import { usePlugins } from "../hooks/usePlugins";
import {
	SETTINGS_SECTIONS,
	canSee,
	pluginSections,
	sectionPath,
} from "../settings/sections";
import SettingsSidebar from "../settings/SettingsSidebar";

/**
 * The settings shell: navbar, a sidebar of sections, and the selected
 * section. Which section is open lives in the URL, so a section can be
 * linked to directly and the back button moves between them.
 */
const SettingsPage = () => {
	const { t } = useTranslation();
	const auth = useAuth();
	const { category, sectionId } = useParams<{
		category: string;
		sectionId: string;
	}>();
	const plugins = usePlugins();

	// AuthGate only renders the app once signed in; this narrows the type.
	if (auth.status !== "authenticated") {
		return null;
	}

	// Before any redirect decision: until the plugin list arrives, a link
	// straight to a plugin section (e.g. from /recycle show_catalog) looks
	// like an unknown section and would bounce to the first core one.
	if (plugins.isPending) {
		return <Navbar />;
	}

	const sections = [
		...SETTINGS_SECTIONS,
		...pluginSections(plugins.plugins),
	].filter((section) => canSee(auth.user.role, section));

	// Nothing visible means a normal user typed the URL: every control here
	// would be refused, so go home instead of showing an empty shell.
	if (sections.length === 0) {
		return <Navigate to="/" replace />;
	}

	const active = sections.find(
		(section) => section.category === category && section.id === sectionId,
	);

	// Bare /settings, an unknown section, or one above this user's role.
	if (!active) {
		return <Navigate to={sectionPath(sections[0])} replace />;
	}

	const Section = active.component;

	return (
		<>
			<Navbar />

			<main className="settings-layout">
				<SettingsSidebar sections={sections} />

				<div className="settings-main">
					<div className="settings-panel">
						<h1 className="settings-title">{t(active.labelKey)}</h1>

						{/* Keyed so switching section drops the previous one's
						    unsaved edits instead of carrying them over. */}
						<Section key={sectionPath(active)} />
					</div>
				</div>
			</main>
		</>
	);
};

export default SettingsPage;
