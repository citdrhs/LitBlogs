import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  findPostDraft,
  removePostDraft as removePostDraftFromCollection,
  upsertPostDraft,
} from "../utils/privateDrafts.js";
import {
  PRIVATE_DRAFT_MEMORY_CLEAR_EVENT,
} from "../utils/privateDraftMemory.js";


const PrivateDraftContext = createContext(null);

const normalizedContextPart = (value) => {
  if (value === null || value === undefined || value === "") return null;
  return String(value);
};

const assignmentDraftKey = ({ userId, classId, assignmentId } = {}) => {
  const parts = [userId, classId, assignmentId].map(normalizedContextPart);
  return parts.includes(null) ? null : JSON.stringify(parts);
};

const normalizeAssignmentMemory = (snapshot = {}) => ({
  content: typeof snapshot.content === "string" ? snapshot.content : "",
  revision: Number.isSafeInteger(snapshot.revision) && snapshot.revision >= 0
    ? snapshot.revision
    : 0,
  savedAt: snapshot.savedAt || null,
  dirty: Boolean(snapshot.dirty),
  status: typeof snapshot.status === "string" ? snapshot.status : "idle",
});

const isRiskyAssignmentMemory = (memory) => (
  memory.dirty || ["pending", "saving"].includes(memory.status)
);

export const PrivateDraftProvider = ({ children }) => {
  const postDraftsRef = useRef([]);
  const assignmentDraftsRef = useRef(new Map());
  const [postDrafts, setPostDrafts] = useState([]);
  const [assignmentVersion, setAssignmentVersion] = useState(0);

  const savePostDraft = useCallback((draft) => {
    const result = upsertPostDraft(postDraftsRef.current, draft);
    postDraftsRef.current = result.drafts;
    setPostDrafts(result.drafts);
    return result;
  }, []);

  const getPostDraft = useCallback((context) => (
    findPostDraft(postDraftsRef.current, context)
  ), []);

  const removePostDraft = useCallback((context) => {
    const nextDrafts = removePostDraftFromCollection(postDraftsRef.current, context);
    postDraftsRef.current = nextDrafts;
    setPostDrafts(nextDrafts);
    return nextDrafts;
  }, []);

  const saveAssignmentMemory = useCallback((context, snapshot) => {
    const key = assignmentDraftKey(context);
    if (!key) return null;
    const memory = normalizeAssignmentMemory(snapshot);
    assignmentDraftsRef.current.set(key, {
      userId: normalizedContextPart(context.userId),
      memory,
    });
    setAssignmentVersion((version) => version + 1);
    return memory;
  }, []);

  const getAssignmentMemory = useCallback((context) => {
    const key = assignmentDraftKey(context);
    return key ? assignmentDraftsRef.current.get(key)?.memory || null : null;
  }, []);

  const removeAssignmentMemory = useCallback((context) => {
    const key = assignmentDraftKey(context);
    if (!key) return false;
    const removed = assignmentDraftsRef.current.delete(key);
    if (removed) setAssignmentVersion((version) => version + 1);
    return removed;
  }, []);

  const clearPrivateDraftMemory = useCallback(() => {
    postDraftsRef.current = [];
    assignmentDraftsRef.current.clear();
    setPostDrafts([]);
    setAssignmentVersion((version) => version + 1);
  }, []);

  const hasRiskyDrafts = useCallback(({ userId } = {}) => {
    const normalizedUserId = normalizedContextPart(userId);
    const hasPost = postDraftsRef.current.some((draft) => (
      normalizedUserId === null || String(draft.userId) === normalizedUserId
    ));
    if (hasPost) return true;

    return Array.from(assignmentDraftsRef.current.values()).some((entry) => (
      (normalizedUserId === null || entry.userId === normalizedUserId)
      && isRiskyAssignmentMemory(entry.memory)
    ));
  }, []);

  useEffect(() => {
    window.addEventListener(
      PRIVATE_DRAFT_MEMORY_CLEAR_EVENT,
      clearPrivateDraftMemory,
    );
    return () => window.removeEventListener(
      PRIVATE_DRAFT_MEMORY_CLEAR_EVENT,
      clearPrivateDraftMemory,
    );
  }, [clearPrivateDraftMemory]);

  const value = useMemo(() => ({
    assignmentVersion,
    postDrafts,
    savePostDraft,
    getPostDraft,
    removePostDraft,
    saveAssignmentMemory,
    getAssignmentMemory,
    removeAssignmentMemory,
    clearPrivateDraftMemory,
    hasRiskyDrafts,
  }), [
    assignmentVersion,
    postDrafts,
    savePostDraft,
    getPostDraft,
    removePostDraft,
    saveAssignmentMemory,
    getAssignmentMemory,
    removeAssignmentMemory,
    clearPrivateDraftMemory,
    hasRiskyDrafts,
  ]);

  return (
    <PrivateDraftContext.Provider value={value}>
      {children}
    </PrivateDraftContext.Provider>
  );
};

// This hook intentionally shares the provider module so consumers cannot
// import a mismatched context instance during code splitting.
// eslint-disable-next-line react-refresh/only-export-components
export const usePrivateDrafts = () => {
  const drafts = useContext(PrivateDraftContext);
  if (!drafts) {
    throw new Error("usePrivateDrafts must be used inside PrivateDraftProvider");
  }
  return drafts;
};
