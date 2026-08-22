import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    get: doubles.get,
    put: doubles.put,
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
