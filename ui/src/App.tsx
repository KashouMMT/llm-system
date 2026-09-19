import { Route, Routes } from "react-router-dom";

import ChatPage from "./layout/ChatPage";
import NotFoundPage from "./layout/NotFoundPage";
import SettingsPage from "./layout/SettingsPage";

const App = () => {
	return (
		<Routes>
			<Route path="/" element={<ChatPage />} />
			<Route path="/c/:conversationId" element={<ChatPage />} />
			{/* Bare /settings redirects to the first section the user may see. */}
			<Route path="/settings" element={<SettingsPage />} />
			<Route
				path="/settings/:category/:sectionId"
				element={<SettingsPage />}
			/>
			<Route path="*" element={<NotFoundPage />} />
		</Routes>
	);
};

export default App;
