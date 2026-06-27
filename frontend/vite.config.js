import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During dev the Vite server runs on :5173 and the FastAPI backend on :8000.
// We proxy all /api requests to the backend so the frontend code can just call
// "/api/..." with no CORS fuss.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
