import preact from "@preact/preset-vite";
import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const backend = env.SARATHI_UI_BACKEND || "http://127.0.0.1:8765";

  return {
    base: "/ui/",
    plugins: [preact()],
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: backend,
          changeOrigin: false,
        },
      },
    },
    build: {
      outDir: "dist",
      emptyOutDir: true,
      sourcemap: false,
      rollupOptions: {
        output: {
          entryFileNames: "app.js",
          assetFileNames: (assetInfo) => assetInfo.names?.some((name) => name.endsWith(".css")) ? "app.css" : "[name][extname]",
        },
      },
    },
  };
});
