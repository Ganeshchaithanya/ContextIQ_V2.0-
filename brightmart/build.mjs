import { copyFile, mkdir, writeFile } from "node:fs/promises";

const backend = new URL(process.env.RENDER_APP_URL ?? "");
if (
  backend.protocol !== "https:" ||
  backend.pathname !== "/" ||
  backend.search ||
  backend.hash ||
  backend.username ||
  backend.password
) {
  throw new Error("RENDER_APP_URL must be the HTTPS origin of ContextIQ on Render.");
}

const root = new URL("./", import.meta.url);
const output = new URL("dist/", root);
const assets = new URL("assets/", output);
await mkdir(assets, { recursive: true });
await copyFile(new URL("index.html", root), new URL("index.html", output));
for (const name of ["store.css", "store.js"]) {
  await copyFile(new URL(name, root), new URL(name, assets));
}
await writeFile(
  new URL("config.js", assets),
  `window.BRIGHTMART_API = ${JSON.stringify(backend.origin + "/shop")};\n`,
);
