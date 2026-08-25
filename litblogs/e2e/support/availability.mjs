export const requiresAvailableEnvironment = (environment = process.env) => (
  Boolean(environment.CI) || environment.E2E_REQUIRE_AVAILABLE === 'true'
);
