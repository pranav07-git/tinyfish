import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  // changeOrigin: false keeps the browser's Host header, which the API's same-origin check compares against.
  server: { proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } } },
});
