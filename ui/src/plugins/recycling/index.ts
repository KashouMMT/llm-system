import type { FrontendPlugin } from "../types";
import Catalog from "./Catalog";
import { en, ja } from "./messages";

// UI half of app/plugins/recycling/ (routes.py serves the catalog).
export const recycling: FrontendPlugin = {
	name: "recycling",
	messages: { en, ja },
	settingsSections: [
		{
			id: "catalog",
			labelKey: "plugins.recycling.catalogTitle",
			// Same gate as the endpoint and as /recycle show_catalog.
			minRole: "admin",
			component: Catalog,
		},
	],
	// The chat's table grows past usefulness with the catalog; the browser
	// pages and searches it instead. Only the bare typed command is
	// redirected: the assistant's own recycle_show_catalog tool still
	// answers in the chat.
	commandRedirects: [
		{ namespace: "recycle", subcommands: ["show_catalog"], section: "catalog" },
	],
};
