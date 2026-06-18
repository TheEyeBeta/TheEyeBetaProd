import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

const source = resolve("../docs/frontend/openapi.json");
const target = resolve("src/api/openapi-schema.ts");
const raw = await readFile(source, "utf8");
const schema = JSON.parse(raw);
const paths = Object.keys(schema.paths ?? {}).sort();

const generated = `// Generated from ../docs/frontend/openapi.json. Do not edit by hand.
export const OPENAPI_VERSION = ${JSON.stringify(schema.openapi ?? "")};
export const OPENAPI_TITLE = ${JSON.stringify(schema.info?.title ?? "")};
export const OPENAPI_PATHS = ${JSON.stringify(paths, null, 2)} as const;
export type OpenApiPath = (typeof OPENAPI_PATHS)[number];
`;

await writeFile(target, generated);
console.log(`Generated ${target} from ${source}`);
