export type MessageRole = "user" | "assistant";

/**
 * Mirrors MESSAGE_STATUSES in app/database/migrations.py.
 *
 * "streaming" means the row exists but generation has not finished, so its
 * content is still empty in the database — the text is only on the wire.
 */
export type MessageStatus =
	| "streaming"
	| "complete"
	| "interrupted"
	| "cancelled"
	| "failed";

export type Message = {
	id: number;
	role: MessageRole;
	content: string;
	created_at: string;
	status: MessageStatus;
};

export type Conversation = {
	id: string;
	title: string;
	created_at: string;
	updated_at: string;
};

export type CreateConversationResponse = {
	id: string;
};

export type SendMessageRequest = {
	client_message_id: string;
	message: string;
};

export type SendMessageResponse = {
	user_message_id: number;
	assistant_message_id: number;
};

/**
 * Every SSE frame carries this envelope; see Event.to_wire() in
 * app/runtime/event_bus.py. `v` lets the server change payload shapes
 * without silently breaking older tabs.
 */
export type ServerEventEnvelope<TPayload> = {
	v: number;
	type: string;
	conversation_id: string;
	payload: TPayload;
};

export type MessageCreatedPayload = {
	message_id: number;
	role: MessageRole;
	content: string;
	status: MessageStatus;
	created_at: string;
	// Present on the user row only — the id this client generated.
	client_message_id?: string;
	// Present on the assistant row only.
	reply_to_message_id?: number;
};

export type MessageDeltaPayload = {
	message_id: number;
	// Starts at 1. A first observed delta above 1 means this client
	// connected after generation had already started.
	seq: number;
	text: string;
};

/**
 * Shared by message.completed, message.cancelled and message.failed.
 * `content` is the full, final text — no refetch is needed to render it.
 */
export type MessageTerminalPayload = {
	message_id: number;
	content: string;
	status: MessageStatus;
};

export type ConversationUpdatedPayload = {
	conversation_id: string;
};

export const EVENT_MESSAGE_CREATED = "message.created";
export const EVENT_MESSAGE_DELTA = "message.delta";
export const EVENT_MESSAGE_COMPLETED = "message.completed";
export const EVENT_MESSAGE_CANCELLED = "message.cancelled";
export const EVENT_MESSAGE_FAILED = "message.failed";
export const EVENT_CONVERSATION_UPDATED = "conversation.updated";
