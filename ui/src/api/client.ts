import type {
	AuthUser,
	Conversation,
	CreateConversationResponse,
	CreateUserRequest,
	ManagedUser,
	Message,
	PluginsResponse,
	PromptSetsResponse,
	RenameConversationRequest,
	RuntimeSettings,
	SendMessageRequest,
	SendMessageResponse,
	SettingValue,
	UpdateUserRequest,
	UploadedAttachment,
} from "./types";

// Exported for frontend plugins, which build their own endpoint URLs
// rather than adding functions here.
export const API_BASE_URL =
	import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/**
 * A non-2xx response, carrying FastAPI's `detail` untouched.
 *
 * `detail` is deliberately `unknown`: FastAPI returns a string for
 * HTTPException(detail="..."), an object for the 409 lock case, and a list
 * for request validation errors. Callers narrow it themselves.
 */
export class ApiError extends Error {
	readonly status: number;
	readonly detail: unknown;

	constructor(status: number, detail: unknown) {
		super(`Request failed with status ${status}`);

		this.name = "ApiError";
		this.status = status;
		this.detail = detail;
	}
}

/**
 * Reads one cookie by name. Used for the CSRF token, which the server
 * sets as a readable (non-HttpOnly) cookie for exactly this purpose.
 */
function readCookie(name: string): string | null {
	const prefix = `${name}=`;

	for (const part of document.cookie.split("; ")) {
		if (part.startsWith(prefix)) {
			return decodeURIComponent(part.slice(prefix.length));
		}
	}

	return null;
}

async function readDetail(response: Response): Promise<unknown> {
	try {
		const body = await response.json();

		if (body && typeof body === "object" && "detail" in body) {
			return (body as { detail: unknown }).detail;
		}

		return body;
	} catch {
		return response.statusText;
	}
}

/**
 * Every API call goes through here: credentials, the CSRF header, and
 * ApiError on a non-2xx. Exported for frontend plugins, which keep their
 * own endpoint functions in their folder rather than in this file.
 */
export async function request<TResponse>(
	path: string,
	init?: RequestInit,
): Promise<TResponse> {
	const method = (init?.method ?? "GET").toUpperCase();

	// The server's CSRF gate wants the signed double-submit token echoed
	// back on every state-changing request. Safe methods don't carry it.
	const csrfToken =
		method === "GET" || method === "HEAD"
			? null
			: readCookie("csrf_token");

	const response = await fetch(`${API_BASE_URL}${path}`, {
		...init,
		// Harmless today; required once sessions become an httpOnly cookie,
		// because EventSource cannot send an Authorization header.
		credentials: "include",
		headers: {
			// Only set on requests that actually carry a body — declaring
			// application/json on a bodyless GET isn't a safelisted CORS
			// value and costs a preflight OPTIONS round trip for nothing.
			...(init?.body ? { "Content-Type": "application/json" } : {}),
			...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
			...init?.headers,
		},
	});

	if (!response.ok) {
		throw new ApiError(response.status, await readDetail(response));
	}

	// 204 (logout) carries no body; calling .json() on it throws.
	if (response.status === 204) {
		return undefined as TResponse;
	}

	return (await response.json()) as TResponse;
}

export function getCurrentUser(signal?: AbortSignal): Promise<AuthUser> {
	return request<AuthUser>("/auth/me", { signal });
}

export function login(credentials: {
	email: string;
	password: string;
}): Promise<AuthUser> {
	return request<AuthUser>("/auth/login", {
		method: "POST",
		body: JSON.stringify(credentials),
	});
}

export function logout(): Promise<void> {
	return request<void>("/auth/logout", { method: "POST" });
}

/**
 * Creates a normal-role account. Does not sign the user in — the caller
 * sends the same credentials to `login` afterwards. Rejects with an
 * ApiError of status 409 if the email is already registered.
 */
export function register(credentials: {
	email: string;
	password: string;
}): Promise<AuthUser> {
	return request<AuthUser>("/auth/register", {
		method: "POST",
		body: JSON.stringify(credentials),
	});
}

export function listConversations(
	signal?: AbortSignal,
): Promise<Conversation[]> {
	return request<Conversation[]>("/conversations", { signal });
}

export function createConversation(): Promise<CreateConversationResponse> {
	return request<CreateConversationResponse>("/conversations", {
		method: "POST",
	});
}

export function renameConversation(
	conversationId: string,
	title: string,
): Promise<Conversation> {
	const body: RenameConversationRequest = { title };

	return request<Conversation>(`/conversations/${conversationId}`, {
		method: "PATCH",
		body: JSON.stringify(body),
	});
}

export function listMessages(
	conversationId: string,
	signal?: AbortSignal,
): Promise<Message[]> {
	return request<Message[]>(`/conversations/${conversationId}/messages`, {
		signal,
	});
}

/**
 * Opens a turn. Resolves as soon as the rows exist (202) — the tokens
 * arrive separately on the event stream, to every subscriber including
 * this one. Returns 200 with the same ids if this client_message_id was
 * already used, which is what makes a retry safe.
 */
export function sendMessage(
	conversationId: string,
	body: SendMessageRequest,
): Promise<SendMessageResponse> {
	return request<SendMessageResponse>(
		`/conversations/${conversationId}/messages`,
		{
			method: "POST",
			body: JSON.stringify(body),
		},
	);
}

/**
 * Uploads one file, unattached to any message yet — sendMessage attaches
 * it afterward by id.
 *
 * The body is the file's raw bytes, not multipart, and Content-Type is
 * deliberately application/octet-stream rather than the file's own type:
 * the server never trusts the header anyway (it sniffs the real type from
 * the bytes), and the CSRF gate rejects text/plain and the multipart/
 * form-urlencoded encodings outright — sending a .txt file's real
 * text/plain type here would be blocked before the request ever reached
 * the route. filename goes in the query string, percent-encoded, since it
 * may be Japanese and header values are restricted to latin-1.
 */
export function uploadFile(
	conversationId: string,
	file: File,
): Promise<UploadedAttachment> {
	return request<UploadedAttachment>(
		`/conversations/${conversationId}/uploads?filename=${encodeURIComponent(file.name)}`,
		{
			method: "POST",
			headers: { "Content-Type": "application/octet-stream" },
			body: file,
		},
	);
}

export function getSettings(signal?: AbortSignal): Promise<RuntimeSettings> {
	return request<RuntimeSettings>("/settings", { signal });
}

/**
 * Applies a batch of changes all-or-nothing and resolves to the full
 * settings afterwards. A rejected batch is an ApiError of status 422 whose
 * detail is the server's reason as a plain string. Admin only.
 */
export function updateSettings(
	changes: Record<string, SettingValue>,
): Promise<RuntimeSettings> {
	return request<RuntimeSettings>("/settings", {
		method: "PATCH",
		body: JSON.stringify(changes),
	});
}

/** Restores one setting's environment default. Admin only. */
export function resetSetting(key: string): Promise<RuntimeSettings> {
	return request<RuntimeSettings>(`/settings/${encodeURIComponent(key)}`, {
		method: "DELETE",
	});
}

export function listPromptSets(
	signal?: AbortSignal,
): Promise<PromptSetsResponse> {
	return request<PromptSetsResponse>("/settings/prompt-sets", { signal });
}

export function eventsUrl(conversationId: string): string {
	return `${API_BASE_URL}/events?conversation_id=${conversationId}`;
}

/**
 * Absolute URL for a generated file.
 *
 * A plain link rather than a fetch: the response carries
 * Content-Disposition: attachment, so the browser downloads it without
 * navigating away, and a cross-origin GET navigation still sends the
 * SameSite=Lax session cookie. Fetching it would mean holding the whole
 * file in memory to hand back to the same browser.
 */
export function fileDownloadUrl(fileId: string): string {
	return `${API_BASE_URL}/files/${fileId}`;
}

// ---- users (root only) -------------------------------------------------
// A refused change comes back as 404/409/422 with the server's reason as a
// string detail; never 403, which the app treats as a stale CSRF token.

export function listUsers(signal?: AbortSignal): Promise<ManagedUser[]> {
	return request<ManagedUser[]>("/users", { signal });
}

export function createUser(body: CreateUserRequest): Promise<ManagedUser> {
	return request<ManagedUser>("/users", {
		method: "POST",
		body: JSON.stringify(body),
	});
}

export function updateUser(
	id: string,
	body: UpdateUserRequest,
): Promise<ManagedUser> {
	return request<ManagedUser>(`/users/${id}`, {
		method: "PATCH",
		body: JSON.stringify(body),
	});
}

export function deleteUser(id: string): Promise<void> {
	return request<void>(`/users/${id}`, { method: "DELETE" });
}

export function listPlugins(signal?: AbortSignal): Promise<PluginsResponse> {
	return request<PluginsResponse>("/plugins", { signal });
}
