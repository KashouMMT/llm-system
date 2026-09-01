import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// https://vite.dev/config/
export default defineConfig({
	plugins: [react()],
	// CORS on the API allows exactly http://localhost:5173, so drifting to
	// another port must be a hard failure rather than a silent one.
	server: {
		port: 5173,
		strictPort: true,
	},
});
