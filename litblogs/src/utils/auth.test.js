import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import axios from "axios";
import { afterEach, describe, expect, it } from "vitest";

import * as auth from "./auth.js";

const SOURCE_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const sourceFiles = (directory) => fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
  const candidate = path.join(directory, entry.name);
  if (entry.isDirectory()) {
    return sourceFiles(candidate);
  }
  if (!/\.[jt]sx?$/.test(entry.name) || /\.(?:test|spec)\.[jt]sx?$/.test(entry.name)) {
    return [];
  }
  return [candidate];
});

const setCsrfCookie = (value = "synthetic csrf token") => {
  document.cookie = `litblog-csrf=${encodeURIComponent(value)}; path=/`;
};

const clearBrowserState = () => {
  localStorage.clear();
  sessionStorage.clear();
  document.cookie = "litblog-csrf=; Max-Age=0; path=/";
};

const responseAdapter = async (config) => ({
  config,
  data: {},
  headers: {},
  status: 200,
  statusText: "OK",
});

afterEach(() => {
  clearBrowserState();
});

describe("browser session metadata", () => {
  it("stores only allowlisted non-secret UI metadata in sessionStorage", () => {
    expect(typeof auth.persistSessionMetadata).toBe("function");
    if (typeof auth.persistSessionMetadata !== "function") return;

    const stored = auth.persistSessionMetadata({
      user_id: 42,
      username: "synthetic-student",
      first_name: "Synthetic",
      last_name: "Student",
      role: "STUDENT",
      is_admin: false,
      token: "header.payload.signature",
      access_token: "another.header.payload",
      password: "must-not-persist",
    });

    expect(stored).toEqual({
      userId: 42,
      username: "synthetic-student",
      firstName: "Synthetic",
      first_name: "Synthetic",
      lastName: "Student",
      last_name: "Student",
      role: "STUDENT",
      is_admin: false,
    });
    expect(JSON.parse(sessionStorage.getItem("user_info"))).toEqual(stored);
    expect(localStorage.getItem("token")).toBeNull();
    expect(sessionStorage.getItem("token")).toBeNull();
    expect(JSON.stringify(sessionStorage)).not.toContain("header.payload");
    expect(JSON.stringify(sessionStorage)).not.toContain("must-not-persist");
  });

  it("clears legacy auth and draft state from both storage scopes", () => {
    localStorage.setItem("token", "legacy.jwt.value");
    localStorage.setItem("user_info", "legacy-user");
    localStorage.setItem("class_info", "legacy-class");
    localStorage.setItem("assignmentDraft:1:2:3", "private assignment draft");
    localStorage.setItem("postDraft:1:2:new", "private post draft");
    localStorage.setItem("darkMode", "true");
    sessionStorage.setItem("token", "legacy-session-token");
    sessionStorage.setItem("user_info", "session-user");
    sessionStorage.setItem("class_info", "session-class");
    sessionStorage.setItem("postDraft:1:2:new", "session draft");

    auth.clearStoredAuth();

    expect(localStorage.getItem("token")).toBeNull();
    expect(localStorage.getItem("user_info")).toBeNull();
    expect(localStorage.getItem("class_info")).toBeNull();
    expect(localStorage.getItem("assignmentDraft:1:2:3")).toBeNull();
    expect(localStorage.getItem("postDraft:1:2:new")).toBeNull();
    expect(sessionStorage.length).toBe(0);
    expect(localStorage.getItem("darkMode")).toBe("true");
  });

  it("purges historical drafts from both storage scopes during app startup", () => {
    localStorage.setItem("assignmentDraft:1:2:3", "private assignment draft");
    sessionStorage.setItem("postDraft:1:2:new", "private post draft");
    sessionStorage.setItem("user_info", "active-session-user");

    auth.purgeLegacyPersistentAuth();

    expect(localStorage.getItem("assignmentDraft:1:2:3")).toBeNull();
    expect(sessionStorage.getItem("postDraft:1:2:new")).toBeNull();
    expect(sessionStorage.getItem("user_info")).toBe("active-session-user");
  });
});

describe("Axios cookie and CSRF policy", () => {
  it("loads safe session metadata from the server without reading a JWT", async () => {
    expect(typeof auth.fetchBrowserSession).toBe("function");
    if (typeof auth.fetchBrowserSession !== "function") return;

    const client = axios.create({
      adapter: async (config) => ({
        config,
        data: {
          user_id: 42,
          username: "synthetic-student",
          first_name: "Synthetic",
          last_name: "Student",
          role: "STUDENT",
          is_admin: false,
        },
        headers: {},
        status: 200,
        statusText: "OK",
      }),
    });

    const metadata = await auth.fetchBrowserSession(client);

    expect(metadata.userId).toBe(42);
    expect(JSON.parse(sessionStorage.getItem("user_info"))).toEqual(metadata);
  });

  it("sends credentials and CSRF for an unsafe same-origin API request", async () => {
    expect(typeof auth.configureAuthHttpClient).toBe("function");
    if (typeof auth.configureAuthHttpClient !== "function") return;

    const client = axios.create({ adapter: responseAdapter });
    auth.configureAuthHttpClient(client, {
      apiBasePath: "/api",
      csrfCookieName: "litblog-csrf",
    });
    setCsrfCookie();

    const response = await client.post("/classes", { name: "Synthetic Class" });

    expect(client.defaults.withCredentials).toBe(false);
    expect(response.config.withCredentials).toBe(true);
    expect(response.config.headers.get("X-CSRF-Token")).toBe("synthetic csrf token");
    expect(response.config.headers.get("Authorization")).toBeUndefined();
  });

  it.each([
    ["a safe API request", "get", "/classes", true],
    [
      "a same-origin non-API request",
      "post",
      new URL("/account", window.location.origin).href,
      false,
    ],
    [
      "a cross-origin API request",
      "post",
      "https://outside.example.test/api/classes",
      false,
    ],
  ])("never leaks browser credentials or CSRF to %s", async (
    _description,
    method,
    url,
    expectedWithCredentials,
  ) => {
    expect(typeof auth.configureAuthHttpClient).toBe("function");
    if (typeof auth.configureAuthHttpClient !== "function") return;

    const client = axios.create({ adapter: responseAdapter });
    auth.configureAuthHttpClient(client, {
      apiBasePath: "/api",
      csrfCookieName: "litblog-csrf",
    });
    setCsrfCookie();

    const response = await client.request({ method, url });

    expect(response.config.headers.get("X-CSRF-Token")).toBeUndefined();
    expect(response.config.withCredentials).toBe(expectedWithCredentials);
  });

  it("calls the CSRF-protected logout endpoint before clearing browser state", async () => {
    expect(typeof auth.configureAuthHttpClient).toBe("function");
    expect(typeof auth.logoutBrowserSession).toBe("function");
    if (
      typeof auth.configureAuthHttpClient !== "function" ||
      typeof auth.logoutBrowserSession !== "function"
    ) return;

    const client = axios.create({
      adapter: async (config) => ({
        ...(await responseAdapter(config)),
        status: 204,
        statusText: "No Content",
      }),
    });
    auth.configureAuthHttpClient(client, {
      apiBasePath: "/api",
      csrfCookieName: "litblog-csrf",
    });
    setCsrfCookie();
    sessionStorage.setItem("user_info", "session-user");

    const response = await auth.logoutBrowserSession(client);

    expect(response.config.method).toBe("post");
    expect(response.config.url).toBe("/auth/logout");
    expect(response.config.headers.get("X-CSRF-Token")).toBe("synthetic csrf token");
    expect(sessionStorage.getItem("user_info")).toBeNull();
  });

  it("keeps session metadata but purges legacy private drafts when logout is not confirmed", async () => {
    const client = axios.create({
      adapter: async (config) => {
        throw new axios.AxiosError("synthetic network failure", "ERR_NETWORK", config);
      },
    });
    auth.configureAuthHttpClient(client, {
      apiBasePath: "/api",
      csrfCookieName: "litblog-csrf",
    });
    setCsrfCookie();
    sessionStorage.setItem("user_info", "active-session-user");
    localStorage.setItem("assignmentDraft:1:2:3", "active draft");
    sessionStorage.setItem("postDraft:1:2:new", "active post draft");

    await expect(auth.logoutBrowserSession(client)).rejects.toThrow("synthetic network failure");

    expect(sessionStorage.getItem("user_info")).toBe("active-session-user");
    expect(localStorage.getItem("assignmentDraft:1:2:3")).toBeNull();
    expect(sessionStorage.getItem("postDraft:1:2:new")).toBeNull();
  });

  it("redacts the CSRF cookie value before request errors reach application logs", async () => {
    const client = axios.create({
      adapter: async (config) => {
        throw new axios.AxiosError("synthetic request failure", "ERR_SYNTHETIC", config);
      },
    });
    auth.configureAuthHttpClient(client, {
      apiBasePath: "/api",
      csrfCookieName: "litblog-csrf",
    });
    setCsrfCookie("synthetic-csrf-cookie-value");

    const error = await client.post("/classes", {
      token: "synthetic-reset-token",
      new_password: "synthetic-new-password",
    }).catch((reason) => reason);

    expect(error.config.headers.get("X-CSRF-Token")).toBeUndefined();
    expect(JSON.stringify(error.config.headers)).not.toContain("synthetic-csrf-cookie-value");
    expect(error.config.data).toBeUndefined();
  });
});

describe("frontend token persistence regression", () => {
  it("contains no JWT storage reads or writes and no direct Bearer construction", () => {
    const violations = sourceFiles(SOURCE_ROOT).flatMap((file) => {
      const source = fs.readFileSync(file, "utf8");
      const relative = path.relative(SOURCE_ROOT, file);
      const patterns = [
        /localStorage\.(?:getItem|setItem)\(\s*["']token["']/,
        /sessionStorage\.(?:getItem|setItem)\(\s*["']token["']/,
        /localStorage\.(?:getItem|setItem)\(\s*["'](?:user_info|class_info)["']/,
        /Authorization\s*:\s*[`"']Bearer\s/,
      ];
      return patterns.some((pattern) => pattern.test(source)) ? [relative] : [];
    });

    expect(violations).toEqual([]);
  });

  it.each(["StudentHub.jsx", "TeacherDashboard.jsx"])(
    "%s relies on cookie requests and session-scoped UI metadata",
    (relativePath) => {
      const source = fs.readFileSync(path.join(SOURCE_ROOT, relativePath), "utf8");
      expect(source).not.toMatch(/localStorage.*token|Authorization\s*:\s*[`"']Bearer/);
      expect(source).toContain("sessionStorage.getItem");
    },
  );

  it("does not log password-reset request secrets through an Axios error", () => {
    const source = fs.readFileSync(path.join(SOURCE_ROOT, "ResetPassword.jsx"), "utf8");

    expect(source).not.toMatch(/console\.error\([^\n]*,\s*error\s*\)/);
  });

  it("keeps the reset form password minimum aligned with the backend", () => {
    const source = fs.readFileSync(path.join(SOURCE_ROOT, "ResetPassword.jsx"), "utf8");

    expect(source).toContain("password.length < 15");
    expect(source).toContain("Password must be at least 15 characters long");
  });
});
