import { useState } from "react";
import { useParams } from "react-router-dom";

import Chat from "../components/Chat";
import Navbar from "../components/Navbar";
import Sidebar from "../components/Sidebar";
import { useChat } from "../hooks/useChat";
import { useConversationStream } from "../hooks/useConversationStream";
import { useMessages } from "../hooks/useMessages";

const ChatPage = () => {
	const [sidebarOpen, setSidebarOpen] = useState(true);

	// The conversation lives in the URL so a refresh, a bookmark and a
	// second tab all resolve to the same conversation. Without it, "two
	// tabs on one conversation" — the reason the event stream exists —
	// could not even be expressed.
	const { conversationId } = useParams<{ conversationId: string }>();

	// All three are keyed by the same id, so they always describe the same
	// conversation. Wiring them here rather than inside Chat keeps that
	// invariant visible in one place.
	const messagesQuery = useMessages(conversationId);
	const stream = useConversationStream(conversationId);
	const chat = useChat(conversationId);

	return (
		<>
			<Navbar />

			<main className="chat-layout">
				<Sidebar
					isOpen={sidebarOpen}
					onClose={() => setSidebarOpen(false)}
				/>

				<Chat
					conversationId={conversationId}
					messages={messagesQuery.data ?? []}
					// A disabled query stays "pending" forever, so the flag
					// is only meaningful once a conversation is selected.
					isLoading={
						Boolean(conversationId) && messagesQuery.isPending
					}
					loadError={messagesQuery.error}
					stream={stream}
					chat={chat}
					onToggleSidebar={() =>
						setSidebarOpen((previous) => !previous)
					}
				/>
			</main>
		</>
	);
};

export default ChatPage;
