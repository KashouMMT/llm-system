import type { ComponentType } from "react";

import type { SettingsSection } from "../settings/sections";

/**
 * A settings page a plugin contributes. Always shown under the PLUGIN
 * category, at /settings/plugin/<plugin name>-<id>, so a plugin cannot
 * place itself among the core sections or collide with another plugin.
 */
export type PluginSettingsSection = Omit<SettingsSection, "category">;

/**
 * A typed slash command the frontend answers itself by opening one of the
 * plugin's settings sections, instead of sending it to the chat.
 */
export type CommandRedirect = {
	/** Without the slash: "recycle". */
	namespace: string;
	/** The subcommand's name and aliases, as the backend would accept them. */
	subcommands: readonly string[];
	/** The `id` of one of this plugin's settingsSections. */
	section: string;
};

/**
 * The UI half of a backend plugin (app/plugins/<name>/).
 *
 * Mirrors the backend rule: a plugin owns its whole vertical, and deleting
 * its folder under ui/src/plugins/ plus its line in ./index.ts removes
 * every trace. Core code never imports a plugin folder directly; it only
 * renders the slots below.
 *
 * Slots are added when a plugin needs one, not in advance.
 */
export type FrontendPlugin = {
	/** The backend plugin folder name, exactly: the join key with GET /plugins. */
	name: string;
	/**
	 * The plugin's own strings, merged into i18n under `plugins.<name>`, so
	 * they leave with the folder instead of lingering in the core locales.
	 */
	messages?: { en: object; ja: object };
	/** Rendered in the chat sidebar, between the conversations and the account block. */
	chatSidebar?: ComponentType;
	settingsSections?: readonly PluginSettingsSection[];
	commandRedirects?: readonly CommandRedirect[];
};
