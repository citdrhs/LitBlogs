export const localPasswordRegistrationEnabledFor = (env = {}) => {
  const mode = String(env.MODE || "").trim().toLowerCase();
  return (
    env.PROD !== true
    && (mode === "development" || mode === "test")
    && env.VITE_LOCAL_PASSWORD_REGISTRATION_ENABLED === "true"
  );
};

export let localPasswordRegistrationEnabled = localPasswordRegistrationEnabledFor(
  import.meta.env,
);

export const applyPublicRegistrationConfig = (runtimeConfig, env = import.meta.env) => {
  const mode = String(env.MODE || "").trim().toLowerCase();
  const productionBuild = env.PROD === true && mode === "production";
  localPasswordRegistrationEnabled = (
    runtimeConfig?.localPasswordRegistrationEnabled === true
    && (productionBuild || localPasswordRegistrationEnabledFor(env))
  );
  return localPasswordRegistrationEnabled;
};
