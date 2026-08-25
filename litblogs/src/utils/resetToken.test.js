import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it, vi } from "vitest";

import {
  capturePasswordResetTokenAtBootstrap,
  clearBootstrappedPasswordResetToken,
  consumePasswordResetToken,
  getBootstrappedPasswordResetToken,
} from "./resetToken";

const sourceRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const fakeWindow = ({ hash = "", search = "" } = {}) => ({
  history: {
    state: { preserved: true },
    replaceState: vi.fn(),
  },
  location: {
    hash,
    pathname: "/reset-password",
    search,
  },
});

describe("password reset URL secret handling", () => {
  it("consumes a fragment token and immediately clears it from browser history", () => {
    const browserWindow = fakeWindow({
      hash: "#token=private-reset-token",
      search: "?return=signin",
    });

    expect(consumePasswordResetToken(browserWindow)).toBe("private-reset-token");
    expect(browserWindow.history.replaceState).toHaveBeenCalledWith(
      browserWindow.history.state,
      "",
      "/reset-password?return=signin",
    );
  });

  it("never accepts a query token and removes legacy query secrets", () => {
    const browserWindow = fakeWindow({
      search: "?token=query-secret&return=signin",
    });

    expect(consumePasswordResetToken(browserWindow)).toBeNull();
    expect(browserWindow.history.replaceState).toHaveBeenCalledWith(
      browserWindow.history.state,
      "",
      "/reset-password?return=signin",
    );
  });

  it("captures reset fragments only on the reset route before app startup", () => {
    clearBootstrappedPasswordResetToken();
    const browserWindow = fakeWindow({ hash: "#token=bootstrap-secret" });

    capturePasswordResetTokenAtBootstrap(browserWindow);

    expect(getBootstrappedPasswordResetToken()).toBe("bootstrap-secret");
    expect(browserWindow.history.replaceState).toHaveBeenCalledOnce();
    clearBootstrappedPasswordResetToken();
  });

  it("bootstraps secret removal before loading OAuth and React application code", () => {
    const projectRoot = path.resolve(sourceRoot, "..");
    const html = fs.readFileSync(path.join(projectRoot, "index.html"), "utf8");
    const bootstrap = fs.readFileSync(path.join(sourceRoot, "bootstrap.js"), "utf8");

    expect(html).toContain('src="/src/bootstrap.js"');
    expect(html).not.toContain('src="/src/main.jsx"');
    expect(bootstrap).not.toMatch(/from\s+["']\.\/main\.jsx["']/);
    expect(bootstrap.indexOf("capturePasswordResetTokenAtBootstrap();"))
      .toBeLessThan(bootstrap.indexOf('import("./main.jsx")'));
  });
});
