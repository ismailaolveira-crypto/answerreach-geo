import { readdir, readFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve("apps/web");
const targets = [
  path.join(root, "app", "(app)", "geo"),
  path.join(root, "src", "lib", "cleanroom-v1-api.ts"),
];

async function filesAt(target) {
  const entries = await readdir(target, { withFileTypes: true }).catch(() => []);
  if (!entries.length && target.endsWith(".ts")) return [target];
  return (await Promise.all(entries.map(async (entry) => {
    const entryPath = path.join(target, entry.name);
    return entry.isDirectory() ? filesAt(entryPath) : [entryPath];
  }))).flat();
}

const files = (await Promise.all(targets.map(filesAt))).flat();
const violations = [];
for (const file of files) {
  const source = await readFile(file, "utf8");
  if (source.includes('from "@/lib/api"') || source.includes("from '@/lib/api'")) {
    violations.push(`${file}: imports legacy API client`);
  }
}
const cleanClient = await readFile(path.join(root, "src", "lib", "cleanroom-v1-api.ts"), "utf8");
if (!cleanClient.includes("/api/v1")) violations.push("cleanroom-v1-api.ts: missing dedicated /api/v1 contract");
if (violations.length) throw new Error(`Clean-room frontend boundary failed:\n${violations.join("\n")}`);
console.log(JSON.stringify({ ok: true, checked_files: files.map((file) => path.relative(process.cwd(), file)) }));
