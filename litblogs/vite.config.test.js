// @vitest-environment node

import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveConfig } from "vite";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));
const configFile = path.join(projectRoot, "vite.config.js");

const resolveBasePaths = async (configuredBase) => {
  const previousBase = process.env.VITE_APP_BASE_PATH;
  process.env.VITE_APP_BASE_PATH = configuredBase;

  let viteConfig;
  try {
    viteConfig = await resolveConfig(
      { configFile, root: projectRoot, mode: "test" },
      "serve",
    );
  } finally {
    if (previousBase === undefined) {
      delete process.env.VITE_APP_BASE_PATH;
    } else {
      process.env.VITE_APP_BASE_PATH = previousBase;
    }
  }

  vi.resetModules();
  vi.stubEnv("BASE_URL", viteConfig.base);
  const { APP_BASE_PATH } = await import("./src/utils/urlUtils.js");

  return { runtimeBase: APP_BASE_PATH, viteBase: viteConfig.base };
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe.sequential("application base path configuration", () => {
  it.each([
    ["root", "/", "/", ""],
    ["missing leading slash", "litblogs", "/litblogs/", "/litblogs"],
    ["repeated leading and trailing slashes", "///school/litblogs///", "/school/litblogs/", "/school/litblogs"],
    ["repeated trailing slashes", "/litblogs///", "/litblogs/", "/litblogs"],
  ])("keeps the resolved Vite and runtime bases aligned for %s", async (_name, configuredBase, expectedViteBase, expectedRuntimeBase) => {
    const { runtimeBase, viteBase } = await resolveBasePaths(configuredBase);

    expect(viteBase).toBe(expectedViteBase);
    expect(runtimeBase).toBe(expectedRuntimeBase);
    expect(viteBase === "/" ? "" : viteBase.slice(0, -1)).toBe(runtimeBase);
  });
});
