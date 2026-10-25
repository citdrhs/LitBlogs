import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DraftSessionRecovery from "./DraftSessionRecovery.jsx";
import { clearStoredAuth, persistSessionMetadata } from "../utils/auth.js";

const doubles = vi.hoisted(() => ({ post: vi.fn(), get: vi.fn() }));
vi.mock("axios", () => ({ default: doubles }));
vi.mock("../utils/auth.js", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    clearStoredAuth: vi.fn(actual.clearStoredAuth),
    persistSessionMetadata: vi.fn(actual.persistSessionMetadata),
  };
});

const SCHOOL_EMAIL = "hcps-review@henricostudents.org";
const PASSWORD = "Synthetic-recovery-password-Aa1!";
const OWNER_SESSION = { user_id: 41, username: "review-student", role: "STUDENT" };
const onRecovered = vi.fn();
const onDiscard = vi.fn();
const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const open = (props = {}) => render(
  <DraftSessionRecovery ownerId={41} onRecovered={onRecovered} onDiscard={onDiscard} {...props} />,
);
const fillCredentials = () => {
  fireEvent.change(screen.getByLabelText("School email"), { target: { value: SCHOOL_EMAIL } });
  fireEvent.change(screen.getByLabelText("Password"), { target: { value: PASSWORD } });
};
const submit = () => fireEvent.submit(screen.getByRole("button", { name: "Sign in and return to draft" }).closest("form"));

beforeEach(() => {
  vi.clearAllMocks();
  doubles.post.mockReset();
  doubles.get.mockReset();
  doubles.post.mockResolvedValue({ status: 200, data: OWNER_SESSION });
  doubles.get.mockResolvedValue({ status: 200, data: OWNER_SESSION });
  localStorage.clear();
  sessionStorage.clear();
});

describe("DraftSessionRecovery", () => {
  it("explains the locked session and keeps the draft out of the recovery page", () => {
    open();
    expect(screen.getByRole("heading", { name: "Sign in to recover your draft" })).toBeInTheDocument();
    expect(screen.getByText(/session has expired/i)).toBeInTheDocument();
    expect(screen.getByText(/only in this tab/i)).toBeInTheDocument();
    expect(screen.getByText(/same school account/i)).toBeInTheDocument();
    expect(screen.getByLabelText("School email")).toHaveFocus();
    expect(screen.getByLabelText("Password")).toHaveAttribute("type", "password");
    expect(screen.queryByRole("textbox", { name: "Post content" })).not.toBeInTheDocument();
  });

  it("checks the authenticated account twice before restoring access without publishing", async () => {
    const checkedSession = deferred();
    doubles.get.mockReturnValue(checkedSession.promise);
    open();
    fillCredentials();
    submit();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    await waitFor(() => expect(doubles.get).toHaveBeenCalledTimes(1));
    expect(persistSessionMetadata).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
    expect(doubles.post).toHaveBeenCalledWith("/auth/login", {
      email: SCHOOL_EMAIL, password: PASSWORD,
    }, { draftReauthentication: true, signal: expect.any(AbortSignal) });
    expect(doubles.get).toHaveBeenCalledWith("/auth/session", {
      draftReauthentication: true, signal: expect.any(AbortSignal),
    });
    await act(async () => checkedSession.resolve({ status: 200, data: OWNER_SESSION }));
    await waitFor(() => expect(onRecovered).toHaveBeenCalledTimes(1));
    expect(persistSessionMetadata).toHaveBeenCalledWith(OWNER_SESSION);
    expect(onDiscard).not.toHaveBeenCalled();
    expect(clearStoredAuth).not.toHaveBeenCalled();
    expect(doubles.post).toHaveBeenCalledTimes(1);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(PASSWORD);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(SCHOOL_EMAIL);
  });

  it.each(["login", "session"])("discards without exposing work when the %s identity belongs to another account", async (stage) => {
    const other = { status: 200, data: { ...OWNER_SESSION, user_id: 42 } };
    if (stage === "login") doubles.post.mockResolvedValue(other);
    else doubles.get.mockResolvedValue(other);
    open();
    fillCredentials();
    submit();
    await waitFor(() => expect(onDiscard).toHaveBeenCalledTimes(1));
    expect(clearStoredAuth).toHaveBeenCalledTimes(1);
    expect(persistSessionMetadata).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
    expect(clearStoredAuth.mock.invocationCallOrder[0]).toBeLessThan(onDiscard.mock.invocationCallOrder[0]);
    if (stage === "login") expect(doubles.get).not.toHaveBeenCalled();
  });

  it.each(["login", "session"])("fails closed when the %s response has no account identity", async (stage) => {
    const missing = { status: 200, data: { role: "STUDENT" } };
    if (stage === "login") doubles.post.mockResolvedValue(missing);
    else doubles.get.mockResolvedValue(missing);
    open();
    fillCredentials();
    submit();
    await waitFor(() => expect(onDiscard).toHaveBeenCalledTimes(1));
    expect(clearStoredAuth).toHaveBeenCalledTimes(1);
    expect(onRecovered).not.toHaveBeenCalled();
  });

  it.each([
    [401, "Check your school email and password, then try again."],
    [403, "We could not restore your session. Contact your teacher or try again."],
    [429, "Too many sign-in attempts. Wait a few minutes and try again."],
    [503, "Sign-in is temporarily unavailable. Keep this tab open and try again."],
  ])("keeps the draft locked after a %s response and displays only a safe error", async (status, message) => {
    doubles.post.mockRejectedValue({ response: { status, data: { detail: "private backend details" } } });
    open();
    fillCredentials();
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("alert")).toHaveFocus();
    expect(document.body).not.toHaveTextContent("private backend details");
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByLabelText("School email")).toHaveValue(SCHOOL_EMAIL);
    expect(screen.getByRole("button", { name: "Sign in and return to draft" })).toBeEnabled();
    expect(clearStoredAuth).not.toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
    expect(doubles.get).not.toHaveBeenCalled();
  });

  it("keeps the draft locked when the session check has a network failure", async () => {
    doubles.get.mockRejectedValue(new Error("synthetic private upstream outage"));
    open();
    fillCredentials();
    submit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Sign-in is temporarily unavailable");
    expect(document.body).not.toHaveTextContent("synthetic private upstream outage");
    expect(clearStoredAuth).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("blocks duplicate submits and aborts an ignored request on unmount", async () => {
    const request = deferred();
    doubles.post.mockReturnValue(request.promise);
    const view = open();
    fillCredentials();
    const form = screen.getByRole("button", { name: "Sign in and return to draft" }).closest("form");
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(doubles.post).toHaveBeenCalledTimes(1);
    expect(screen.getByLabelText("Password")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Signing in…" })).toBeDisabled();
    const signal = doubles.post.mock.calls[0][2].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => request.resolve({ status: 200, data: OWNER_SESSION }));
    expect(doubles.get).not.toHaveBeenCalled();
    expect(persistSessionMetadata).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("ignores a completed session check after unmount", async () => {
    const request = deferred();
    doubles.get.mockReturnValue(request.promise);
    const view = open();
    fillCredentials();
    submit();
    await waitFor(() => expect(doubles.get).toHaveBeenCalledTimes(1));
    const signal = doubles.get.mock.calls[0][1].signal;
    view.unmount();
    expect(signal.aborted).toBe(true);
    await act(async () => request.resolve({ status: 200, data: OWNER_SESSION }));
    expect(persistSessionMetadata).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();
  });

  it("explicitly discards even while a recovery request is pending", async () => {
    const request = deferred();
    doubles.post.mockImplementation((path) => path === "/auth/login"
      ? request.promise : Promise.resolve({ status: 204 }));
    open();
    fillCredentials();
    submit();
    const signal = doubles.post.mock.calls[0][2].signal;
    fireEvent.click(screen.getByRole("button", { name: "Discard draft and sign out" }));
    expect(signal.aborted).toBe(true);
    expect(clearStoredAuth).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(onDiscard).toHaveBeenCalledTimes(1));
    expect(doubles.post).toHaveBeenLastCalledWith("/auth/logout", {}, {
      draftReauthentication: true, timeout: 10_000,
    });
    expect(clearStoredAuth.mock.invocationCallOrder[0]).toBeLessThan(onDiscard.mock.invocationCallOrder[0]);
    await act(async () => request.resolve({ status: 200, data: OWNER_SESSION }));
    expect(doubles.get).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
  });

  it("clears private memory before a bounded logout and still discards if logout fails", async () => {
    const logout = deferred();
    doubles.post.mockReturnValue(logout.promise);
    open();
    fireEvent.click(screen.getByRole("button", { name: "Discard draft and sign out" }));
    expect(clearStoredAuth).toHaveBeenCalledTimes(1);
    expect(onDiscard).not.toHaveBeenCalled();
    expect(doubles.post).toHaveBeenCalledWith("/auth/logout", {}, {
      draftReauthentication: true, timeout: 10_000,
    });
    await act(async () => logout.reject(new Error("synthetic logout outage")));
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(onRecovered).not.toHaveBeenCalled();
    expect(document.body).not.toHaveTextContent("synthetic logout outage");
  });

  it("starts discard once before clearing memory or logging out and ignores late recovery", async () => {
    const login = deferred();
    const logout = deferred();
    const onDiscardStart = vi.fn();
    doubles.post.mockImplementation((path) => path === "/auth/login"
      ? login.promise : logout.promise);
    open({ onDiscardStart });
    fillCredentials();
    submit();
    const discardButton = screen.getByRole("button", { name: "Discard draft and sign out" });
    fireEvent.click(discardButton);
    expect(onDiscardStart).toHaveBeenCalledTimes(1);
    expect(onDiscardStart.mock.invocationCallOrder[0]).toBeLessThan(clearStoredAuth.mock.invocationCallOrder[0]);
    expect(clearStoredAuth.mock.invocationCallOrder[0]).toBeLessThan(doubles.post.mock.invocationCallOrder[1]);
    expect(onDiscard).not.toHaveBeenCalled();
    fireEvent.click(discardButton);
    expect(onDiscardStart).toHaveBeenCalledTimes(1);
    await act(async () => login.resolve({ status: 200, data: OWNER_SESSION }));
    expect(doubles.get).not.toHaveBeenCalled();
    expect(persistSessionMetadata).not.toHaveBeenCalled();
    expect(onRecovered).not.toHaveBeenCalled();
    expect(onDiscard).not.toHaveBeenCalled();
    await act(async () => logout.resolve({ status: 204 }));
    expect(onDiscard).toHaveBeenCalledTimes(1);
  });
});

