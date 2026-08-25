import { afterEach, describe, expect, it, vi } from "vitest";

const loadUrlUtils = async (baseUrl = "/") => {
  vi.resetModules();
  vi.stubEnv("BASE_URL", baseUrl);
  return import("./urlUtils.js");
};

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("apiPath", () => {
  it("adds the default API prefix to local paths", async () => {
    const { apiPath } = await loadUrlUtils();

    expect(apiPath()).toBe("/api");
    expect(apiPath(null)).toBe("/api");
    expect(apiPath("classes")).toBe("/api/classes");
    expect(apiPath("/classes")).toBe("/api/classes");
  });

  it("normalizes a configured application base before adding the API prefix", async () => {
    const { API_BASE_PATH, apiPath } = await loadUrlUtils("litblogs///");

    expect(API_BASE_PATH).toBe("/litblogs/api");
    expect(apiPath("/classes")).toBe("/litblogs/api/classes");
  });

  it.each([
    "https://cdn.example.test/classes",
    "//cdn.example.test/classes",
  ])("leaves the external URL %s unchanged", async (externalUrl) => {
    const { apiPath } = await loadUrlUtils();

    expect(apiPath(externalUrl)).toBe(externalUrl);
  });

  it("classifies an external URL after trimming surrounding whitespace", async () => {
    const { apiPath } = await loadUrlUtils();

    expect(apiPath("  https://cdn.example.test/classes  ")).toBe(
      "https://cdn.example.test/classes",
    );
  });
});

describe("mediaPath", () => {
  it("preserves an absent media path", async () => {
    const { mediaPath } = await loadUrlUtils();

    expect(mediaPath()).toBe("");
    expect(mediaPath(null)).toBeNull();
  });

  it.each([
    "https://cdn.example.test/avatar.png",
    "//cdn.example.test/avatar.png",
  ])("leaves the external URL %s unchanged", async (externalUrl) => {
    const { mediaPath } = await loadUrlUtils("/litblogs/");

    expect(mediaPath(externalUrl)).toBe(externalUrl);
  });

  it("does not reinterpret a whitespace-padded external URL as a local upload", async () => {
    const { mediaPath } = await loadUrlUtils("/litblogs/");

    expect(mediaPath("  https://cdn.example.test/avatar.png  ")).toBe(
      "https://cdn.example.test/avatar.png",
    );
  });

  it("normalizes local upload paths at the configured application base", async () => {
    const { mediaPath } = await loadUrlUtils("/litblogs/");

    expect(mediaPath("uploads/images/avatar.png")).toBe(
      "/litblogs/api/uploads/images/avatar.png",
    );
    expect(mediaPath("/api/uploads/images/avatar.png")).toBe(
      "/litblogs/api/uploads/images/avatar.png",
    );
  });
});
