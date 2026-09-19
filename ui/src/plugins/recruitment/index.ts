import type { FrontendPlugin } from "../types";
import BlankForms from "./BlankForms";
import BlankFormsSection from "./BlankFormsSection";
import { en, ja } from "./messages";

// UI half of app/plugins/recruitment/ (routes.py serves the blank forms).
export const recruitment: FrontendPlugin = {
	name: "recruitment",
	messages: { en, ja },
	chatSidebar: BlankForms,
	settingsSections: [
		{
			id: "blank-forms",
			labelKey: "plugins.recruitment.blankForms",
			// The settings page is admin-only today; anyone signed in may
			// download the forms themselves, from the chat sidebar.
			minRole: "admin",
			component: BlankFormsSection,
		},
	],
};
