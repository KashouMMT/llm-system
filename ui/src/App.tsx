import { Route, Routes } from "react-router-dom";

import ChatPage from "./layout/ChatPage";
import NotFoundPage from "./layout/NotFoundPage";
import SettingPage from "./layout/SettingPage";

const App = () => {
	return (
		<Routes>
			<Route path="/" element={<ChatPage />} />
			<Route path="/c/:conversationId" element={<ChatPage />} />
			<Route path="/setting" element={<SettingPage />} />
			<Route path="*" element={<NotFoundPage />} />
		</Routes>
	);
};

export default App;
