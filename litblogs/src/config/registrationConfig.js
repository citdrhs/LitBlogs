export const localPasswordRegistrationEnabledFor = (env = {}) => {
  const mode = String(env.MODE || "").trim().toLowerCase();
  return (
    env.PROD !== true
    && (mode === "development" || mode === "test")
    && env.VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED === "true"
  );
};

export const localPasswordRegistrationEnabled = localPasswordRegistrationEnabledFor(
  import.meta.env,
);
