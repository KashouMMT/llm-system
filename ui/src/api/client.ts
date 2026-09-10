import type {
	AuthUser,
	Conversation,
	CreateConversationResponse,
	Message,
	RenameConversationRequest,
	SendMessageRequest,
	SendMessageResponse,
} from "./types";

const API_BASE_URL =
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

async function request<TResponse>(
	path: string,
	init?: RequestInit,
): Promise<TResponse> {
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

/**
 * Absolute URL for a blank, fill-by-hand form.
 *
 * A plain link, for the same reasons as fileDownloadUrl: the response
 * carries Content-Disposition: attachment, and the SameSite=Lax session
 * cookie rides along on the GET navigation.
 *
 * docType is "rirekisho" or "shokumu_keirekisho".
 */
export function blankDocumentUrl(docType: string): string {
	return `${API_BASE_URL}/documents/blank/${docType}`;
}
