import { Route, Routes } from "react-router-dom"
import ChatPage from "./layout/ChatPage";
import SettingPage from "./layout/SettingPage";

const App = () => {
	return <Routes>
		<Route path="/" element={<ChatPage />} />
		<Route path	="/setting" element={<SettingPage />} />
	</Routes>	
}

export default App;