import { copyFile, mkdir, readFile } from "node:fs/promises";

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
await copyFile(page, new URL("index.html", output));
await Promise.all(
  [...assets].map((name) => copyFile(new URL(name, source), new URL(name, outputAssets))),
);
