import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Этап 0: сборка отдаётся тем же FastAPI-процессом (app/web/main.py,
// StaticFiles), без CORS — один origin, dev-прокси на /api не нужен.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
});
