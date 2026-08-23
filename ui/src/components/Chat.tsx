import { type FormEvent, useState } from "react";
import "../assets/css/chat.css";

type ChatProps = {
	onToggleSidebar: () => void;
};

type Message = {
	id: number;
	role: "user" | "ai";
	content: string;
};

const Chat = ({ onToggleSidebar }: ChatProps) => {
	const [input, setInput] = useState("");

	const [messages, setMessages] = useState<Message[]>([
		{
			id: 1,
			role: "ai",
			content: "Hello! How can I help you today?",
		},
		{
			id: 2,
			role: "user",
			content: "Hey! I'm testing this chat interface.",
		},
		{
			id: 3,
			role: "ai",
			content:
				"Nice! The message area is scrollable, so you can have as many messages as you want.",
		},
	]);

	const handleSubmit = (event: FormEvent) => {
		event.preventDefault();

		const content = input.trim();

		if (!content) {
			return;
		}

		const message: Message = {
			id: Date.now(),
			role: "user",
			content,
		};

		setMessages((previousMessages) => [...previousMessages, message]);

		setInput("");
	};

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

						<small className="text-secondary">Online</small>
					</div>
				</div>

				<div className="chat-messages">
					{messages.map((message) => (
						<div
							key={message.id}
							className={
								message.role === "user"
									? "message message-user"
									: "message message-ai"
							}
						>
							<div className="message-content">
								{message.content}
							</div>
						</div>
					))}
				</div>

				<form className="chat-input" onSubmit={handleSubmit}>
					<input
						type="text"
						className="form-control"
						placeholder="Type a message..."
						value={input}
						onChange={(event) => setInput(event.target.value)}
					/>

					<button type="submit" className="btn btn-primary">
						Send
					</button>
				</form>
			</div>
		</section>
	);
};

export default Chat;
