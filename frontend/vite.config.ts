import path from "node:path"
import { fileURLToPath } from "node:url"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

const currentDir = path.dirname(fileURLToPath(import.meta.url))

// 开发模式下前端 dev server 需要把 API 请求转发到后端。
// 默认对齐后端默认端口，可用 VIDEODOC_DEV_API 覆盖。
const apiTarget = process.env.VIDEODOC_DEV_API ?? "http://127.0.0.1:8765"

export default defineConfig({
  base: "/app/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(currentDir, "./src"),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": apiTarget,
      "/tasks": apiTarget,
      "/assets": apiTarget,
      "/sample": apiTarget,
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
})
