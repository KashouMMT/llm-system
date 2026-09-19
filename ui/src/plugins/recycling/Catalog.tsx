import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import "./catalog.css";
import { fileDownloadUrl } from "../../api/client";
import TableScroll from "../../components/TableScroll";
import type { CatalogEvidence, CatalogQuery, CatalogRow } from "./api";
import { useCatalog } from "./useCatalog";

const PAGE_SIZE = 50;
// Long enough that typing a word is one request, short enough to feel live.
const SEARCH_DEBOUNCE_MS = 300;

const DASH = "—";

const formatNumber = (value: number | null): string =>
	value === null ? DASH : String(value);

const formatWeight = (row: CatalogRow): string => {
	const base = row.weight_kg === null ? DASH : `${row.weight_kg} kg`;

	if (row.weight_kg_min === null || row.weight_kg_max === null) {
		return base;
	}

	return `${base} (${row.weight_kg_min}–${row.weight_kg_max})`;
};

const formatSize = (row: CatalogRow): string =>
	row.length_cm === null && row.width_cm === null && row.height_cm === null
		? DASH
		: [row.length_cm, row.width_cm, row.height_cm].map(formatNumber).join(" × ");

type PreviewProps = {
	evidence: CatalogEvidence;
	onClose: () => void;
};

/**
 * One evidence image, full size, over the page. An <img> rather than a
 * link: GET /files answers with Content-Disposition: attachment, which a
 * link turns into a download but an image element simply displays.
 */
const EvidencePreview = ({ evidence, onClose }: PreviewProps) => {
	const { t } = useTranslation();

	useEffect(() => {
		const onKey = (event: KeyboardEvent) => {
			if (event.key === "Escape") {
				onClose();
			}
		};

		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [onClose]);

	return (
		<div className="catalog-preview" role="dialog" aria-modal="true" onClick={onClose}>
			<figure
				className="catalog-preview-body"
				onClick={(event) => event.stopPropagation()}
			>
				<img src={fileDownloadUrl(evidence.file_id)} alt={evidence.raw_label} />

				<figcaption className="catalog-preview-caption">
					<span>
						{t("plugins.recycling.detectedAs", { label: evidence.raw_label })}
					</span>

					<a href={fileDownloadUrl(evidence.file_id)}>
						{t("plugins.recycling.download")}
					</a>

					<button type="button" className="theme-toggle" onClick={onClose}>
						{t("plugins.recycling.close")}
					</button>
				</figcaption>
			</figure>
		</div>
	);
};

/**
 * The catalog browser: search, filter and page through the catalog in the
 * database, with each row's evidence images a click away. Read-only —
 * edits go through the assistant's catalog tools, which show a reviewable
 * before/after for every change.
 */
const Catalog = () => {
	const { t } = useTranslation();

	const [searchInput, setSearchInput] = useState("");
	const [query, setQuery] = useState<CatalogQuery>({
		search: "",
		visualClass: "",
		excluded: "",
		offset: 0,
		limit: PAGE_SIZE,
	});
	const [preview, setPreview] = useState<CatalogEvidence | null>(null);

	// Every filter change goes back to the first page: page 7 of the old
	// filter means nothing under the new one.
	const filter = (changes: Partial<CatalogQuery>) =>
		setQuery((previous) => ({ ...previous, ...changes, offset: 0 }));

	useEffect(() => {
		const timer = window.setTimeout(
			() =>
				setQuery((previous) =>
					previous.search === searchInput
						? previous
						: { ...previous, search: searchInput, offset: 0 },
				),
			SEARCH_DEBOUNCE_MS,
		);

		return () => window.clearTimeout(timer);
	}, [searchInput]);

	const catalog = useCatalog(query);
	const page = catalog.data;
	const unfiltered =
		!query.search && !query.visualClass && !query.excluded;

	return (
		<div className="catalog">
			<div className="catalog-toolbar">
				<input
					type="search"
					className="form-control catalog-search"
					placeholder={t("plugins.recycling.search")}
					value={searchInput}
					onChange={(event) => setSearchInput(event.target.value)}
				/>

				<select
					className="form-select catalog-filter"
					value={query.visualClass}
					onChange={(event) => filter({ visualClass: event.target.value })}
				>
					<option value="">{t("plugins.recycling.allClasses")}</option>

					{page?.visual_classes.map((visualClass) => (
						<option key={visualClass} value={visualClass}>
							{visualClass}
						</option>
					))}
				</select>

				<select
					className="form-select catalog-filter"
					value={query.excluded}
					onChange={(event) =>
						filter({
							excluded: event.target.value as CatalogQuery["excluded"],
						})
					}
				>
					<option value="">{t("plugins.recycling.allStatuses")}</option>
					<option value="false">{t("plugins.recycling.collectable")}</option>
					<option value="true">{t("plugins.recycling.excluded")}</option>
				</select>
			</div>

			{catalog.isPending && (
				<p className="settings-status">{t("plugins.recycling.loading")}</p>
			)}

			{catalog.isError && (
				<p className="settings-error">{t("plugins.recycling.loadError")}</p>
			)}

			{page && page.total === 0 && (
				<p className="settings-status">
					{unfiltered
						? t("plugins.recycling.emptyCatalog")
						: t("plugins.recycling.empty")}
				</p>
			)}

			{page && page.total > 0 && (
				<>
					<TableScroll>
						<table
							className={`catalog-table${catalog.isPlaceholderData ? " stale" : ""}`}
						>
							<thead>
								<tr>
									<th>{t("plugins.recycling.columns.label")}</th>
									<th>{t("plugins.recycling.columns.visualClass")}</th>
									<th>{t("plugins.recycling.columns.status")}</th>
									<th>{t("plugins.recycling.columns.weight")}</th>
									<th>{t("plugins.recycling.columns.size")}</th>
									<th>{t("plugins.recycling.columns.material")}</th>
									<th>{t("plugins.recycling.columns.source")}</th>
									<th>{t("plugins.recycling.columns.seen")}</th>
									<th>{t("plugins.recycling.columns.evidence")}</th>
									<th>{t("plugins.recycling.columns.updated")}</th>
								</tr>
							</thead>

							<tbody>
								{page.items.map((row) => (
									<tr key={row.id}>
										<td>
											<div className="catalog-label">
												{row.canonical_label}
											</div>
											<div className="catalog-muted">{row.id}</div>
											{row.aliases.length > 0 && (
												<div className="catalog-muted">
													{row.aliases.join(", ")}
												</div>
											)}
										</td>
										<td>{row.visual_class ?? DASH}</td>
										<td>
											{row.excluded ? (
												<>
													{t("plugins.recycling.excluded")}
													{row.exclusion_reason && (
														<div className="catalog-muted">
															{row.exclusion_reason}
														</div>
													)}
												</>
											) : (
												t("plugins.recycling.collectable")
											)}
										</td>
										<td>{formatWeight(row)}</td>
										<td>{formatSize(row)}</td>
										<td>{row.material ?? DASH}</td>
										<td>{row.source}</td>
										<td>{row.observations}</td>
										<td>
											<div className="catalog-evidence">
												{row.evidence.length === 0
													? DASH
													: row.evidence.map((evidence) => (
															<button
																key={evidence.file_id}
																type="button"
																className="catalog-chip"
																onClick={() => setPreview(evidence)}
															>
																{evidence.frame_index === null
																	? t("plugins.recycling.photo")
																	: t("plugins.recycling.frame", {
																			index: evidence.frame_index,
																		})}
															</button>
														))}
											</div>
										</td>
										<td>
											{new Date(row.updated_at).toLocaleDateString()}
										</td>
									</tr>
								))}
							</tbody>
						</table>
					</TableScroll>

					<div className="catalog-pager">
						<button
							type="button"
							className="btn btn-outline-secondary btn-sm"
							disabled={page.offset === 0}
							onClick={() =>
								setQuery((previous) => ({
									...previous,
									offset: Math.max(0, previous.offset - PAGE_SIZE),
								}))
							}
						>
							{t("plugins.recycling.previous")}
						</button>

						<span className="settings-status">
							{t("plugins.recycling.range", {
								from: page.offset + 1,
								to: page.offset + page.items.length,
								total: page.total,
							})}
						</span>

						<button
							type="button"
							className="btn btn-outline-secondary btn-sm"
							disabled={page.offset + page.items.length >= page.total}
							onClick={() =>
								setQuery((previous) => ({
									...previous,
									offset: previous.offset + PAGE_SIZE,
								}))
							}
						>
							{t("plugins.recycling.next")}
						</button>
					</div>
				</>
			)}

			{preview && (
				<EvidencePreview evidence={preview} onClose={() => setPreview(null)} />
			)}
		</div>
	);
};

export default Catalog;
