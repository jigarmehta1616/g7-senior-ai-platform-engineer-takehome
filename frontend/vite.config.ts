import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// Strict CSP for the production bundle only: the dev server injects styles for HMR,
// which a `style-src 'self'` policy would block.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "connect-src 'self' http://127.0.0.1:8081 http://localhost:8081",
  "base-uri 'none'",
  "form-action 'self'",
].join("; ");

function contentSecurityPolicy(): Plugin {
  return {
    name: "content-security-policy",
    apply: "build",
    transformIndexHtml: () => [
      { tag: "meta", attrs: { "http-equiv": "Content-Security-Policy", content: CSP }, injectTo: "head-prepend" },
    ],
  };
}

const api = "http://127.0.0.1:8080";

export default defineConfig({
  base: "/console/",
  plugins: [react(), tailwindcss(), contentSecurityPolicy()],
  build: { outDir: "dist", emptyOutDir: true, sourcemap: false },
  server: {
    port: 5173,
    proxy: { "/v1": api, "/dev": api, "/readyz": api },
  },
});
