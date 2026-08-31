import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const testDirectory = path.dirname(fileURLToPath(import.meta.url));
const mediaRoot = path.resolve(testDirectory, "..");
const repositoryRoot = path.resolve(testDirectory, "..", "..", "..");

const arrayFields = (source, constantName) => {
  const declaration = source.match(
    new RegExp(`const ${constantName} = \\[([\\s\\S]*?)\\];`),
  );
  assert.ok(declaration, `missing ${constantName} runtime-config contract`);
  return Array.from(declaration[1].matchAll(/"([a-z_]+)"/g), (match) => match[1]);
};

test("keeps the capture runtime-config mock aligned with frontend required fields", () => {
  const frontendSource = fs.readFileSync(
    path.join(repositoryRoot, "litblogs", "src", "config", "runtimeConfig.js"),
    "utf8",
  );
  const captureSource = fs.readFileSync(
    path.join(mediaRoot, "scripts", "capture.mjs"),
    "utf8",
  );
  const payload = captureSource.match(
    /url\.pathname === "\/api\/runtime-config"[\s\S]*?body:\s*JSON\.stringify\(\{([\s\S]*?)\}\),/,
  );
  assert.ok(payload, "missing capture runtime-config mock payload");

  const requiredFields = [
    ...arrayFields(frontendSource, "PUBLIC_STRING_FIELDS"),
    ...arrayFields(frontendSource, "PUBLIC_BOOLEAN_FIELDS"),
  ].sort();
  const captureFields = Array.from(
    payload[1].matchAll(/^\s*([a-z_]+):/gm),
    (match) => match[1],
  ).sort();

  assert.deepEqual(captureFields, requiredFields);
  assert.match(payload[1], /^\s*google_oauth_enabled:\s*false,/m);
  assert.match(payload[1], /^\s*microsoft_oauth_enabled:\s*false,/m);
});
