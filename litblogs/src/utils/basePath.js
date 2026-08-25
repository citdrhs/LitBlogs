export const normalizeViteBasePath = (value = "/") => {
  const normalizedValue = typeof value === "string" ? value.trim() : "";
  const pathSegments = normalizedValue.split("/").filter(Boolean);

  return pathSegments.length === 0 ? "/" : `/${pathSegments.join("/")}/`;
};

export const normalizeRuntimeBasePath = (value = "/") => {
  const viteBasePath = normalizeViteBasePath(value);
  return viteBasePath === "/" ? "" : viteBasePath.slice(0, -1);
};
