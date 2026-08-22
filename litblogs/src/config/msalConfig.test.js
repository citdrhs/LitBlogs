import { describe, expect, it } from "vitest";

import { msalConfig } from "./msalConfig.js";

describe("Microsoft browser token cache", () => {
  it("keeps provider credentials in memory instead of browser storage", () => {
    expect(msalConfig.cache.cacheLocation).toBe("memoryStorage");
    expect(msalConfig.cache.storeAuthStateInCookie).toBe(false);
  });
});
