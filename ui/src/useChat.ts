import { useState } from "react";

const API_URL = "http://localhost:8000";

export function useChat() {
	const [loading, setLoading] = useState(false);

	const sendMessageStream = async (
        message: string, 
        sessionId: string,
        onChunk: (chunk: string) => void
    ) => {
		setLoading(true);

		try {
			const res = await fetch(`${API_URL}/chat/stream`, {
				method: "POST",
				headers: {
					"Content-Type": "application/json",
				},
				body: JSON.stringify({
					message,
					session_id: sessionId,
				}),
			});

            if (!res.body) throw new Error("No response body");

			const reader = res.body.getReader();
            const decoder = new TextDecoder("utf-8");

            while(true) {
                const { done, value } = await reader.read();
                if(done) break;

                const chunk = decoder.decode(value);
                onChunk(chunk);
            }

		} catch (err) {
			console.error(err);
            onChunk("\n[Error receiving response]");
		} finally {
			setLoading(false);
		}
	};

	return { sendMessageStream, loading };
}
