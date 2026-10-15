import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { clearPendingVerification, getPendingVerification } from "./utils/pendingVerification";
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const doubles = vi.hoisted(() => ({
  get: vi.fn(),
  loginPopup: vi.fn(),
  post: vi.fn(),
  fetchBrowserSession: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    get: doubles.get,
    post: doubles.post,
  },
}));

vi.mock("@azure/msal-react", () => ({
  useMsal: () => ({ instance: { loginPopup: doubles.loginPopup } }),
}));

vi.mock("@react-oauth/google", () => ({
  GoogleLogin: ({ onSuccess }) => (
    <button
      type="button"
      onClick={() => onSuccess({ credential: "synthetic-google-id-token" })}
    >
      Synthetic Google
    </button>
  ),
}));

vi.mock("./utils/auth", () => ({
  fetchBrowserSession: doubles.fetchBrowserSession,
  persistSessionMetadata: vi.fn(),
}));

vi.mock("./utils/userSettings", () => ({
  applyGlobalUserSettings: vi.fn(),
  saveLocalUserSettings: vi.fn(() => ({ darkMode: false })),
}));

let SignIn;
let SignUp;

beforeAll(async () => {
  vi.stubEnv("VITE_GOOGLE_OAUTH_ENABLED", "true");
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "987654321.apps.googleusercontent.com");
  vi.stubEnv("VITE_MICROSOFT_OAUTH_ENABLED", "true");
  vi.stubEnv("VITE_MICROSOFT_CLIENT_ID", "2f1c67a1-91e2-46a3-941f-b88e31763e51");
  vi.stubEnv("VITE_MICROSOFT_TENANT_ID", "871bd3e0-2dc0-4a40-9b07-9d03068c2364");
  ({ default: SignIn } = await import("./Sign-in.jsx"));
  ({ default: SignUp } = await import("./Sign-up.jsx"));
});

afterAll(() => {
  vi.unstubAllEnvs();
});

beforeEach(() => {
  vi.clearAllMocks();
  clearPendingVerification();
  window.matchMedia = vi.fn().mockReturnValue({ matches: false });
  doubles.post.mockResolvedValue({ data: {} });
  doubles.get.mockResolvedValue({ data: {} });
  doubles.fetchBrowserSession.mockResolvedValue({ role: "STUDENT" });
  doubles.loginPopup.mockResolvedValue({
    idToken: "synthetic-microsoft-id-token",
    account: {
      username: "raw-profile-must-not-be-sent@attacker.example",
      name: "Raw Profile",
      localAccountId: "raw-profile-id",
    },
  });
});

describe("pending local-password sign in", () => {
  it("redirects after a correct-password pending response without starting a session", async () => {
    doubles.post.mockRejectedValue({ response: { status: 403, data: { detail: {
      code: "email_verification_required",
      email: "student@example.com",
      verification_challenge: "synthetic-private-challenge",
      expires_at: new Date(Date.now() + 900_000).toISOString(),
      teacher_code_allowed: true,
    } } } });
    render(<MemoryRouter initialEntries={["/sign-in"]}><Routes>
      <Route path="/sign-in" element={<SignIn />} />
      <Route path="/verify-email" element={<h1>Pending verification page</h1>} />
    </Routes></MemoryRouter>);
    expect(screen.queryByRole("link", { name: /request another verification email/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /teacher code/i })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Email Address"), { target: { value: "student@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Synthetic-password-15!" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign In" }));
    expect(await screen.findByRole("heading", { name: "Pending verification page" })).toBeInTheDocument();
    expect(getPendingVerification()?.challenge).toBe("synthetic-private-challenge");
    expect(doubles.fetchBrowserSession).not.toHaveBeenCalled();
    expect(doubles.get).not.toHaveBeenCalled();
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain("synthetic-private-challenge");
  });
});

describe("federated sign-in payloads", () => {
  it("posts only the Google ID token", async () => {
    render(
      <MemoryRouter>
        <SignIn />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Synthetic Google" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith("/auth/google-login", {
        idToken: "synthetic-google-id-token",
      });
    });
  });

  it("posts only the Microsoft ID token and never the account profile", async () => {
    render(
      <MemoryRouter>
        <SignIn />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Sign in with Microsoft" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith("/auth/microsoft-login", {
        idToken: "synthetic-microsoft-id-token",
      });
    });
    expect(JSON.stringify(doubles.post.mock.calls)).not.toContain("raw-profile-must-not-be-sent");
  });
});

describe("federated signup payloads", () => {
  it("does not expose public administrator registration", () => {
    render(
      <MemoryRouter>
        <SignUp />
      </MemoryRouter>,
    );

    expect(screen.queryByRole("option", { name: "Admin" })).not.toBeInTheDocument();
    const source = readFileSync(resolve("src", "Sign-up.jsx"), "utf8");
    expect(source).not.toMatch(/\bADMIN\b/);
  });

  it("posts only the Google ID token plus the requested public role", async () => {
    render(
      <MemoryRouter>
        <SignUp />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "STUDENT" } });

    fireEvent.click(screen.getByRole("button", { name: "Synthetic Google" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith("/auth/google-signup", {
        idToken: "synthetic-google-id-token",
        role: "STUDENT",
      });
    });
  });

  it("posts only the Microsoft ID token plus the requested public role", async () => {
    render(
      <MemoryRouter>
        <SignUp />
      </MemoryRouter>,
    );
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "STUDENT" } });

    fireEvent.click(screen.getByRole("button", { name: "Sign up with Microsoft" }));

    await waitFor(() => {
      expect(doubles.post).toHaveBeenCalledWith("/auth/microsoft-signup", {
        idToken: "synthetic-microsoft-id-token",
        role: "STUDENT",
      });
    });
    expect(JSON.stringify(doubles.post.mock.calls)).not.toContain("raw-profile-must-not-be-sent");
  });
});
