import { useState } from "react";

import Chat from "../components/Chat";
import Navbar from "../components/Navbar";
import Sidebar from "../components/Sidebar";

const ChatPage = () => {
	const [sidebarOpen, setSidebarOpen] = useState(true);

	return (
		<>
			<Navbar />

			<main className="chat-layout">
				<Sidebar
					isOpen={sidebarOpen}
					onClose={() => setSidebarOpen(false)}
				/>
				<Chat
					onToggleSidebar={() =>
						setSidebarOpen((previous) => !previous)
					}
				/>
			</main>
		</>
	);
};

export default ChatPage;
