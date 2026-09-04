import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { beforeEach, describe, expect, it, vi } from "vitest";

const sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const loadSubject = async () => {
  vi.resetModules();
  return import("./verificationToken.js");
};

const fakeWindow = ({
  hash = "",
  pathname = "/verify-email",
  search = "",
  state = { preserved: true },
} = {}) => ({
  history: {
    state,
    replaceState: vi.fn(),
  },
  location: { hash, pathname, search },
  localStorage: {
    getItem: vi.fn(),
    setItem: vi.fn(),
  },
  sessionStorage: {
    getItem: vi.fn(),
    setItem: vi.fn(),
  },
});

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("email verification URL secret handling", () => {
  it.each([
    "/verify-email",
    "/verify-email/",
    "/litblogs/verify-email",
    "/litblogs/verify-email/",
  ])("captures a fragment token on the public route %s", async (pathname) => {
    const subject = await loadSubject();
    const browserWindow = fakeWindow({
      hash: "#token=private-verification-token",
      pathname,
      search: "?source=welcome",
    });

    expect(subject.captureEmailVerificationTokenAtBootstrap(browserWindow)).toBe(true);
    expect(browserWindow.history.replaceState).toHaveBeenCalledWith(
      browserWindow.history.state,
      "",
      `${pathname}?source=welcome`,
    );
  });

  it("never accepts a query token and removes it while preserving unrelated query and history state", async () => {
    const subject = await loadSubject();
    const historyState = { navigationId: 9, nested: { preserved: true } };
    const browserWindow = fakeWindow({
      hash: "#section=ignored",
      search: "?token=query-secret&source=signin&topic=email",
      state: historyState,
    });

    expect(subject.captureEmailVerificationTokenAtBootstrap(browserWindow)).toBe(false);
    expect(browserWindow.history.replaceState).toHaveBeenCalledWith(
      historyState,
      "",
      "/verify-email?source=signin&topic=email",
    );
  });

  it("does not consume fragments or rewrite history on any other path", async () => {
    const subject = await loadSubject();
    const browserWindow = fakeWindow({
      hash: "#token=private-verification-token",
      pathname: "/reset-password",
      search: "?token=legacy-query-token",
    });

    expect(subject.captureEmailVerificationTokenAtBootstrap(browserWindow)).toBe(false);
    expect(browserWindow.history.replaceState).not.toHaveBeenCalled();
  });

  it("rejects an oversized fragment without writing, logging, or retaining it", async () => {
    const subject = await loadSubject();
    const oversizedToken = "x".repeat(129);
    const browserWindow = fakeWindow({ hash: `#token=${oversizedToken}` });
    const consoleSpies = [
      vi.spyOn(console, "log").mockImplementation(() => {}),
      vi.spyOn(console, "info").mockImplementation(() => {}),
      vi.spyOn(console, "warn").mockImplementation(() => {}),
      vi.spyOn(console, "error").mockImplementation(() => {}),
    ];

    expect(subject.captureEmailVerificationTokenAtBootstrap(browserWindow)).toBe(false);
    const submit = vi.fn();
    await expect(subject.submitBootstrappedEmailVerification(submit)).rejects.toThrow(
      "Email verification is unavailable",
    );
    expect(submit).not.toHaveBeenCalled();
    expect(browserWindow.localStorage.setItem).not.toHaveBeenCalled();
    expect(browserWindow.sessionStorage.setItem).not.toHaveBeenCalled();
    consoleSpies.forEach((spy) => expect(spy).not.toHaveBeenCalled());
    expect(browserWindow.history.replaceState).toHaveBeenCalledWith(
      browserWindow.history.state,
      "",
      "/verify-email",
    );
  });

  it("rejects ambiguous duplicate fragment tokens", async () => {
    const subject = await loadSubject();
    const browserWindow = fakeWindow({ hash: "#token=first&token=second" });

    expect(subject.captureEmailVerificationTokenAtBootstrap(browserWindow)).toBe(false);
    const submit = vi.fn();
    await expect(subject.submitBootstrappedEmailVerification(submit)).rejects.toThrow(
      "Email verification is unavailable",
    );
    expect(submit).not.toHaveBeenCalled();
    expect(browserWindow.history.replaceState).toHaveBeenCalledWith(
      browserWindow.history.state,
      "",
      "/verify-email",
    );
  });
});

describe("one-time verification submission", () => {
  it("shares one in-flight request across StrictMode-style duplicate consumers", async () => {
    const subject = await loadSubject();
    const browserWindow = fakeWindow({ hash: "#token=single-use-token" });
    subject.captureEmailVerificationTokenAtBootstrap(browserWindow);
    let resolveRequest;
    const request = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    const submit = vi.fn(() => request);

    const first = subject.submitBootstrappedEmailVerification(submit);
    const replay = subject.submitBootstrappedEmailVerification(submit);

    expect(first).toBe(replay);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(submit).toHaveBeenCalledWith("single-use-token");
    resolveRequest({ status: 200 });
    await expect(first).resolves.toEqual({ status: 200 });
  });

  it.each(["resolve", "reject"])(
    "cannot replay a token after terminal %s and drops the completed promise",
    async (terminalState) => {
      const subject = await loadSubject();
      subject.captureEmailVerificationTokenAtBootstrap(
        fakeWindow({ hash: "#token=terminal-token" }),
      );
      const terminalError = new Error("private transport detail");
      const submit = vi.fn(() => (
        terminalState === "resolve"
          ? Promise.resolve({ status: 200 })
          : Promise.reject(terminalError)
      ));

      if (terminalState === "resolve") {
        await expect(subject.submitBootstrappedEmailVerification(submit)).resolves.toEqual({
          status: 200,
        });
      } else {
        await expect(subject.submitBootstrappedEmailVerification(submit)).rejects.toBe(terminalError);
      }

      const replaySubmit = vi.fn();
      await expect(subject.submitBootstrappedEmailVerification(replaySubmit)).rejects.toThrow(
        "Email verification is unavailable",
      );
      expect(replaySubmit).not.toHaveBeenCalled();
      expect(submit).toHaveBeenCalledTimes(1);
    },
  );

  it("does not re-arm or detach an in-flight verification when capture runs again", async () => {
    const subject = await loadSubject();
    subject.captureEmailVerificationTokenAtBootstrap(
      fakeWindow({ hash: "#token=first-single-use-token" }),
    );
    let resolveRequest;
    const request = new Promise((resolve) => {
      resolveRequest = resolve;
    });
    const submit = vi.fn(() => request);
    const first = subject.submitBootstrappedEmailVerification(submit);

    const recaptureWindow = fakeWindow({ hash: "#token=second-single-use-token" });
    expect(subject.captureEmailVerificationTokenAtBootstrap(recaptureWindow)).toBe(true);
    const replaySubmit = vi.fn();
    const replay = subject.submitBootstrappedEmailVerification(replaySubmit);

    expect(replay).toBe(first);
    expect(submit).toHaveBeenCalledTimes(1);
    expect(replaySubmit).not.toHaveBeenCalled();
    expect(recaptureWindow.history.replaceState).toHaveBeenCalledWith(
      recaptureWindow.history.state,
      "",
      "/verify-email",
    );
    resolveRequest({ status: 200 });
    await expect(first).resolves.toEqual({ status: 200 });
  });

  it("does not accept a new fragment after terminal verification completion", async () => {
    const subject = await loadSubject();
    subject.captureEmailVerificationTokenAtBootstrap(
      fakeWindow({ hash: "#token=completed-single-use-token" }),
    );
    await subject.submitBootstrappedEmailVerification(() => Promise.resolve({ status: 200 }));

    const recaptureWindow = fakeWindow({ hash: "#token=late-single-use-token" });
    expect(subject.captureEmailVerificationTokenAtBootstrap(recaptureWindow)).toBe(false);
    const replaySubmit = vi.fn();
    await expect(subject.submitBootstrappedEmailVerification(replaySubmit)).rejects.toThrow(
      "Email verification is unavailable",
    );
    expect(replaySubmit).not.toHaveBeenCalled();
    expect(recaptureWindow.history.replaceState).toHaveBeenCalledWith(
      recaptureWindow.history.state,
      "",
      "/verify-email",
    );
  });
});

describe("bootstrap ordering", () => {
  it("removes verification and reset URL secrets before loading the React application", () => {
    const projectRoot = path.resolve(sourceRoot, "..");
    const html = fs.readFileSync(path.join(projectRoot, "index.html"), "utf8");
    const bootstrap = fs.readFileSync(path.join(sourceRoot, "bootstrap.js"), "utf8");

    expect(html).toContain('src="/src/bootstrap.js"');
    expect(html).not.toContain('src="/src/main.jsx"');
    expect(bootstrap).not.toMatch(/from\s+["']\.\/main\.jsx["']/);
    expect(bootstrap).toContain("captureEmailVerificationTokenAtBootstrap();");
    expect(bootstrap.indexOf("captureEmailVerificationTokenAtBootstrap();"))
      .toBeLessThan(bootstrap.indexOf('import("./main.jsx")'));
  });
});
