import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { ApiError } from "../api/client";
import type { SettingDescription, SettingValue } from "../api/types";
import {
	usePromptSets,
	useResetSetting,
	useSettings,
	useUpdateSettings,
} from "../hooks/useSettings";

/**
 * How one runtime setting is edited. `min`/`max`/`step` only shape the
 * spinner: the form is noValidate and the server is the one validator, so
 * a rule is never enforced in two places that could disagree.
 */
export type FieldSpec =
	| { key: string; kind: "integer" }
	| { key: string; kind: "decimal"; min?: number; max?: number; step: number }
	| { key: string; kind: "logLevel" }
	| { key: string; kind: "promptSet" };

// Mirrors LOG_LEVELS in app/config/runtime_settings.py.
const LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

/**
 * Typed text → the JSON value sent. Anything that is not cleanly a number
 * is sent as typed, so the server's own message explains what is wrong
 * with it. An integer field sends "1.5" as text on purpose: as a number,
 * Python's int() would quietly truncate it to 1.
 */
const toValue = (field: FieldSpec, text: string): SettingValue => {
	const trimmed = text.trim();

	if (field.kind === "integer") {
		return /^-?\d+$/.test(trimmed) ? Number(trimmed) : text;
	}

	if (field.kind === "decimal") {
		const number = Number(trimmed);

		return trimmed !== "" && Number.isFinite(number) ? number : text;
	}

	return text;
};

type InputProps = {
	id: string;
	value: string;
	onChange: (text: string) => void;
};

const Select = ({
	id,
	value,
	onChange,
	options,
	unlistedLabel,
}: InputProps & { options: readonly string[]; unlistedLabel: string }) => (
	<select
		id={id}
		className="form-select settings-input"
		value={value}
		onChange={(event) => onChange(event.target.value)}
	>
		{/* A live value outside the list is still shown, labelled, so the
		    select never silently displays the first option instead. */}
		{!options.includes(value) && <option value={value}>{unlistedLabel}</option>}

		{options.map((option) => (
			<option key={option} value={option}>
				{option}
			</option>
		))}
	</select>
);

// Its own component so only this field fetches the folder list.
const PromptSetSelect = (props: InputProps) => {
	const { t } = useTranslation();
	const promptSets = usePromptSets();

	return (
		<Select
			{...props}
			options={promptSets.data?.prompt_sets ?? []}
			// The list holds complete sets only. A live value outside it
			// names an incomplete set, which the server accepts but runs
			// as "default".
			unlistedLabel={t("settings.incompleteSet", { name: props.value })}
		/>
	);
};

const FieldInput = ({
	field,
	...props
}: InputProps & { field: FieldSpec }) => {
	if (field.kind === "promptSet") {
		return <PromptSetSelect {...props} />;
	}

	if (field.kind === "logLevel") {
		return (
			<Select {...props} options={LOG_LEVELS} unlistedLabel={props.value} />
		);
	}

	const { id, value, onChange } = props;

	return (
		<input
			id={id}
			type="number"
			className="form-control settings-input"
			value={value}
			min={field.kind === "decimal" ? field.min : 1}
			max={field.kind === "decimal" ? field.max : undefined}
			step={field.kind === "decimal" ? field.step : 1}
			onChange={(event) => onChange(event.target.value)}
		/>
	);
};

const errorMessage = (error: unknown, fallback: string): string =>
	// A 422 carries the server's reason as a string — the cross-field rules
	// ("max_tokens must be less than context_window…") only exist there.
	error instanceof ApiError && typeof error.detail === "string"
		? error.detail
		: fallback;

type RuntimeSettingsFormProps = {
	fields: readonly FieldSpec[];
};

/**
 * One form over GET/PATCH /settings, shared by every CORE section.
 *
 * Saved as one batch per section rather than per field: several of these
 * fields constrain each other, and the server checks the merged result,
 * so changing two of them one at a time can pass through a state it
 * rejects even when the final pair is valid.
 */
const RuntimeSettingsForm = ({ fields }: RuntimeSettingsFormProps) => {
	const { t } = useTranslation();
	const settingsQuery = useSettings();
	const update = useUpdateSettings();
	const reset = useResetSetting();

	// Only what the user has typed. Every other field shows the server's
	// value straight from the query, so a save or reset shows through with
	// nothing to resync.
	const [edits, setEdits] = useState<Record<string, string>>({});
	const [error, setError] = useState<string | null>(null);
	const [saved, setSaved] = useState(false);

	if (settingsQuery.isPending) {
		return <p className="settings-status">{t("settings.loading")}</p>;
	}

	if (settingsQuery.isError) {
		return <p className="settings-error">{t("settings.loadError")}</p>;
	}

	const settings = settingsQuery.data;

	const shown = (key: string): string =>
		edits[key] ?? String(settings[key]?.value ?? "");

	const changed = fields.filter(
		(field) =>
			field.key in edits &&
			edits[field.key] !== String(settings[field.key]?.value),
	);

	const edit = (key: string, text: string) => {
		setEdits((previous) => ({ ...previous, [key]: text }));
		setSaved(false);
	};

	const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
		event.preventDefault();
		setError(null);

		update.mutate(
			Object.fromEntries(
				changed.map((field) => [
					field.key,
					toValue(field, edits[field.key]),
				]),
			),
			{
				onSuccess: () => {
					setEdits({});
					setSaved(true);
				},
				onError: (failure) =>
					setError(errorMessage(failure, t("settings.errGeneric"))),
			},
		);
	};

	const handleReset = (key: string) => {
		setError(null);
		setSaved(false);

		reset.mutate(key, {
			onSuccess: () =>
				setEdits((previous) => {
					const next = { ...previous };
					delete next[key];
					return next;
				}),
			onError: (failure) =>
				setError(errorMessage(failure, t("settings.errGeneric"))),
		});
	};

	const busy = update.isPending || reset.isPending;

	return (
		<form className="settings-form" onSubmit={handleSubmit} noValidate>
			{fields.map((field) => {
				const entry: SettingDescription | undefined = settings[field.key];

				// A key the server no longer describes: skip it rather than
				// render a control that can only be refused.
				if (!entry) {
					return null;
				}

				const inputId = `setting-${field.key}`;

				return (
					<div key={field.key} className="settings-field">
						<label htmlFor={inputId} className="settings-field-label">
							{t(`settings.fields.${field.key}.label`)}

							{!entry.persisted && (
								<span className="settings-badge">
									{t("settings.sessionOnly")}
								</span>
							)}
						</label>

						<FieldInput
							field={field}
							id={inputId}
							value={shown(field.key)}
							onChange={(text) => edit(field.key, text)}
						/>

						<p className="settings-field-help">
							{t(`settings.fields.${field.key}.help`)}
						</p>

						<div className="settings-field-meta">
							<span>
								{t("settings.defaultValue", {
									value: String(entry.default),
								})}
							</span>

							{entry.value !== entry.default && (
								<button
									type="button"
									className="settings-reset"
									disabled={busy}
									onClick={() => handleReset(field.key)}
								>
									{t("settings.reset")}
								</button>
							)}
						</div>
					</div>
				);
			})}

			{error && (
				<p className="settings-error" role="alert">
					{error}
				</p>
			)}

			<div className="settings-actions">
				<button
					type="submit"
					className="btn btn-primary"
					disabled={busy || changed.length === 0}
				>
					{update.isPending ? t("settings.saving") : t("settings.save")}
				</button>

				<button
					type="button"
					className="btn btn-outline-secondary"
					disabled={busy || Object.keys(edits).length === 0}
					onClick={() => {
						setEdits({});
						setError(null);
					}}
				>
					{t("settings.discard")}
				</button>

				{saved && (
					<span className="settings-status" role="status">
						{t("settings.saved")}
					</span>
				)}
			</div>
		</form>
	);
};

export default RuntimeSettingsForm;
