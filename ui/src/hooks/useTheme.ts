import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "theme";

const getInitialTheme = (): Theme => {
	return localStorage.getItem(STORAGE_KEY) === "dark" ? "dark" : "light";
};

export const useTheme = () => {
	const [theme, setTheme] = useState<Theme>(getInitialTheme);

	useEffect(() => {
		document.documentElement.setAttribute("data-theme", theme);
		localStorage.setItem(STORAGE_KEY, theme);
	}, [theme]);

	const toggleTheme = () => {
		setTheme((previous) => (previous === "light" ? "dark" : "light"));
	};

	return { theme, toggleTheme };
};
