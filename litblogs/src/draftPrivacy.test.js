// @vitest-environment node

import { readFileSync, readdirSync } from "node:fs";
import { extname, join } from "node:path";
import { describe, expect, it } from "vitest";

const projectRoot = globalThis.process.cwd();
const sourceRoot = join(projectRoot, "src");

const readProjectFile = (relativePath) => (
  readFileSync(join(projectRoot, relativePath), "utf8")
);

const collectRuntimeFiles = (directory) => readdirSync(directory, { withFileTypes: true })
  .flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "test" ? [] : collectRuntimeFiles(path);
    }

    const isRuntimeSource = [".js", ".jsx"].includes(extname(entry.name));
    return isRuntimeSource && !entry.name.includes(".test.") ? [path] : [];
  });

describe("private browser draft policy", () => {
  it("has no runtime writer for legacy assignment or post draft storage keys", () => {
    for (const file of collectRuntimeFiles(sourceRoot)) {
      const source = readFileSync(file, "utf8");
      const storageWrites = source.match(
        /(?:localStorage|sessionStorage)\.setItem\([\s\S]{0,300}?\)/g,
      ) || [];

      for (const write of storageWrites) {
        expect(write).not.toMatch(/assignmentDraft:|postDraft:/);
      }
    }

    const classFeedSource = readProjectFile("src/ClassFeed.jsx");
    expect(classFeedSource).not.toContain("assignmentDraft:");
    expect(classFeedSource).not.toContain("postDraft:");

    const classFeedStorageWrites = classFeedSource.match(
      /(?:localStorage|sessionStorage)\.setItem\([^;]*\);?/g,
    ) || [];
    expect(classFeedStorageWrites).toEqual([
      "localStorage.setItem('darkMode', JSON.stringify(darkMode));",
      "localStorage.setItem(reminderKey, new Date().toISOString());",
    ]);
    expect(classFeedSource).not.toMatch(/indexedDB|CacheStorage|\bcaches\.|createObjectURL|pushState|replaceState/);
  });

  it("keeps the draft implementation free of durable browser stores and URL history", () => {
    const draftSource = readProjectFile("src/utils/privateDrafts.js");

    for (const forbiddenApi of [
      /localStorage/,
      /sessionStorage/,
      /indexedDB/,
      /CacheStorage/,
      /\bcaches\b/,
      /createObjectURL/,
      /revokeObjectURL/,
      /pushState/,
      /replaceState/,
      /\blocation\b/,
      /\bconsole\b/,
    ]) {
      expect(draftSource).not.toMatch(forbiddenApi);
    }
  });

  it("wires assignment recovery to the server and labels post drafts as tab-only", () => {
    const classFeedSource = readProjectFile("src/ClassFeed.jsx");
    const settingsSource = readProjectFile("src/Settings.jsx");

    expect(classFeedSource).toContain("loadAssignmentDraft(axios");
    expect(classFeedSource).toMatch(/saveAssignmentDraft\(\s*axios,/);
    expect(classFeedSource).toContain("Saved to your account");
    expect(classFeedSource).toContain("Kept only in this tab");
    expect(settingsSource).toContain("Assignment drafts are saved securely to your account");
    expect(settingsSource).toContain("post drafts stay only in the current tab");
  });

  it("does not log private draft, media, file, or upload metadata from ClassFeed", () => {
    const classFeedSource = readProjectFile("src/ClassFeed.jsx");
    const loggingCalls = classFeedSource.match(
      /console\.(?:log|debug|info|warn|error)\([^;]*\);?/g,
    ) || [];

    for (const call of loggingCalls) {
      expect(call).not.toMatch(/draft|content|media|file|upload|video|response\.data|url/i);
    }
  });
});
