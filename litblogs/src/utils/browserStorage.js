import { APP_BASE_PATH } from "./urlUtils.js";

// Storage is shared by every app on an origin. A subpath installation owns
// only its namespaced keys; generic legacy keys may belong to a sibling app.
export const storageKey = (key) => APP_BASE_PATH ? `litblogs:${APP_BASE_PATH}:${key}` : key;
