import type {
	AuthUser,
	Conversation,
	CreateConversationResponse,
	Message,
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
	username: string;
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
