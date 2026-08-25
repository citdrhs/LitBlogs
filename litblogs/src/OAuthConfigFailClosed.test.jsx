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
  useMsal: () => ({ instance: { loginPopup: vi.fn() } }),
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

beforeAll(async () => {
  vi.stubEnv("VITE_GOOGLE_CLIENT_ID", "replace-with-google-client-id");
  vi.stubEnv("VITE_MICROSOFT_CLIENT_ID", "replace-with-microsoft-client-id");
  vi.stubEnv("VITE_MICROSOFT_TENANT_ID", "common");
  window.matchMedia = vi.fn().mockReturnValue({ matches: false });
  ({ default: SignIn } = await import("./Sign-in.jsx"));
});

afterAll(() => {
  vi.unstubAllEnvs();
});

it("does not render provider controls when public provider configuration is invalid", () => {
  render(
    <MemoryRouter>
      <SignIn />
    </MemoryRouter>,
  );

  expect(screen.queryByRole("button", { name: "Unsafe Google flow" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Sign in with Microsoft" })).not.toBeInTheDocument();
});
