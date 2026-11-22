import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";

const source = new URL("app/static/", import.meta.url);
const output = new URL("contextiq-dist/", import.meta.url);
const outputAssets = new URL("static/", output);
const page = new URL("v2.html", source);
const html = await readFile(page, "utf8");
const assets = new Set(
  Array.from(html.matchAll(/(?:href|src)="\/static\/([\w.-]+)"/g), ([, filename]) => filename),
);
assets.add("upi.svg");

await mkdir(outputAssets, { recursive: true });
const scripts = [...html.matchAll(/<script src="\/static\/([\w.-]+)" defer><\/script>/g)];
const bundle = (await Promise.all(scripts.map(async ([, name]) => `/* ${name} */\n${await readFile(new URL(name, source), "utf8")}\n;`))).join("\n");
const hash = createHash("sha256").update(bundle).digest("hex").slice(0, 12);
const filename = `contextiq-${hash}.js`;
await writeFile(new URL(filename, outputAssets), bundle);
let first = true;
const builtHtml = html.replace(/<script src="\/static\/[\w.-]+" defer><\/script>/g, () => {
  if (!first) return "";
  first = false;
  return `<script src="/static/${filename}" defer></script>`;
});
await writeFile(new URL("index.html", output), builtHtml);
await Promise.all(
  [...assets].map((name) => copyFile(new URL(name, source), new URL(name, outputAssets))),
);
