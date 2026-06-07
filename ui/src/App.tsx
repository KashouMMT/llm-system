import { useRef, useEffect, useState } from "react";
import { useChat } from "./useChat";

import styles from "./assets/style.module.css";

type Message = {
	id: number;
	text: string;
	sender: "user" | "bot";
};

function App() {
	const bottomRef = useRef<HTMLDivElement | null>(null);

	const [messages, setMessages] = useState<Message[]>([
		{
			id: 1,
			text: "Hello! How can I assist you today?",
			sender: "bot",
		},
	]);

	const [input, setInput] = useState("");
	const [sessionId] = useState(() => crypto.randomUUID());

	const { sendMessageStream, loading } = useChat();

	const sendMessage = async () => {
		if (!input.trim()) return;

		const userText = input;

		const userMessage: Message = {
			id: Date.now(),
			text: userText,
			sender: "user",
		};

		const botMessageId = Date.now() + 1;

		setMessages((prev) => [
			...prev,
			userMessage,
			{ id: botMessageId, text: "", sender: "bot" },
		]);

		setInput("");

		await sendMessageStream(userText, sessionId, (chunk) => {
			setMessages((prev) =>
				prev.map((msg) =>
					msg.id === botMessageId
						? { ...msg, text: msg.text + chunk }
						: msg,
				),
			);
		});
	};

	useEffect(() => {
		bottomRef.current?.scrollIntoView({ behavior: "smooth" });
	}, [messages]);

	return (
		<div className={`${styles["chat-container"]}`}>
			<div className={`${styles["chat-window"]}`}>
				{messages.map((msg) =>  {
                    const showBookButton = msg.sender === "bot" && msg.text.includes("/book_now");

                    const cleanText = msg.text.replace("/book_now","").trim();

                    return (
					<div
						key={msg.id}
						className={`${styles.message} ${
							msg.sender === "user" ? styles.user : styles.bot
						}`}
					>
						{cleanText || "…"}
                        {showBookButton && (
                            <button className={styles.bookButton}
                            onClick={() => alert("Booking flow goes here")}>
                                Book a room now
                            </button>
                        )}
					</div>
				)})}
                <div ref={bottomRef} />
			</div>
			<div className={`${styles["input-area"]}`}>
				<input
					value={input}
					onChange={(e) => setInput(e.target.value)}
					placeholder="Send a message"
					onKeyDown={(e) => e.key === "Enter" && sendMessage()}
				/>
				<button onClick={sendMessage} disabled={loading}>
					↑
				</button>
			</div>
		</div>
	);
}

export default App;
