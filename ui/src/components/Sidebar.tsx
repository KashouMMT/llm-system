import "../assets/css/sidebar.css";

type SidebarProps = {
	isOpen: boolean;
	onClose: () => void;
};

const Sidebar = ({ isOpen, onClose }: SidebarProps) => {
	const conversations = [
		"How does LangGraph work?",
		"React Router setup",
		"Building an AI Agent",
		"PostgreSQL memory design",
		"Ollama model comparison",
		"FastAPI streaming",
		"RAG architecture discussion",
		"Vector database options",
		"LangChain vs LangGraph",
		"AI Agent Platform idea",
		"React component architecture",
		"Bootstrap navbar problem",
		"Python async programming",
		"LLM context windows",
		"Prompt engineering",
		"Local AI development",
		"Docker deployment",
		"Nginx configuration",
		"PostgreSQL optimization",
		"Authentication design",
		"Spring Boot architecture",
		"TypeScript patterns",
		"Frontend state management",
		"AI memory implementation",
	];

	return (
		<>
			<div
				className={`sidebar-backdrop ${isOpen ? "show" : ""}`}
				onClick={onClose}
			/>

			<aside className={`sidebar ${isOpen ? "open" : ""}`}>
				<div className="sidebar-header">
					<button className="btn btn-primary w-100">
						+ New chat
					</button>
				</div>

				<div className="sidebar-conversations">
					{conversations.map((conversation, index) => (
						<button
							key={index}
							className="sidebar-conversation"
							onClick={onClose}
						>
							<span className="conversation-title">
								{conversation}
							</span>
						</button>
					))}
				</div>
			</aside>
		</>
	);
};

export default Sidebar;
