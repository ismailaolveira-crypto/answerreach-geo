import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const pagePath = "apps/web/app/(app)/geo/[workspaceId]/questions/page.tsx";
const clientPath = "apps/web/src/lib/cleanroom-v1-api.ts";
const [page, client] = await Promise.all([
	readFile(pagePath, "utf8"),
	readFile(clientPath, "utf8"),
]);

assert.match(page, /<select name="topic" defaultValue=\{query\.topic \?\? ""\}>/);
assert.match(page, /<option value="">全部主题<\/option>/);
assert.match(page, /library\.topics\.map\(\(topic\) =>/);
assert.match(page, /getQuestionLibrary\(workspaceId, query\)/);
assert.match(client, /topic\?: string;/);
assert.match(client, /params\.set\(key, value\)/);
assert.match(client, /question-library\$\{suffix\}/);

console.log(JSON.stringify({ ok: true, checked: [pagePath, clientPath] }));
