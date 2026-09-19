// Imported for its side effect as much as its value: i18n must be
// initialised before a bundle is added, and init() replaces the store, so
// depending on the module here guarantees the order whatever imports this.
import i18n from "../i18n";
import { recruitment } from "./recruitment";
import { recycling } from "./recycling";
import type { FrontendPlugin } from "./types";

/**
 * Every plugin whose UI ships in this bundle. Shipping is not showing:
 * usePlugins() keeps only those GET /plugins also lists, so the backend's
 * EXCLUDED_TOOL_PLUGINS stays the one place that decides.
 *
 * A backend plugin with no UI (clock) simply has no entry here.
 */
export const FRONTEND_PLUGINS: readonly FrontendPlugin[] = [
	recruitment,
	recycling,
];

for (const plugin of FRONTEND_PLUGINS) {
	if (!plugin.messages) {
		continue;
	}

	for (const [language, messages] of Object.entries(plugin.messages)) {
		i18n.addResourceBundle(
			language,
			"translation",
			{ plugins: { [plugin.name]: messages } },
			true, // deep: merge beside the other plugins, not over them
			false,
		);
	}
}
