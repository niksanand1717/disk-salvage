import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  base: "./",                       // loaded from file:// by Electron
  build: { outDir: "dist", emptyOutDir: true },
  test: { include: ["electron/**/*.test.ts", "src/**/*.test.ts"] },
});
