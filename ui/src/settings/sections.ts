import type { ComponentType } from "react";

import type { UserRole } from "../api/types";
import type { FrontendPlugin } from "../plugins/types";
import {
	GeneralSection,
	LlmSection,
	MemorySection,
	StreamingSection,
} from "./CoreSections";

/**
 * Who OWNS a section. Who may SEE it is `minRole`, a separate axis: a
 * plugin page can be root-only without leaving the PLUGIN group.
 *
 * No "admin" category yet — nothing admin-level lives outside CORE.
 */
export type SettingsCategory = "core" | "root" | "plugin";

/** Sidebar order. A category with no visible section is not rendered. */
export const CATEGORY_ORDER: readonly SettingsCategory[] = [
	"core",
	"root",
	"plugin",
];

export type SettingsSection = {
	category: SettingsCategory;
	/** URL segment, unique within its category. */
	id: string;
	/** i18n key for both the sidebar entry and the page heading. */
	labelKey: string;
	/**
	 * Hides the section from lower roles. Presentation only — the backend
	 * refuses the requests regardless of what the page showed.
	 */
	minRole: "admin" | "root";
	component: ComponentType;
};

const ROLE_RANK: Record<UserRole, number> = { user: 0, admin: 1, root: 2 };

export const canSee = (role: UserRole, section: SettingsSection): boolean =>
	ROLE_RANK[role] >= ROLE_RANK[section.minRole];

export const sectionPath = (section: SettingsSection): string =>
	`/settings/${section.category}/${section.id}`;

/** A plugin section's id in the URL: prefixed, so two plugins cannot clash. */
export const pluginSectionId = (pluginName: string, id: string): string =>
	`${pluginName}-${id}`;

/** The loaded plugins' sections, placed under the PLUGIN category. */
export const pluginSections = (
	plugins: readonly FrontendPlugin[],
): SettingsSection[] =>
	plugins.flatMap((plugin) =>
		(plugin.settingsSections ?? []).map((section) => ({
			...section,
			category: "plugin" as const,
			id: pluginSectionId(plugin.name, section.id),
		})),
	);

// The CORE sections. Plugin sections are added at render time by
// pluginSections(), since which plugins loaded is only known then.
export const SETTINGS_SECTIONS: readonly SettingsSection[] = [
	{
		category: "core",
		id: "general",
		labelKey: "settings.sections.general",
		minRole: "admin",
		component: GeneralSection,
	},
	{
		category: "core",
		id: "llm",
		labelKey: "settings.sections.llm",
		minRole: "admin",
		component: LlmSection,
	},
	{
		category: "core",
		id: "memory",
		labelKey: "settings.sections.memory",
		minRole: "admin",
		component: MemorySection,
	},
	{
		category: "core",
		id: "streaming",
		labelKey: "settings.sections.streaming",
		minRole: "admin",
		component: StreamingSection,
	},
];
