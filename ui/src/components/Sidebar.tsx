import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";

import "../assets/css/sidebar.css";
import { useAuth } from "../auth/AuthContext";
import {
	useConversations,
	useCreateConversation,
	useRenameConversation,
} from "../hooks/useConversations";
import { usePlugins } from "../hooks/usePlugins";

type SidebarProps = {
	isOpen: boolean;
	onClose: () => void;
};

// Matches Field(max_length=TITLE_MAX_CHARS) on PATCH /conversations; the
// server rejects anything longer with 422, this just stops the user
// getting there.
const TITLE_MAX_CHARS = 80;

const Sidebar = ({ isOpen, onClose }: SidebarProps) => {
	const { t } = useTranslation();
	const navigate = useNavigate();
	const auth = useAuth();
	const { plugins } = usePlugins();

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
							? t("sidebar.creating")
							: t("sidebar.newChat")}
					</button>
				</div>

				<div className="sidebar-conversations">
					{conversationsQuery.isPending && (
						<p className="small text-secondary px-2">
							{t("sidebar.loading")}
						</p>
					)}

					{conversationsQuery.isError && (
						<p className="small text-danger px-2">
							{t("sidebar.loadError")}
						</p>
					)}

					{conversationsQuery.data?.length === 0 && (
						<p className="small text-secondary px-2">
							{t("sidebar.empty")}
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
									aria-label={t("sidebar.renameAria")}
									title={t("sidebar.rename")}
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

				{/* The chat-sidebar slot: whatever loaded plugins put here
				    (the recruitment plugin's blank forms, for one). */}
				{plugins.map(({ name, chatSidebar: Slot }) =>
					Slot ? <Slot key={name} /> : null,
				)}

				{auth.status === "authenticated" && (
					<div className="sidebar-account">
						<span className="sidebar-account-name">
							{auth.user.email}
						</span>

						<button
							type="button"
							className="theme-toggle w-100"
							onClick={() => {
								void auth.logout();
							}}
						>
							{t("sidebar.signOut")}
						</button>
					</div>
				)}
			</aside>
		</>
	);
};

export default Sidebar;
