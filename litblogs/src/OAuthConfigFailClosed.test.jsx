import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterAll, beforeAll, expect, it, vi } from "vitest";

vi.mock("axios", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}));

vi.mock("@azure/msal-react", () => ({
  useMsal: () => {
    throw new Error("Disabled Microsoft provider must not invoke useMsal");
  },
}));

vi.mock("@react-oauth/google", () => ({
  GoogleLogin: () => <button type="button">Unsafe Google flow</button>,
}));

vi.mock("./utils/auth", () => ({
  fetchBrowserSession: vi.fn(),
  persistSessionMetadata: vi.fn(),
}));

vi.mock("./utils/userSettings", () => ({
  applyGlobalUserSettings: vi.fn(),
  saveLocalUserSettings: vi.fn(() => ({ darkMode: false })),
}));

let SignIn;
let SignUp;

beforeAll(async () => {
  vi.stubEnv("VITE_GOOGLE_OAUTH_ENABLED", "false");
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "987654321.apps.googleusercontent.com");
  vi.stubEnv("VITE_MICROSOFT_OAUTH_ENABLED", "false");
  vi.stubEnv("VITE_MICROSOFT_CLIENT_ID", "2f1c67a1-91e2-46a3-941f-b88e31763e51");
  vi.stubEnv("VITE_MICROSOFT_TENANT_ID", "871bd3e0-2dc0-4a40-9b07-9d03068c2364");
  window.matchMedia = vi.fn().mockReturnValue({ matches: false });
  ({ default: SignIn } = await import("./Sign-in.jsx"));
  ({ default: SignUp } = await import("./Sign-up.jsx"));
});

afterAll(() => {
  vi.unstubAllEnvs();
});

it("keeps password sign-in and resend help while disabled providers ignore stale valid IDs", () => {
  render(
    <MemoryRouter>
      <SignIn />
    </MemoryRouter>,
  );

  expect(screen.queryByRole("button", { name: "Unsafe Google flow" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sign in with Microsoft" })).not.toBeInTheDocument();
  expect(screen.getByLabelText("Password")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Sign In" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /request another verification email/i })).toHaveAttribute(
    "href",
    "/verify-email?resend=1",
  );
});

it("does not invoke Microsoft hooks or show OAuth controls on password signup", () => {
  render(
    <MemoryRouter>
      <SignUp localPasswordRegistrationEnabled />
    </MemoryRouter>,
  );

  expect(screen.getByLabelText("Password")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Unsafe Google flow" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sign up with Microsoft" })).not.toBeInTheDocument();
});
