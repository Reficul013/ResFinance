import { defineConfig } from "vite";

const root = new URL(".", import.meta.url).pathname;

export default defineConfig({
  build: {
    emptyOutDir: true,
    outDir: "dist",
    rollupOptions: {
      input: {
        approval: `${root}approval.html`,
        background: `${root}src/background.ts`,
        content: `${root}src/content.ts`,
        popup: `${root}popup.html`,
      },
      output: {
        entryFileNames: "[name].js",
      },
    },
  },
});
