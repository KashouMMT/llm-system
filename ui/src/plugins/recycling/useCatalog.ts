import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { fetchCatalog, type CatalogQuery } from "./api";

export const useCatalog = (query: CatalogQuery) => {
	return useQuery({
		queryKey: ["plugins", "recycling", "catalog", query],
		queryFn: ({ signal }) => fetchCatalog(query, signal),
		// Keep showing the current page while the next one loads, so paging
		// and typing in the search box do not flash an empty table.
		placeholderData: keepPreviousData,
	});
};
