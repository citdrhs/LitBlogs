import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  post: vi.fn(),
  writeText: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    get: doubles.get,
    put: doubles.put,
    post: doubles.post,
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
    created_at: "2026-01-03T00:00:00Z",
    disabled: false,
  },
  {
    id: 2,
    username: "student-user",
    email: "student@example.test",
    role: "STUDENT",
    created_at: "2026-01-02T00:00:00Z",
    disabled: false,
  },
  {
    id: 3,
    username: "teacher-user",
    email: "teacher@example.test",
    role: "TEACHER",
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
