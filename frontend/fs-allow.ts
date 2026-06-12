import { fileURLToPath, URL } from "node:url";

/** Vite dev server 跨 root 白名单单源 — vite.config.ts 与 .storybook/main.ts 共用。
 *  tokens 单源在仓库根 static/css/（spec §7），两个 Vite 实例都要放行。 */
export const frontendRoot = fileURLToPath(new URL(".", import.meta.url));
export const tokensDir = fileURLToPath(new URL("../static/css", import.meta.url));
export const fsAllow = [frontendRoot, tokensDir];
