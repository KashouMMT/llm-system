import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
	getSettings,
	listPromptSets,
	resetSetting,
	updateSettings,
} from "../api/client";

export const settingsKey = ["settings"] as const;

// Not nested under settingsKey: invalidating the settings by prefix would
// otherwise refetch the folder list too, which no settings change affects.
const promptSetsKey = ["prompt-sets"] as const;

export const useSettings = () => {
	return useQuery({
		queryKey: settingsKey,
		queryFn: ({ signal }) => getSettings(signal),
	});
};

// Both mutations answer with the full settings after the change, so the
// cache is replaced with that rather than refetched: one round trip, and
// the page shows exactly what the server now holds.

export const useUpdateSettings = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: updateSettings,
		onSuccess: (settings) => {
			queryClient.setQueryData(settingsKey, settings);
		},
	});
};

export const useResetSetting = () => {
	const queryClient = useQueryClient();

	return useMutation({
		mutationFn: resetSetting,
		onSuccess: (settings) => {
			queryClient.setQueryData(settingsKey, settings);
		},
	});
};

export const usePromptSets = () => {
	return useQuery({
		queryKey: promptSetsKey,
		queryFn: ({ signal }) => listPromptSets(signal),
	});
};
