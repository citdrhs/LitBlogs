export const PRIVATE_DRAFT_MEMORY_CLEAR_EVENT = "litblogs:clear-private-draft-memory";

export const requestPrivateDraftMemoryClear = () => {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(PRIVATE_DRAFT_MEMORY_CLEAR_EVENT));
  }
};
