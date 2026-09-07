import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

import "../assets/css/sidebar.css";
import { blankDocumentUrl } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import {
	useConversations,
	useCreateConversation,
	useRenameConversation,
} from "../hooks/useConversations";

type SidebarProps = {
	isOpen: boolean;
	onClose: () => void;
};

// Matches Field(max_length=TITLE_MAX_CHARS) on PATCH /conversations; the
// server rejects anything longer with 422, this just stops the user
// getting there.
const TITLE_MAX_CHARS = 80;

// The empty forms a user can take without talking to the assistant first.
// Kept here rather than fetched: the two document types are fixed, and a
// request just to learn their names would delay the sidebar for nothing.
const BLANK_FORMS = [
	{ docType: "rirekisho", label: "履歴書", hint: "Rirekisho" },
	{
		docType: "shokumu_keirekisho",
		label: "職務経歴書",
		hint: "Shokumu Keirekisho",
	},
];

const Sidebar = ({ isOpen, onClose }: SidebarProps) => {
	const navigate = useNavigate();
	const auth = useAuth();

	const conversationsQuery = useConversations();
	const createConversation = useCreateConversation();
	const renameConversation = useRenameConversation();

	// Which conversation is being renamed inline, and its working text.
	// null means none — the list renders normally.
	const [editingId, setEditingId] = useState<string | null>(null);
	const [draft, setDraft] = useState("");

	const handleCreate = () => {
		createConversation.mutate(undefined, {
			onSuccess: (conversation) => {
				navigate(`/c/${conversation.id}`);
				onClose();
			},
		});
	};

	const startEditing = (id: string, currentTitle: string) => {
		setEditingId(id);
		setDraft(currentTitle);
	};

	const cancelEditing = () => {
		setEditingId(null);
		setDraft("");
	};

	const commitEditing = (id: string, currentTitle: string) => {
		const next = draft.trim();

		// Skip the request when nothing changed or the field was cleared —
		// an empty title is rejected by the server anyway.
		if (next && next !== currentTitle) {
			renameConversation.mutate({ id, title: next });
		}

		cancelEditing();
	};

	return (
		<>
			<div
				className={`sidebar-backdrop ${isOpen ? "show" : ""}`}
				onClick={onClose}
			/>

			<aside className={`sidebar ${isOpen ? "open" : ""}`}>
				<div className="sidebar-header">
					<button
						type="button"
						className="btn btn-primary w-100"
						onClick={handleCreate}
						disabled={createConversation.isPending}
					>
						{createConversation.isPending
							? "Creating…"
							: "+ New chat"}
					</button>
				</div>

				<div className="sidebar-conversations">
					{conversationsQuery.isPending && (
						<p className="small text-secondary px-2">Loading…</p>
					)}

					{conversationsQuery.isError && (
						<p className="small text-danger px-2">
							Could not load conversations.
						</p>
					)}

					{conversationsQuery.data?.length === 0 && (
						<p className="small text-secondary px-2">
							No conversations yet.
						</p>
					)}

					{/* NavLink rather than a button: a real href means
					    middle-click opens the same conversation in a second
					    tab, which is the fastest way to see the shared
					    stream working. The pen button beside it swaps the
					    row for an input to rename it in place. */}
					{conversationsQuery.data?.map((conversation) =>
						editingId === conversation.id ? (
							<input
								key={conversation.id}
								className="sidebar-conversation-edit"
								value={draft}
								autoFocus
								maxLength={TITLE_MAX_CHARS}
								onChange={(event) =>
									setDraft(event.target.value)
								}
								onBlur={() =>
									commitEditing(
										conversation.id,
										conversation.title,
									)
								}
								onKeyDown={(event) => {
									if (event.key === "Enter") {
										// Triggers onBlur, which commits.
										event.currentTarget.blur();
									} else if (event.key === "Escape") {
										cancelEditing();
									}
								}}
							/>
						) : (
							<div
								key={conversation.id}
								className="sidebar-conversation-row"
							>
								<NavLink
									to={`/c/${conversation.id}`}
									className={({ isActive }) =>
										`sidebar-conversation${isActive ? " active" : ""}`
									}
									onClick={onClose}
								>
									<span className="conversation-title">
										{conversation.title}
									</span>
								</NavLink>

								<button
									type="button"
									className="sidebar-conversation-rename"
									aria-label="Rename conversation"
									title="Rename"
									onClick={() =>
										startEditing(
											conversation.id,
											conversation.title,
										)
									}
								>
									<i
										className="bi bi-pen"
										aria-hidden="true"
									/>
								</button>
							</div>
						),
					)}
				</div>

				{/* Plain anchors, like the message attachments in Chat: the
				    response carries Content-Disposition: attachment, so the
				    browser downloads without navigating away and the session
				    cookie rides along on the GET. */}
				<div className="sidebar-forms">
					<p className="sidebar-forms-heading">Blank forms</p>

					{BLANK_FORMS.map((form) => (
						<a
							key={form.docType}
							className="sidebar-form"
							href={blankDocumentUrl(form.docType)}
						>
							<span className="sidebar-form-label">
								{form.label}
							</span>

							<span className="sidebar-form-hint">
								{form.hint}
							</span>
						</a>
					))}
				</div>

				{auth.status === "authenticated" && (
					<div className="sidebar-account">
						<span className="sidebar-account-name">
							{auth.user.username}
						</span>

						<button
							type="button"
							className="theme-toggle w-100"
							onClick={() => {
								void auth.logout();
							}}
						>
							Sign out
						</button>
					</div>
				)}
			</aside>
		</>
	);
};

export default Sidebar;
