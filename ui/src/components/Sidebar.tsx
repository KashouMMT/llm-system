import { NavLink, useNavigate } from "react-router-dom";

import "../assets/css/sidebar.css";
import { blankDocumentUrl } from "../api/client";
import {
	useConversations,
	useCreateConversation,
} from "../hooks/useConversations";

type SidebarProps = {
	isOpen: boolean;
	onClose: () => void;
};

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

	const conversationsQuery = useConversations();
	const createConversation = useCreateConversation();

	const handleCreate = () => {
		createConversation.mutate(undefined, {
			onSuccess: (conversation) => {
				navigate(`/c/${conversation.id}`);
				onClose();
			},
		});
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
					    stream working. */}
					{conversationsQuery.data?.map((conversation) => (
						<NavLink
							key={conversation.id}
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
					))}
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
			</aside>
		</>
	);
};

export default Sidebar;
