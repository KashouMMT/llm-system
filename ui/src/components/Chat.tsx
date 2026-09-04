import {
	type FormEvent,
	type UIEvent,
	useEffect,
	useRef,
	useState,
} from "react";
import type { Message, MessageStatus } from "../api/types";
import type { ChatError, useChat } from "../hooks/useChat";
import type {
	ConversationStream,
	StreamStatus,
} from "../hooks/useConversationStream";
import { fileDownloadUrl } from "../api/client";
import Markdown from "./Markdown";

import "../assets/css/chat.css";

type ChatProps = {
	conversationId: string | undefined;
	messages: Message[];
	isLoading: boolean;
	loadError: Error | null;
	stream: ConversationStream;
	chat: ReturnType<typeof useChat>;
	onToggleSidebar: () => void;
};

// How close to the bottom counts as "following along".
const NEAR_BOTTOM_PX = 80;

const STATUS_LABEL: Record<StreamStatus, string> = {
	idle: "No conversation",
	connecting: "Connecting…",
	open: "Online",
	closed: "Disconnected",
};

// Only the outcomes worth explaining to the reader; a finished answer and
// one still arriving need no note.
const OUTCOME_NOTE: Partial<Record<MessageStatus, string>> = {
	interrupted: "The server stopped before this answer finished.",
	cancelled: "This answer was cancelled.",
	failed: "This answer failed to generate.",
};

const errorText = (error: ChatError): string => {
	switch (error.kind) {
		case "busy":
			return "This conversation is already generating an answer.";
		case "missing":
			return "This conversation no longer exists.";
		case "invalid":
			return error.message;
		case "network":
			return "Could not reach the server.";
		default:
			return error.message;
	}
};

const formatBytes = (bytes: number): string => {
	if (bytes < 1024) {
		return `${bytes} B`;
	}

	if (bytes < 1024 * 1024) {
		return `${Math.round(bytes / 1024)} KB`;
	}

	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
};

const Chat = ({
	conversationId,
	messages,
	isLoading,
	loadError,
	stream,
	chat,
	onToggleSidebar,
}: ChatProps) => {
	const [input, setInput] = useState("");

	const scrollRef = useRef<HTMLDivElement>(null);
	const textareaRef = useRef<HTMLTextAreaElement>(null);

	// Whether the reader is following the bottom of the transcript. A ref,
	// not state: it changes on every scroll event and nothing renders from
	// it, so putting it in state would only cause renders.
	const pinnedRef = useRef(true);

	// Grows the box to fit typed content, up to the CSS max-height cap —
	// past that, the textarea scrolls internally instead of growing further.
	useEffect(() => {
		const element = textareaRef.current;

		if (!element) {
			return;
		}

		element.style.height = "auto";
		element.style.height = `${element.scrollHeight}px`;
	}, [input]);

	// Derived from the transcript rather than from this tab's own send, so
	// a turn started in another tab disables this composer too.
	const isGenerating = messages.some(
		(message) => message.status === "streaming",
	);

	// No dependency list on purpose: drafts change identity on every
	// animation frame while tokens arrive, and this must run after each of
	// those commits.
	useEffect(() => {
		const element = scrollRef.current;

		if (!element || !pinnedRef.current) {
			return;
		}

		element.scrollTop = element.scrollHeight;
	});

	const handleScroll = (event: UIEvent<HTMLDivElement>) => {
		const element = event.currentTarget;

		pinnedRef.current =
			element.scrollHeight - element.scrollTop - element.clientHeight <
			NEAR_BOTTOM_PX;
	};

	const handleSubmit = (event: FormEvent) => {
		event.preventDefault();

		const text = input;

		if (!text.trim() || !conversationId) {
			return;
		}

		setInput("");
		pinnedRef.current = true;

		void chat.send(text).then((result) => {
			// A refused turn must not cost the user their typing.
			if (result === null) {
				setInput(text);
			}
		});
	};

	const canSend =
		Boolean(conversationId) &&
		Boolean(input.trim()) &&
		!chat.isSending &&
		!isGenerating;

	return (
		<section className="chat-section">
			<div className="chat-container">
				<div className="chat-header">
					<button
						type="button"
						className="btn btn-outline-secondary sidebar-toggle d-lg-none d-md-none"
						onClick={onToggleSidebar}
					>
						☰
					</button>

					<div>
						<h5 className="mb-0">AI Assistant</h5>

						<small className="text-secondary">
							{isGenerating
								? "Generating…"
								: STATUS_LABEL[stream.status]}
						</small>
					</div>
				</div>

				<div
					className="chat-messages"
					ref={scrollRef}
					onScroll={handleScroll}
				>
					{!conversationId && (
						<p className="text-secondary">
							Pick a conversation, or start a new one.
						</p>
					)}

					{isLoading && (
						<p className="text-secondary">Loading messages…</p>
					)}

					{loadError && (
						<p className="text-danger">
							Could not load this conversation.
						</p>
					)}

					{conversationId &&
						!isLoading &&
						!loadError &&
						messages.length === 0 && (
							<p className="text-secondary">
								No messages yet — say something.
							</p>
						)}

					{messages.map((message) => {
						// While a turn is in flight the database row is
						// still empty — the text exists only on the wire,
						// in the draft. The terminal event replaces the
						// row's content and drops the draft, so this falls
						// back to the stored text on its own.
						const content =
							stream.drafts[message.id] ?? message.content;

						// A live draft exists only while tokens are arriving
						// into this tab; the terminal event deletes it, at
						// which point message.content holds the full text.
						const isStreaming =
							stream.drafts[message.id] !== undefined;

						const note = OUTCOME_NOTE[message.status];

						return (
							<div
								key={message.id}
								className={
									message.role === "user"
										? "message message-user"
										: "message message-ai"
								}
							>
								<div className="message-content">
									{content &&
										(message.role === "assistant" ? (
											<Markdown isStreaming={isStreaming}>
													{content}
												</Markdown>
										) : (
											content
										))}

									{!content &&
										message.status === "streaming" && (
											<span className="typing-indicator">
												<span />
												<span />
												<span />
											</span>
										)}

									{note && (
										<div className="mt-2 small text-secondary">
											{note}
										</div>
									)}

									{message.attachments.length > 0 && (
										<ul className="message-attachments">
											{message.attachments.map((attachment) => (
												<li key={attachment.id}>
													<a
														className="message-attachment"
														href={fileDownloadUrl(attachment.id)}
													>
														{attachment.filename}
													</a>

													<span className="message-attachment-size">
														{formatBytes(attachment.size_bytes)}
													</span>
												</li>
											))}
										</ul>
									)}
								</div>
							</div>
						);
					})}
				</div>

				{stream.joinedLate && (
					<div className="alert alert-info m-3 mb-0 py-2 small">
						Joined while an answer was already in progress — showing
						it from here.
					</div>
				)}

				{chat.error && (
					<div className="alert alert-warning m-3 mb-0 py-2 d-flex align-items-center justify-content-between">
						<span className="small">{errorText(chat.error)}</span>

						<span className="d-flex gap-2">
							{chat.error.kind !== "busy" && (
								<button
									type="button"
									className="btn btn-sm btn-outline-secondary"
									onClick={() => void chat.retry()}
								>
									Retry
								</button>
							)}

							<button
								type="button"
								className="btn-close"
								aria-label="Dismiss"
								onClick={chat.clearError}
							/>
						</span>
					</div>
				)}

				<form className="chat-input" onSubmit={handleSubmit}>
					<textarea
						className="form-control"
						ref={textareaRef}
						rows={1}
						placeholder={
							conversationId
								? "Type a message..."
								: "Select a conversation first"
						}
						value={input}
						disabled={!conversationId}
						onChange={(event) => setInput(event.target.value)}
					/>

					<button
						type="submit"
						className="btn btn-primary"
						disabled={!canSend}
					>
						{chat.isSending ? "Sending…" : "Send"}
					</button>
				</form>
			</div>
		</section>
	);
};

export default Chat;
