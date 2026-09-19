import { request } from "../../api/client";

/** Mirrors the flat columns of recycling_catalog_items; null = unknown. */
export type CatalogRow = {
	id: string;
	position: number;
	canonical_label: string;
	aliases: string[];
	visual_class: string | null;
	excluded: boolean;
	exclusion_reason: string | null;
	observations: number;
	weight_kg: number | null;
	weight_kg_min: number | null;
	weight_kg_max: number | null;
	length_cm: number | null;
	width_cm: number | null;
	height_cm: number | null;
	volume_m3: number | null;
	material: string | null;
	nestable: boolean | null;
	stackable: boolean | null;
	unit_price: number | null;
	currency: string | null;
	extra: Record<string, string>;
	source: string;
	updated_at: string;
	evidence: CatalogEvidence[];
};

export type CatalogEvidence = {
	file_id: string;
	/** The frame's index in its video; null for a photo. */
	frame_index: number | null;
	/** What the model called it, before clustering mapped it to this row. */
	raw_label: string;
};

export type CatalogPage = {
	total: number;
	offset: number;
	limit: number;
	visual_classes: string[];
	items: CatalogRow[];
};

export type CatalogQuery = {
	search: string;
	visualClass: string;
	/** "" for both. */
	excluded: "" | "true" | "false";
	offset: number;
	limit: number;
};

export function fetchCatalog(
	query: CatalogQuery,
	signal?: AbortSignal,
): Promise<CatalogPage> {
	const params = new URLSearchParams({
		offset: String(query.offset),
		limit: String(query.limit),
	});

	// Empty filters are left off rather than sent blank: excluded="" would
	// fail the server's bool parsing, and visual_class="" would match none.
	if (query.search.trim()) {
		params.set("search", query.search.trim());
	}

	if (query.visualClass) {
		params.set("visual_class", query.visualClass);
	}

	if (query.excluded) {
		params.set("excluded", query.excluded);
	}

	return request<CatalogPage>(`/plugins/recycling/catalog?${params}`, {
		signal,
	});
}
