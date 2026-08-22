import { fireEvent, render, screen } from "@testing-library/react";
import axios from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";

import ProtectedRoute from "./ProtectedRoute";

const originalAdapter = axios.defaults.adapter;

afterEach(() => {
  axios.defaults.adapter = originalAdapter;
  sessionStorage.clear();
  localStorage.clear();
});

describe("ProtectedRoute", () => {
  it("authorizes from the HttpOnly cookie session endpoint without a browser JWT", async () => {
    axios.defaults.adapter = async (config) => ({
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
    });

    render(
      <MemoryRouter initialEntries={["/protected"]}>
        <Routes>
          <Route
            path="/protected"
            element={(
              <ProtectedRoute>
                <p>Protected session content</p>
              </ProtectedRoute>
            )}
          />
          <Route path="/sign-in" element={<p>Sign in</p>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Protected session content")).toBeInTheDocument();
    expect(localStorage.getItem("token")).toBeNull();
    expect(JSON.parse(sessionStorage.getItem("user_info"))).toMatchObject({ userId: 42 });
  });

  it("does not render a protected page when the fresh session role is not allowed", async () => {
    const protectedPage = vi.fn(() => <p>Teacher-only data</p>);
    const ProtectedPage = protectedPage;
    axios.defaults.adapter = async (config) => ({
      config,
      data: {
        user_id: 7,
        username: "synthetic-student",
        role: "STUDENT",
        is_admin: false,
      },
      headers: {},
      status: 200,
      statusText: "OK",
    });

    render(
      <MemoryRouter initialEntries={["/teacher-only"]}>
        <Routes>
          <Route
            path="/teacher-only"
            element={(
              <ProtectedRoute allowedRoles={["TEACHER"]}>
                <ProtectedPage />
              </ProtectedRoute>
            )}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(/do not have access/i);
    expect(protectedPage).not.toHaveBeenCalled();
    expect(screen.queryByText("Teacher-only data")).not.toBeInTheDocument();
    expect(JSON.parse(sessionStorage.getItem("user_info"))).toMatchObject({ role: "STUDENT" });
  });

  it("renders a role-scoped page only after a matching fresh session response", async () => {
    axios.defaults.adapter = async (config) => ({
      config,
      data: {
        user_id: 8,
        username: "synthetic-teacher",
        role: "teacher",
        is_admin: false,
      },
      headers: {},
      status: 200,
      statusText: "OK",
    });

    render(
      <MemoryRouter initialEntries={["/teacher-only"]}>
        <Routes>
          <Route
            path="/teacher-only"
            element={(
              <ProtectedRoute allowedRoles={["TEACHER"]}>
                <p>Teacher-only data</p>
              </ProtectedRoute>
            )}
          />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Teacher-only data")).toBeInTheDocument();
  });

  it("preserves return navigation only when the fresh session is unauthenticated", async () => {
    axios.defaults.adapter = async () => {
      throw Object.assign(new Error("unauthenticated"), { response: { status: 401 } });
    };

    const SignInProbe = () => {
      const location = useLocation();
      return <p>Return to {location.state?.from?.pathname || "nowhere"}</p>;
    };

    render(
      <MemoryRouter initialEntries={["/student-hub?tab=assignments"]}>
        <Routes>
          <Route
            path="/student-hub"
            element={(
              <ProtectedRoute allowedRoles={["STUDENT"]}>
                <p>Student data</p>
              </ProtectedRoute>
            )}
          />
          <Route path="/sign-in" element={<SignInProbe />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Return to /student-hub")).toBeInTheDocument();
    expect(screen.queryByText("Student data")).not.toBeInTheDocument();
  });

  it("revalidates the cookie session before rendering a newly scoped route", async () => {
    let sessionRequestCount = 0;
    axios.defaults.adapter = async (config) => {
      sessionRequestCount += 1;
      return {
        config,
        data: {
          user_id: 9,
          username: "synthetic-role-change",
          role: sessionRequestCount === 1 ? "STUDENT" : "TEACHER",
          is_admin: false,
        },
        headers: {},
        status: 200,
        statusText: "OK",
      };
    };

    const ScopedRoute = () => {
      const { scope } = useParams();
      const allowedRole = scope === "teacher" ? "TEACHER" : "STUDENT";
      return (
        <ProtectedRoute allowedRoles={[allowedRole]}>
          <p>{allowedRole} page data</p>
        </ProtectedRoute>
      );
    };

    render(
      <MemoryRouter initialEntries={["/scope/student"]}>
        <Link to="/scope/teacher">Open teacher scope</Link>
        <Routes>
          <Route path="/scope/:scope" element={<ScopedRoute />} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("STUDENT page data")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("link", { name: "Open teacher scope" }));

    expect(await screen.findByText("TEACHER page data")).toBeInTheDocument();
    expect(sessionRequestCount).toBe(2);
  });
});
