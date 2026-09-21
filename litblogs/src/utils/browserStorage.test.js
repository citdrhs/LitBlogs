import axios from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe.each(["/", "/dren/"])("browser state at %s", (base) => {
  const prefix = base === "/" ? "" : "litblogs:/dren:";
  const load = async () => {
    vi.resetModules();
    vi.stubEnv("BASE_URL", base);
    return import("./auth.js");
  };

  it("stores session metadata and preferences within the app namespace", async () => {
    const auth = await load();
    const settings = await import("./userSettings.js");
    auth.persistSessionMetadata({ user_id: 42, username: "student" });
    settings.saveLocalUserSettings({ darkMode: true });
    expect(JSON.parse(sessionStorage.getItem(`${prefix}user_info`))).toMatchObject({ userId: 42 });
    expect(auth.getStoredSessionMetadata()).toMatchObject({ userId: 42 });
    expect(JSON.parse(localStorage.getItem(`${prefix}litblogs_settings`))).toMatchObject({ darkMode: true });
    expect(settings.getLocalUserSettings().darkMode).toBe(true);
  });

  it("only purges owned auth and draft keys", async () => {
    const auth = await load();
    const keys = ["token", "user_info", "class_info", "postDraft:1:2:new", "assignmentDraft:1:2:3"];
    for (const storage of [localStorage, sessionStorage]) {
      for (const key of keys) {
        storage.setItem(`${prefix}${key}`, "app-private-data");
        if (prefix) storage.setItem(key, "sibling-data");
      }
      storage.setItem("sibling:token", "sibling-data");
    }
    auth.purgeLegacyPersistentAuth();
    auth.clearStoredAuth();
    for (const storage of [localStorage, sessionStorage]) {
      for (const key of keys) {
        expect(storage.getItem(`${prefix}${key}`)).toBeNull();
        if (prefix) expect(storage.getItem(key)).toBe("sibling-data");
      }
      expect(storage.getItem("sibling:token")).toBe("sibling-data");
    }
  });

  it("uses the runtime-selected CSRF cookie only for this app's API", async () => {
    const auth = await load();
    const name = prefix ? "__Secure-litblogs-csrf" : "__Host-litblogs-csrf";
    vi.spyOn(document, "cookie", "get").mockReturnValue(
      "sibling-csrf=sibling; __Secure-litblogs-csrf=subpath-token; __Host-litblogs-csrf=root-token",
    );
    const client = axios.create({ adapter: async (config) => ({ config, status: 200, data: {}, headers: {} }) });
    const apiBasePath = `${base === "/" ? "" : "/dren"}/api`;
    auth.configureAuthHttpClient(client, { apiBasePath, csrfCookieName: name });
    const own = await client.post("/auth/logout");
    expect(own.config.headers.get("X-CSRF-Token")).toBe(prefix ? "subpath-token" : "root-token");
    const sibling = await client.post(`${window.location.origin}/other/api/logout`);
    expect(sibling.config.headers.has("X-CSRF-Token")).toBe(false);
    expect(sibling.config.withCredentials).toBe(false);
  });
});
