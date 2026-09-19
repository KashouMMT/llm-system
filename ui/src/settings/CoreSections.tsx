import RuntimeSettingsForm, { type FieldSpec } from "./RuntimeSettingsForm";

// Grouped by what an admin is trying to change, not by the backend's
// module layout. Every key here must be in FIELD_PARSERS
// (app/config/runtime_settings.py); a key the server does not describe is
// skipped by the form rather than shown.

const GENERAL: readonly FieldSpec[] = [
	{ key: "system_prompt_name", kind: "promptSet" },
	{ key: "log_level", kind: "logLevel" },
];

const LLM: readonly FieldSpec[] = [
	{ key: "temperature", kind: "decimal", min: 0, max: 2, step: 0.05 },
	{ key: "top_p", kind: "decimal", min: 0, max: 1, step: 0.05 },
	{ key: "top_k", kind: "integer" },
	{ key: "max_tokens", kind: "integer" },
	{ key: "context_window", kind: "integer" },
];

// The three *_messages windows constrain each other (as max_tokens and
// context_window do above), so they share a section and save as one batch.
const MEMORY: readonly FieldSpec[] = [
	{ key: "summary_token_threshold", kind: "integer" },
	{ key: "max_summary_chars", kind: "integer" },
	{ key: "max_context_history_messages", kind: "integer" },
	{ key: "max_unsummarized_messages", kind: "integer" },
	{ key: "min_retained_raw_messages", kind: "integer" },
	{ key: "max_checkpoint_messages", kind: "integer" },
];

const STREAMING: readonly FieldSpec[] = [
	{ key: "sse_heartbeat_seconds", kind: "decimal", min: 1, step: 1 },
	{ key: "sse_queue_maxsize", kind: "integer" },
];

export const GeneralSection = () => <RuntimeSettingsForm fields={GENERAL} />;
export const LlmSection = () => <RuntimeSettingsForm fields={LLM} />;
export const MemorySection = () => <RuntimeSettingsForm fields={MEMORY} />;
export const StreamingSection = () => (
	<RuntimeSettingsForm fields={STREAMING} />
);
