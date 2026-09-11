import {
	type ChangeEvent,
	type FormEvent,
	type UIEvent,
	useEffect,
	useRef,
	useState,
} from "react";
import { useTranslation } from "react-i18next";
import type { Message, MessageStatus } from "../api/types";
import type { Attachments } from "../hooks/useAttachments";
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
	attachments: Attachments;
	onToggleSidebar: () => void;
};

// How close to the bottom counts as "following along".
const NEAR_BOTTOM_PX = 80;

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
	attachments,
	onToggleSidebar,
}: ChatProps) => {
	const { t } = useTranslation();

	const [input, setInput] = useState("");
	const fileInputRef = useRef<HTMLInputElement>(null);

	// Built from `t` per render rather than as module constants, so they
	// follow a language switch. Cheap: a handful of lookups.
	const statusLabel: Record<StreamStatus, string> = {
		idle: t("chat.statusIdle"),
		connecting: t("chat.statusConnecting"),
		open: t("chat.statusOpen"),
		closed: t("chat.statusClosed"),
	};

	// Only the outcomes worth explaining to the reader; a finished answer
	// and one still arriving need no note.
	const outcomeNote = (status: MessageStatus): string | undefined => {
		switch (status) {
			case "interrupted":
				return t("chat.noteInterrupted");
			case "cancelled":
				return t("chat.noteCancelled");
			case "failed":
				return t("chat.noteFailed");
			default:
				return undefined;
		}
	};

	const errorText = (error: ChatError): string => {
		switch (error.kind) {
			case "busy":
				return t("chat.errBusy");
			case "missing":
				return t("chat.errMissing");
			case "invalid":
				return error.message;
			case "network":
				return t("chat.errNetwork");
			default:
				return error.message;
		}
	};

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
		const attachmentIds = attachments.attachedIds;

		if ((!text.trim() && attachmentIds.length === 0) || !conversationId) {
			return;
		}

		setInput("");
		pinnedRef.current = true;

		void chat.send(text, attachmentIds).then((result) => {
			// A refused turn must not cost the user their typing or
			// re-upload their files.
			if (result === null) {
				setInput(text);
			} else {
				attachments.clear();
			}
		});
	};

	const handleFilesPicked = (event: ChangeEvent<HTMLInputElement>) => {
		if (event.target.files) {
			attachments.addFiles(event.target.files);
		}

		// Clears the input's own value so picking the same file again (after
		// removing its chip) fires onChange a second time.
		event.target.value = "";
	};

	const canSend =
		Boolean(conversationId) &&
		(Boolean(input.trim()) || attachments.attachedIds.length > 0) &&
		!chat.isSending &&
		!isGenerating &&
		!attachments.isUploading;

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
						<h5 className="mb-0">{t("chat.assistant")}</h5>

						<small className="text-secondary">
							{isGenerating
								? t("chat.generating")
								: statusLabel[stream.status]}
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
							{t("chat.pickConversation")}
						</p>
					)}

					{isLoading && (
						<p className="text-secondary">
							{t("chat.loadingMessages")}
						</p>
					)}

					{loadError && (
						<p className="text-danger">{t("chat.loadError")}</p>
					)}

					{conversationId &&
						!isLoading &&
						!loadError &&
						messages.length === 0 && (
							<p className="text-secondary">
								{t("chat.noMessages")}
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

						const note = outcomeNote(message.status);

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
						{t("chat.joinedLate")}
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
									{t("chat.retry")}
								</button>
							)}

							<button
								type="button"
								className="btn-close"
								aria-label={t("chat.dismiss")}
								onClick={chat.clearError}
							/>
						</span>
					</div>
				)}

				{attachments.slots.length > 0 && (
					<ul className="attachment-chips">
						{attachments.slots.map((slot) => (
							<li
								key={slot.localId}
								className={`attachment-chip attachment-chip-${slot.status}`}
							>
								<span className="attachment-chip-name">
									{slot.file.name}
								</span>

								{slot.status === "uploading" && (
									<span className="attachment-chip-status">
										{t("chat.attachmentUploading")}
									</span>
								)}

								{slot.status === "error" && (
									<span className="attachment-chip-status text-danger">
										{slot.errorMessage ??
											t("chat.attachmentError")}
									</span>
								)}

								<button
									type="button"
									className="attachment-chip-remove"
									aria-label={t("chat.attachmentRemove")}
									onClick={() =>
										attachments.removeSlot(slot.localId)
									}
								>
									×
								</button>
							</li>
						))}
					</ul>
				)}

				<form className="chat-input" onSubmit={handleSubmit}>
					<input
						ref={fileInputRef}
						type="file"
						multiple
						hidden
						onChange={handleFilesPicked}
					/>

					<button
						type="button"
						className="btn btn-outline-secondary attachment-button"
						aria-label={t("chat.attach")}
						disabled={!conversationId}
						onClick={() => fileInputRef.current?.click()}
					>
						<i className="bi bi-paperclip" aria-hidden="true" />
					</button>

					<textarea
						className="form-control"
						ref={textareaRef}
						rows={1}
						placeholder={
							conversationId
								? t("chat.inputPlaceholder")
								: t("chat.inputPlaceholderNoConv")
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
						{chat.isSending ? t("chat.sending") : t("chat.send")}
					</button>
				</form>
			</div>
		</section>
	);
};

export default Chat;
