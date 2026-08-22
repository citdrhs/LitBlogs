const emptyPostContent = () => ({
  text: "",
  media: [],
  expandableLists: [],
  codeSnippets: [],
  files: [],
});

const cloneItems = (items) => (
  Array.isArray(items) ? items.map((item) => ({ ...item })) : []
);

export const clonePrivatePostContent = (value) => {
  if (!value || typeof value !== "object") {
    return emptyPostContent();
  }

  return {
    text: typeof value.text === "string" ? value.text : "",
    media: cloneItems(value.media),
    expandableLists: cloneItems(value.expandableLists),
    codeSnippets: cloneItems(value.codeSnippets),
    files: cloneItems(value.files),
  };
};

const normalizeAssignmentDraft = (payload = {}) => ({
  hasDraft: Boolean(payload.has_draft),
  content: payload.has_draft && typeof payload.content === "string"
    ? payload.content
    : "",
  savedAt: payload.has_draft ? (payload.saved_at || null) : null,
  revision: Number.isSafeInteger(payload.revision) && payload.revision >= 0
    ? payload.revision
    : 0,
});

const assertDraftRevision = (revision) => {
  if (
    !Number.isSafeInteger(revision)
    || revision < 0
    || revision > 2_147_483_646
  ) {
    throw new TypeError("A bounded assignment draft revision is required");
  }
};

const assignmentDraftEndpoint = (assignmentId) => {
  const normalizedId = String(assignmentId ?? "");
  if (!/^\d+$/.test(normalizedId)) {
    throw new TypeError("A numeric assignment id is required");
  }
  return `/assignments/${normalizedId}/draft`;
};

export const loadAssignmentDraft = async (httpClient, assignmentId) => {
  const response = await httpClient.get(assignmentDraftEndpoint(assignmentId));
  return normalizeAssignmentDraft(response.data);
};

export const saveAssignmentDraft = async (
  httpClient,
  assignmentId,
  content,
  expectedRevision,
  requestConfig,
) => {
  assertDraftRevision(expectedRevision);
  const request = [
    assignmentDraftEndpoint(assignmentId),
    {
      content: typeof content === "string" ? content : "",
      expected_revision: expectedRevision,
    },
  ];
  if (requestConfig) request.push(requestConfig);

  const response = await httpClient.put(
    ...request,
  );
  return normalizeAssignmentDraft(response.data);
};

export const submitAssignment = async (
  httpClient,
  assignmentId,
  content,
  expectedDraftRevision,
  requestConfig,
) => {
  assertDraftRevision(expectedDraftRevision);
  const request = [
    assignmentDraftEndpoint(assignmentId).replace(/\/draft$/, "/submit"),
    {
      content: typeof content === "string" ? content : "",
      expected_draft_revision: expectedDraftRevision,
    },
  ];
  if (requestConfig) request.push(requestConfig);
  const response = await httpClient.post(...request);
  return response.data;
};

const postDraftScope = (editingPostId) => (
  editingPostId === null || editingPostId === undefined
    ? "new"
    : `edit:${editingPostId}`
);

const postDraftKey = ({ classId, userId, editingPostId }) => {
  if (classId === null || classId === undefined || !userId) {
    return null;
  }
  return `${userId}:${classId}:${postDraftScope(editingPostId)}`;
};

const hasMeaningfulPostDraft = (payload = {}) => Boolean(
  payload.postTitle?.trim()
  || payload.content?.trim()
  || payload.postContent?.text?.trim()
  || (payload.postContent?.media?.length || 0) > 0
  || (payload.postContent?.files?.length || 0) > 0
  || (payload.postContent?.expandableLists?.length || 0) > 0
  || (payload.postContent?.codeSnippets?.length || 0) > 0
);

export const findPostDraft = (drafts, context) => {
  const key = postDraftKey(context);
  if (!key) return null;
  return (drafts || []).find((draft) => draft.key === key) || null;
};

export const removePostDraft = (drafts, context) => {
  const key = postDraftKey(context);
  if (!key) return [...(drafts || [])];
  return (drafts || []).filter((draft) => draft.key !== key);
};

export const upsertPostDraft = (
  drafts,
  { classId, userId, editingPostId, payload = {}, savedAt = null },
) => {
  const context = { classId, userId, editingPostId };
  const key = postDraftKey(context);
  if (!key || !hasMeaningfulPostDraft(payload)) {
    return {
      drafts: removePostDraft(drafts, context),
      savedAt: null,
    };
  }

  const nextSavedAt = savedAt || new Date().toISOString();
  const draft = {
    key,
    userId: String(userId),
    classId: String(classId),
    scope: postDraftScope(editingPostId),
    editingPostId: editingPostId ?? null,
    postTitle: payload.postTitle || "",
    content: payload.content || "",
    postContent: clonePrivatePostContent(payload.postContent),
    savedAt: nextSavedAt,
  };

  const nextDrafts = removePostDraft(drafts, context);
  nextDrafts.push(draft);
  nextDrafts.sort((left, right) => (
    new Date(right.savedAt).getTime() - new Date(left.savedAt).getTime()
  ));

  return { drafts: nextDrafts, savedAt: nextSavedAt };
};
