// Looked up as plugins.recruitment.<key>; see FrontendPlugin.messages.

export const en = {
	blankForms: "Blank forms",
	sectionIntro: "Empty forms to fill in by hand.",
};

// Typed against en, so a key missing in either language fails tsc.
export const ja: typeof en = {
	blankForms: "空のフォーム",
	sectionIntro: "手書きで記入するための空のフォームです。",
};
