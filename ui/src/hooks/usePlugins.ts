import { useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { listPlugins } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { FRONTEND_PLUGINS } from "../plugins";
import {
	canSee,
	pluginSectionId,
	pluginSections,
	sectionPath,
} from "../settings/sections";

const pluginsKey = ["plugins"] as const;

/**
 * The frontend plugins this deployment actually loaded: the bundled ones
 * whose name GET /plugins lists.
 *
 * Fails closed: until the server answers, or if it cannot, no plugin is
 * active. The backend's denylist fails open on purpose; here a wrong "yes"
 * would show a feature the deployment excluded, and a wrong "no" only
 * hides one for a moment.
 */
export const usePlugins = () => {
	const query = useQuery({
		queryKey: pluginsKey,
		queryFn: ({ signal }) => listPlugins(signal),
		// Only changes when the server restarts; a page reload picks it up.
		staleTime: Infinity,
	});

	const loaded = query.data?.plugins;

	const plugins = useMemo(
		() =>
			loaded
				? FRONTEND_PLUGINS.filter((plugin) => loaded.includes(plugin.name))
				: [],
		[loaded],
	);

	return { plugins, isPending: query.isPending };
};

/**
 * Where a typed message should take the user instead of being sent, or
 * null to send it as usual.
 *
 * Matches the way ChatService splits a command — whitespace-separated,
 * case-sensitive — and only the bare form: "/recycle show_catalog" with
 * anything after it is not the same command any more, so it goes to the
 * backend. A user who may not see the target section is not redirected
 * either; their message goes through and the backend refuses it with its
 * usual reply.
 */
export const useCommandRedirect = () => {
	const { plugins } = usePlugins();
	const auth = useAuth();

	return useCallback(
		(text: string): string | null => {
			const [first, subcommand, ...rest] = text.trim().split(/\s+/);

			if (!first?.startsWith("/") || !subcommand || rest.length > 0) {
				return null;
			}

			if (auth.status !== "authenticated") {
				return null;
			}

			for (const plugin of plugins) {
				for (const redirect of plugin.commandRedirects ?? []) {
					if (
						first !== `/${redirect.namespace}` ||
						!redirect.subcommands.includes(subcommand)
					) {
						continue;
					}

					const targetId = pluginSectionId(plugin.name, redirect.section);
					const target = pluginSections([plugin]).find(
						(section) => section.id === targetId,
					);

					return target && canSee(auth.user.role, target)
						? sectionPath(target)
						: null;
				}
			}

			return null;
		},
		[plugins, auth],
	);
};
