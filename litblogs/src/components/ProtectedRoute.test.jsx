import { render, screen } from "@testing-library/react";
import axios from "axios";
import { afterEach, describe, expect, it } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

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
});
