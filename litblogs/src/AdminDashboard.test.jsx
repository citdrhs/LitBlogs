import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  delete: vi.fn(),
  writeText: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    get: doubles.get,
    put: doubles.put,
    post: doubles.post,
    delete: doubles.delete,
  },
}));

vi.mock("./components/Navbar", () => ({ default: () => <nav>Admin navigation</nav> }));
vi.mock("./components/Footer", () => ({ default: () => <footer>Admin footer</footer> }));

import AdminDashboard from "./AdminDashboard";

const initialUsers = [
  {
    id: 1,
    username: "admin-user",
    email: "admin@example.test",
    role: "ADMIN",
    email_verified: true,
    created_at: "2026-01-03T00:00:00Z",
    disabled: false,
  },
  {
    id: 2,
    username: "student-user",
    email: "student@example.test",
    role: "STUDENT",
    email_verified: true,
    created_at: "2026-01-02T00:00:00Z",
    disabled: false,
  },
  {
    id: 3,
    username: "teacher-user",
    email: "teacher@example.test",
    role: "TEACHER",
    email_verified: true,
    created_at: "2026-01-01T00:00:00Z",
    disabled: true,
  },
];

const renderDashboard = () => render(
  <MemoryRouter>
    <AdminDashboard />
  </MemoryRouter>,
);

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  doubles.post.mockReset();
  doubles.delete.mockReset();
  doubles.writeText.mockReset().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: doubles.writeText },
  });
  sessionStorage.setItem("user_info", JSON.stringify({
    userId: 1,
    username: "admin-user",
    role: "ADMIN",
    is_admin: true,
  }));

  let users = structuredClone(initialUsers);
  doubles.get.mockImplementation(async (path) => {
    if (path === "/users") return { data: structuredClone(users) };
    if (path === "/classes") return { data: [] };
    throw new Error(`Unexpected GET ${path}`);
  });
  doubles.put.mockImplementation(async (path, payload) => {
    const match = path.match(/^\/users\/(\d+)\/status$/);
    if (!match) throw new Error(`Unexpected PUT ${path}`);
    const userId = Number(match[1]);
    users = users.map((user) => (
      user.id === userId ? { ...user, disabled: payload.disabled } : user
    ));
    return { data: { disabled: payload.disabled } };
  });
  doubles.delete.mockImplementation(async (path) => {
    const match = path.match(/^\/admin\/users\/(\d+)$/);
    if (!match) throw new Error(`Unexpected DELETE ${path}`);
    users = users.filter((user) => user.id !== Number(match[1]));
    return { status: 204 };
  });
});

const invitation = {
  email: "new.teacher@school.edu",
  invitation_token: "synthetic-private-invitation-code",
  expires_at: "2026-09-14T18:00:00Z",
};

const openInvitation = async () => {
  const button = await screen.findByRole("button", { name: "Invite Teacher" });
  button.focus();
  fireEvent.click(button);
  return screen.getByRole("dialog", { name: "Invite Teacher" });
};

const submitInvitation = (dialog, email = invitation.email) => {
  fireEvent.change(within(dialog).getByLabelText("Teacher email"), {
    target: { value: email },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Create invitation" }));
};

describe("administrator teacher invitations", () => {
  it("opens a focused dialog for a student-domain admin and explains replacement", async () => {
    sessionStorage.setItem("user_info", JSON.stringify({
      userId: 1,
      username: "student-domain-admin",
      email: "admin@students.school.edu",
      role: "ADMIN",
      is_admin: true,
    }));
    renderDashboard();

    const dialog = await openInvitation();
    const email = within(dialog).getByLabelText("Teacher email");
    expect(email).toHaveFocus();
    expect(email).toHaveAttribute("type", "email");
    expect(email).toHaveAttribute("maxlength", "100");
    expect(email).toBeRequired();
    expect(within(dialog).getByText(/replaces any previous unused invitation/i)).toBeInTheDocument();

    const close = within(dialog).getByRole("button", { name: "Close" });
    close.focus();
    fireEvent.keyDown(close, { key: "Tab" });
    expect(email).toHaveFocus();
    fireEvent.keyDown(email, { key: "Tab", shiftKey: true });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Invite Teacher" })).toHaveFocus();
    expect(doubles.post).not.toHaveBeenCalled();
  });

  it("creates an email-bound invitation and copies signup instructions without persisting the code", async () => {
    doubles.post.mockResolvedValueOnce({ data: invitation });
    renderDashboard();
    const dialog = await openInvitation();
    submitInvitation(dialog, "  New.Teacher@school.edu  ");

    expect(await within(dialog).findByLabelText("Invitation code")).toHaveValue(invitation.invitation_token);
    expect(doubles.post).toHaveBeenCalledWith("/admin/teacher-invitations", {
      email: "New.Teacher@school.edu",
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(within(dialog).getByText(invitation.email)).toBeInTheDocument();
    expect(within(dialog).getByText(/expires/i).querySelector("time")).toHaveAttribute("datetime", invitation.expires_at);
    const signup = within(dialog).getByRole("link", { name: /sign up/i });
    expect(signup).toHaveAttribute("href", `${window.location.origin}/sign-up`);
    expect(signup.href).not.toContain(invitation.invitation_token);
    expect(within(dialog).getByText(/choose Teacher/i)).toHaveTextContent(/verify your email/i);
    expect(within(dialog).getByText(/no email has been sent/i)).toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Copy invitation" }));
    expect(await within(dialog).findByRole("status")).toHaveTextContent("Invitation copied");
    expect(doubles.writeText).toHaveBeenCalledWith(expect.stringContaining(invitation.invitation_token));
    const copied = doubles.writeText.mock.calls[0][0];
    expect(copied).toContain(invitation.email);
    expect(copied).toContain(`${window.location.origin}/sign-up`);
    expect(copied).toMatch(/choose Teacher/i);
    expect(copied).toMatch(/verify your email/i);
    expect(copied).toMatch(/once/i);
    expect(copied).toMatch(/expire/i);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain(invitation.invitation_token);

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByDisplayValue(invitation.invitation_token)).not.toBeInTheDocument();
    const reopened = await openInvitation();
    expect(within(reopened).getByLabelText("Teacher email")).toHaveValue("");
    expect(within(reopened).queryByLabelText("Invitation code")).not.toBeInTheDocument();
  });

  it("blocks duplicate submissions while pending and ignores a response after dismissal", async () => {
    let resolveRequest;
    doubles.post.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve; }));
    renderDashboard();
    const dialog = await openInvitation();
    submitInvitation(dialog);
    const create = within(dialog).getByRole("button", { name: "Creating invitation…" });
    expect(create).toBeDisabled();
    expect(within(dialog).getByLabelText("Teacher email")).toBeDisabled();
    fireEvent.click(create);
    expect(doubles.post).toHaveBeenCalledTimes(1);

    const { signal } = doubles.post.mock.calls[0][2];
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(signal.aborted).toBe(true);
    const reopened = await openInvitation();
    await act(async () => { resolveRequest({ data: invitation }); });
    expect(within(reopened).getByLabelText("Teacher email")).toHaveValue("");
    expect(screen.queryByDisplayValue(invitation.invitation_token)).not.toBeInTheDocument();
  });

  it.each([
    [400, "Enter an email address from an approved school domain."],
    [422, "Enter an email address from an approved school domain."],
    [409, "An invitation could not be created for this email. Check whether an account already exists."],
    [403, "You need an active administrator session to create invitations. Sign in again."],
    [503, "The invitation could not be created. Try again."],
    [undefined, "The invitation could not be created. Try again."],
  ])("shows safe, recoverable errors for status %s", async (status, message) => {
    doubles.post.mockRejectedValueOnce({
      response: { status, data: { detail: "sensitive database topology" } },
    });
    renderDashboard();
    const dialog = await openInvitation();
    submitInvitation(dialog);

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText("sensitive database topology")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Create invitation" })).toBeEnabled();
    expect(within(dialog).getByLabelText("Teacher email")).toHaveValue(invitation.email);
  });

  it("provides selectable instructions when clipboard access fails", async () => {
    doubles.post.mockResolvedValueOnce({ data: invitation });
    doubles.writeText.mockRejectedValueOnce(new Error("sensitive clipboard failure"));
    renderDashboard();
    const dialog = await openInvitation();
    submitInvitation(dialog);
    fireEvent.click(await within(dialog).findByRole("button", { name: "Copy invitation" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Copy failed. Select and copy the invitation below.");
    const manual = within(dialog).getByLabelText("Invitation to copy manually");
    expect(manual.value).toContain(invitation.invitation_token);
    expect(manual).toHaveFocus();
    expect(manual.selectionStart).toBe(0);
    expect(manual.selectionEnd).toBe(manual.value.length);
    expect(screen.queryByText("sensitive clipboard failure")).not.toBeInTheDocument();
  });
});

describe("administrator account lifecycle controls", () => {
  it("uses a generic dashboard load failure", async () => {
    doubles.get.mockRejectedValue({
      response: { data: { detail: "sensitive database topology" } },
    });

    renderDashboard();

    expect(await screen.findByText("Error: Failed to load dashboard data")).toBeInTheDocument();
    expect(screen.queryByText("sensitive database topology")).not.toBeInTheDocument();
  });

  it("confirms a disable, refreshes safe status state, and prevents self-disable", async () => {
    renderDashboard();

    expect(await screen.findByRole("heading", { name: "Admin Dashboard" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disable admin-user" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enable teacher-user" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "Disable student-user" }));
    const dialog = screen.getByRole("dialog", { name: "Disable student-user?" });
    expect(within(dialog).getByText(/immediately revokes active sessions/i)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm disable" }));

    await waitFor(() => {
      expect(doubles.put).toHaveBeenCalledWith("/users/2/status", { disabled: true });
      expect(doubles.get.mock.calls.filter(([path]) => path === "/users")).toHaveLength(2);
    });
    expect(await screen.findByRole("status")).toHaveTextContent("student-user has been disabled");
    expect(screen.getByRole("button", { name: "Enable student-user" })).toBeEnabled();
  });

  it("shows a generic accessible failure and keeps the prior status", async () => {
    doubles.put.mockRejectedValueOnce({
      response: { data: { detail: "sensitive operator failure" } },
    });
    renderDashboard();
    await screen.findByRole("heading", { name: "Admin Dashboard" });

    fireEvent.click(screen.getByRole("button", { name: "Enable teacher-user" }));
    fireEvent.click(
      within(screen.getByRole("dialog", { name: "Enable teacher-user?" }))
        .getByRole("button", { name: "Confirm enable" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Account status could not be updated. Try again.",
    );
    expect(screen.queryByText("sensitive operator failure")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable teacher-user" })).toBeEnabled();
  });
});

const recovery = {
  email: "student@example.test",
  reset_url: "https://school.example/dren/reset-password?token=synthetic-private-recovery-code",
  expires_at: "2026-09-25T22:00:00Z",
};

const openAccountAction = async (action, username = "student-user") => {
  const button = await screen.findByRole("button", { name: `${action} ${username}` });
  button.focus();
  fireEvent.click(button);
  return screen.getByRole("dialog", { name: `${action} for ${username}` });
};

describe("administrator account recovery", () => {
  it("creates a manually shared recovery link without sending email or persisting credentials", async () => {
    doubles.post.mockResolvedValueOnce({ data: recovery });
    renderDashboard();
    const dialog = await openAccountAction("Recover access");
    expect(within(dialog).getByLabelText("Share a recovery link myself")).toBeChecked();
    expect(within(dialog).getByLabelText("Share a recovery link myself")).toHaveFocus();
    expect(doubles.post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Create recovery link" }));

    const link = await within(dialog).findByLabelText("Recovery link");
    expect(link).toHaveValue(recovery.reset_url);
    expect(link).toHaveAttribute("readonly");
    expect(link).toHaveFocus();
    expect(doubles.post).toHaveBeenCalledWith("/admin/users/2/recovery", { delivery: "manual" }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(within(dialog).getByText(/no email has been sent/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/expires/i).querySelector("time")).toHaveAttribute("datetime", recovery.expires_at);
    expect(within(dialog).queryByText(/temporary password/i)).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Copy recovery link" }));
    expect(await within(dialog).findByRole("status")).toHaveTextContent("Recovery link copied.");
    expect(doubles.writeText).toHaveBeenCalledWith(recovery.reset_url);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain("synthetic-private-recovery-code");

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByDisplayValue(recovery.reset_url)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recover access student-user" })).toHaveFocus();
    const reopened = await openAccountAction("Recover access");
    expect(within(reopened).queryByLabelText("Recovery link")).not.toBeInTheDocument();
  });

  it("requires selecting email delivery and submitting before queuing recovery email", async () => {
    doubles.post.mockResolvedValueOnce({ data: { email: recovery.email, queued: true } });
    renderDashboard();
    const dialog = await openAccountAction("Recover access");
    fireEvent.click(within(dialog).getByLabelText("Email a recovery link to this user"));
    expect(doubles.post).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Send recovery email" }));

    expect(await within(dialog).findByRole("status")).toHaveTextContent("Recovery email queued");
    expect(doubles.post).toHaveBeenCalledWith("/admin/users/2/recovery", { delivery: "email" }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(within(dialog).queryByLabelText("Recovery link")).not.toBeInTheDocument();
    expect(doubles.writeText).not.toHaveBeenCalled();
  });

  it("prevents duplicate recovery requests and keeps the dialog open until issuance finishes", async () => {
    let resolveRequest;
    doubles.post.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve; }));
    renderDashboard();
    const dialog = await openAccountAction("Recover access");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create recovery link" }));
    const pending = within(dialog).getByRole("button", { name: "Requesting recovery…" });
    expect(pending).toBeDisabled();
    expect(within(dialog).getByLabelText("Email a recovery link to this user")).toBeDisabled();
    fireEvent.click(pending);
    expect(doubles.post).toHaveBeenCalledTimes(1);
    const { signal } = doubles.post.mock.calls[0][2];
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeDisabled();
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(signal.aborted).toBe(false);
    await act(async () => { resolveRequest({ data: recovery }); });
    expect(within(dialog).getByLabelText("Recovery link")).toHaveValue(recovery.reset_url);
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(signal.aborted).toBe(true);
    const reopened = await openAccountAction("Recover access");
    expect(within(reopened).queryByLabelText("Recovery link")).not.toBeInTheDocument();
  });

  it("selects the recovery link for manual copying if clipboard access fails", async () => {
    doubles.post.mockResolvedValueOnce({ data: recovery });
    doubles.writeText.mockRejectedValueOnce(new Error("private clipboard error"));
    renderDashboard();
    const dialog = await openAccountAction("Recover access");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create recovery link" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Copy recovery link" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Copy failed. Select and copy the recovery link above.");
    const link = within(dialog).getByLabelText("Recovery link");
    expect(link).toHaveFocus();
    expect(link.selectionStart).toBe(0);
    expect(link.selectionEnd).toBe(link.value.length);
    expect(screen.queryByText("private clipboard error")).not.toBeInTheDocument();
  });

  it.each([
    [403, "You need an active administrator session. Sign in again."],
    [404, "This account is no longer available. Refresh the dashboard."],
    [409, "Recovery requires an active account with a verified email."],
    [503, "Recovery could not be requested. Try again."],
  ])("shows safe recovery guidance for status %s", async (status, message) => {
    doubles.post.mockRejectedValueOnce({ response: { status, data: { detail: "private backend detail" } } });
    renderDashboard();
    const dialog = await openAccountAction("Recover access");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create recovery link" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
    expect(within(dialog).getByRole("button", { name: "Create recovery link" })).toBeEnabled();
    expect(screen.queryByText("private backend detail")).not.toBeInTheDocument();
  });

  it("disables recovery for disabled users without hiding the reason", async () => {
    renderDashboard();
    const button = await screen.findByRole("button", { name: "Recover access teacher-user" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", "Enable this account before recovering access");
  });

  it("identifies unverified email and directs the user to resend verification before recovery", async () => {
    doubles.get.mockImplementation(async (path) => {
      if (path === "/users") return { data: initialUsers.map((user) => ({
        ...user,
        email_verified: user.id !== 2,
      })) };
      if (path === "/classes") return { data: [] };
      throw new Error(`Unexpected GET ${path}`);
    });
    renderDashboard();

    const button = await screen.findByRole("button", { name: "Recover access student-user" });
    expect(screen.getByText("Email unverified")).toBeInTheDocument();
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("title", `Ask this user to resend their verification email at ${window.location.origin}/verify-email?resend=1`);
    expect(screen.getByText(/Ask this user to request a new verification email/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Verification page" })).toHaveAttribute("href", `${window.location.origin}/verify-email?resend=1`);
    expect(screen.getByRole("button", { name: "Recover access admin-user" })).toBeEnabled();
    fireEvent.click(button);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(doubles.post).not.toHaveBeenCalled();
  });

  it.each([
    ["120", "A recovery email was requested recently. Try again in 2 minutes."],
    [undefined, "A recovery email was requested recently. Wait a few minutes before trying again."],
  ])("explains the recovery email cooldown with Retry-After %s", async (retryAfter, message) => {
    doubles.post.mockRejectedValueOnce({ response: {
      status: 429,
      headers: { "retry-after": retryAfter },
      data: { detail: "private cooldown detail" },
    } });
    renderDashboard();
    const dialog = await openAccountAction("Recover access");
    fireEvent.click(within(dialog).getByLabelText("Email a recovery link to this user"));
    fireEvent.click(within(dialog).getByRole("button", { name: "Send recovery email" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeEnabled();
    expect(within(dialog).queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText("private cooldown detail")).not.toBeInTheDocument();
  });
});

describe("administrator email verification links", () => {
  const verification = {
    email: "student@example.test",
    verification_url: "https://school.example/dren/verify-email#token=synthetic-private-verification-code",
    expires_at: "2026-09-26T22:00:00Z",
  };

  beforeEach(() => {
    doubles.get.mockImplementation(async (path) => {
      if (path === "/users") return { data: initialUsers.map((user) => ({ ...user, email_verified: user.id === 1 })) };
      if (path === "/classes") return { data: [] };
      throw new Error(`Unexpected GET ${path}`);
    });
  });

  it("offers verification only for unverified accounts and disables it for disabled accounts", async () => {
    renderDashboard();
    expect(await screen.findByRole("button", { name: "Create verification link student-user" })).toBeEnabled();
    const disabled = screen.getByRole("button", { name: "Create verification link teacher-user" });
    expect(disabled).toBeDisabled();
    expect(disabled).toHaveAttribute("title", "Enable this account before creating a verification link");
    expect(screen.queryByRole("button", { name: "Create verification link admin-user" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recover access student-user" })).toBeDisabled();
  });

  it("creates and copies a private one-time verification link, then clears it on close", async () => {
    doubles.post.mockResolvedValueOnce({ data: verification });
    renderDashboard();
    const dialog = await openAccountAction("Create verification link");
    const create = within(dialog).getByRole("button", { name: "Create verification link" });
    expect(create).toHaveFocus();
    expect(doubles.post).not.toHaveBeenCalled();
    expect(within(dialog).queryByLabelText("Email a recovery link to this user")).not.toBeInTheDocument();
    fireEvent.click(create);

    const link = await within(dialog).findByLabelText("Verification link");
    expect(link).toHaveValue(verification.verification_url);
    expect(link).toHaveAttribute("readonly");
    expect(link).toHaveFocus();
    expect(doubles.post).toHaveBeenCalledWith("/admin/users/2/verification", {}, expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(within(dialog).getByText(/share this link privately/i)).toHaveTextContent("No email has been sent.");
    expect(within(dialog).getByText(/can be used once/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/^Expires:/i).querySelector("time")).toHaveAttribute("datetime", verification.expires_at);
    fireEvent.click(within(dialog).getByRole("button", { name: "Copy verification link" }));
    expect(await within(dialog).findByRole("status")).toHaveTextContent("Verification link copied.");
    expect(doubles.writeText).toHaveBeenCalledWith(verification.verification_url);
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain("synthetic-private-verification-code");

    fireEvent.click(within(dialog).getByRole("button", { name: "Close" }));
    expect(screen.queryByDisplayValue(verification.verification_url)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create verification link student-user" })).toHaveFocus();
    const reopened = await openAccountAction("Create verification link");
    expect(within(reopened).queryByLabelText("Verification link")).not.toBeInTheDocument();
  });

  it("keeps verification issuance open and prevents duplicate requests", async () => {
    let resolveRequest;
    doubles.post.mockImplementationOnce(() => new Promise((resolve) => { resolveRequest = resolve; }));
    renderDashboard();
    const dialog = await openAccountAction("Create verification link");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create verification link" }));
    const pending = within(dialog).getByRole("button", { name: "Creating verification link…" });
    expect(pending).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeDisabled();
    fireEvent.click(pending);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(doubles.post).toHaveBeenCalledTimes(1);
    await act(async () => { resolveRequest({ data: verification }); });
    expect(within(dialog).getByLabelText("Verification link")).toHaveValue(verification.verification_url);
    expect(within(dialog).getByRole("button", { name: "Close" })).toBeEnabled();
  });

  it("selects the verification link for manual copying when clipboard access fails", async () => {
    doubles.post.mockResolvedValueOnce({ data: verification });
    doubles.writeText.mockRejectedValueOnce(new Error("private clipboard error"));
    renderDashboard();
    const dialog = await openAccountAction("Create verification link");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create verification link" }));
    fireEvent.click(await within(dialog).findByRole("button", { name: "Copy verification link" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Copy failed. Select and copy the verification link above.");
    const link = within(dialog).getByLabelText("Verification link");
    expect(link).toHaveFocus();
    expect(link.selectionStart).toBe(0);
    expect(link.selectionEnd).toBe(link.value.length);
  });

  it.each([
    [409, "Verification links require an active account with an unverified email. Refresh the dashboard and try again."],
    [503, "The verification link could not be created. Try again."],
  ])("shows safe verification guidance for status %s", async (status, message) => {
    doubles.post.mockRejectedValueOnce({ response: { status, data: { detail: "private verification detail" } } });
    renderDashboard();
    const dialog = await openAccountAction("Create verification link");
    fireEvent.click(within(dialog).getByRole("button", { name: "Create verification link" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
    expect(within(dialog).getByRole("button", { name: "Create verification link" })).toBeEnabled();
    expect(screen.queryByText("private verification detail")).not.toBeInTheDocument();
  });
});

describe("administrator account deletion", () => {
  it("blocks self-deletion and requires the exact target email with clear consequences", async () => {
    renderDashboard();
    expect(await screen.findByRole("button", { name: "Delete account admin-user" })).toBeDisabled();
    const dialog = await openAccountAction("Delete account", "teacher-user");
    expect(within(dialog).getByText(/cannot be undone/i)).toBeInTheDocument();
    expect(within(dialog).getByText(/classes, schoolwork, or uploads/i)).toBeInTheDocument();
    const confirmation = within(dialog).getByLabelText("Type teacher@example.test to confirm");
    expect(confirmation).toHaveFocus();
    const remove = within(dialog).getByRole("button", { name: "Permanently delete account" });
    for (const value of ["DELETE", "student@example.test", "TEACHER@example.test", "teacher@example.test "]) {
      fireEvent.change(confirmation, { target: { value } });
      expect(remove).toBeDisabled();
    }
    fireEvent.change(confirmation, { target: { value: "teacher@example.test" } });
    expect(remove).toBeEnabled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(doubles.delete).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete account teacher-user" })).toHaveFocus();
  });

  it("deletes only the confirmed target and refreshes users and classes", async () => {
    renderDashboard();
    const dialog = await openAccountAction("Delete account");
    fireEvent.change(within(dialog).getByLabelText("Type student@example.test to confirm"), { target: { value: "student@example.test" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Permanently delete account" }));
    await waitFor(() => expect(doubles.delete).toHaveBeenCalledWith("/admin/users/2", expect.objectContaining({
      params: { confirm: "student@example.test" },
      signal: expect.any(AbortSignal),
    })));
    expect(await screen.findByRole("status")).toHaveTextContent("student-user has been deleted.");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete account student-user" })).not.toBeInTheDocument();
    await waitFor(() => {
      expect(doubles.get.mock.calls.filter(([path]) => path === "/users")).toHaveLength(2);
      expect(doubles.get.mock.calls.filter(([path]) => path === "/classes")).toHaveLength(2);
    });
  });

  it("prevents duplicate deletion and keeps confirmation open until the request finishes", async () => {
    let rejectRequest;
    doubles.delete.mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRequest = reject; }));
    renderDashboard();
    const dialog = await openAccountAction("Delete account");
    fireEvent.change(within(dialog).getByLabelText("Type student@example.test to confirm"), { target: { value: "student@example.test" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Permanently delete account" }));
    const remove = within(dialog).getByRole("button", { name: "Deleting account…" });
    expect(remove).toBeDisabled();
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.click(remove);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(doubles.delete).toHaveBeenCalledTimes(1);
    await act(async () => { rejectRequest({ response: { status: 503 } }); });
    expect(within(dialog).getByRole("alert")).toHaveTextContent("The account could not be deleted. Try again.");
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toBeEnabled();
  });

  it("keeps the account and shows preservation guidance when deletion is blocked", async () => {
    doubles.delete.mockRejectedValueOnce({ response: { status: 409, data: { detail: "private database dependency" } } });
    renderDashboard();
    const dialog = await openAccountAction("Delete account", "teacher-user");
    fireEvent.change(within(dialog).getByLabelText("Type teacher@example.test to confirm"), { target: { value: "teacher@example.test" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Permanently delete account" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("This account is protected or still has classes, schoolwork, or uploads.");
    expect(screen.getByRole("button", { name: "Delete account teacher-user" })).toBeInTheDocument();
    expect(screen.queryByText("private database dependency")).not.toBeInTheDocument();
  });
});
