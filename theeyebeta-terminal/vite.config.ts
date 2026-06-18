import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/admin-api": {
        target: "http://127.0.0.1:7200",
        changeOrigin: true,
        cookiePathRewrite: {
          "/admin/auth": "/admin-api/admin/auth"
        },
        rewrite: (path) => path.replace(/^\/admin-api/, "")
      },
      "/admin-ws": {
        target: "ws://127.0.0.1:7200",
        changeOrigin: true,
        ws: true,
        rewrite: (path) => path.replace(/^\/admin-ws/, "")
      },
      "/data-api": {
        target: "http://127.0.0.1:7000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/data-api/, "")
      }
    }
  },
  preview: {
    port: 4173
  }
});
