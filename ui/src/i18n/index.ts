import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { en } from "./locales/en";
import { ja } from "./locales/ja";

export const SUPPORTED_LANGUAGES = ["en", "ja"] as const;
export type Language = (typeof SUPPORTED_LANGUAGES)[number];

const STORAGE_KEY = "lang";

// The app is used mostly from Japan, so Japanese is the default. There is
// no locale/geolocation detection on purpose: a fixed default plus a
// visible switcher that remembers the choice is predictable.
const DEFAULT_LANGUAGE: Language = "ja";

const isLanguage = (value: string | null): value is Language =>
	value === "en" || value === "ja";

const readStoredLanguage = (): Language => {
	try {
		const stored = localStorage.getItem(STORAGE_KEY);

		if (isLanguage(stored)) {
			return stored;
		}
	} catch {
		// localStorage throws in private mode or when storage is disabled;
		// fall through to the default.
	}

	return DEFAULT_LANGUAGE;
};

const initialLanguage = readStoredLanguage();

void i18n.use(initReactI18next).init({
	resources: {
		en: { translation: en },
		ja: { translation: ja },
	},
	lng: initialLanguage,
	fallbackLng: "en",
	interpolation: {
		// React escapes interpolated values already.
		escapeValue: false,
	},
	react: {
		// Resources are bundled and init is synchronous, so nothing ever
		// needs to suspend while a translation loads.
		useSuspense: false,
	},
});

document.documentElement.lang = initialLanguage;

/**
 * Switch the active language, keep `<html lang>` in sync for
 * accessibility, and remember the choice for the next visit.
 */
export const setLanguage = (language: Language): void => {
	void i18n.changeLanguage(language);
	document.documentElement.lang = language;

	try {
		localStorage.setItem(STORAGE_KEY, language);
	} catch {
		// Non-fatal: the choice just will not survive to the next visit.
	}
};

export default i18n;
