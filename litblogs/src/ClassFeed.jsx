import { lazy, Suspense, useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import axios from 'axios';
import Prism from 'prismjs';
import 'prismjs/themes/prism-tomorrow.css';
import 'prismjs/components/prism-core';
import 'prismjs/components/prism-clike';
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-markup';
import 'prismjs/components/prism-css';
import 'prismjs/components/prism-sql';
import Loader from './components/Loader';
import Navbar from "./components/Navbar";
import Footer from "./components/Footer";
import './LitBlogs.css';
import { toast } from 'react-hot-toast';
import { IoMdHeart, IoMdHeartEmpty } from 'react-icons/io';
import CommentThread from './components/CommentThread';
import { formatRelativeTime, setupTimeUpdater } from './utils/timeUtils';
import { mediaPath } from './utils/urlUtils';
import { logoutBrowserSession } from './utils/auth';
import {
  buildPostRequestPayload,
  MAX_POST_HTML_LENGTH,
} from './utils/postRequestContract';
import RichTextContent from './components/RichTextContent';
import {
  clonePrivatePostContent,
  loadAssignmentDraft,
  saveAssignmentDraft,
  submitAssignment,
} from './utils/privateDrafts';
import { usePrivateDrafts } from './context/PrivateDraftContext';
import { sanitizeRichText } from './utils/richTextSecurity';
import {
  applyGlobalUserSettings,
  getEditorFontSizePx,
  getLocalUserSettings,
  normalizeUserSettings,
  saveLocalUserSettings,
} from './utils/userSettings';

const LitBlogsEditor = lazy(() => import('./components/LitBlogsEditor'));

const DIALOG_FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[contenteditable="true"]',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const containDialogFocus = (event, dialog) => {
  if (event.key !== 'Tab' || !dialog) return;
  const focusable = [...dialog.querySelectorAll(DIALOG_FOCUSABLE_SELECTOR)]
    .filter((element) => !element.hidden && element.getAttribute('aria-hidden') !== 'true');
  if (!focusable.length) {
    event.preventDefault();
    dialog.focus();
    return;
  }

  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
};

// Add this after your imports
Prism.manual = true;

const createEmptyPostContent = () => ({
  text: "",
  media: [],
  expandableLists: [],
  codeSnippets: [],
  files: []
});

const normalizePostContentForEditor = (content = '') => {
  return sanitizeRichText(content, { mode: 'editor' });
};

const MediaPreview = ({ media, files, onRemove }) => {
  return (
    <div className="space-y-4 mt-4">
      {/* GIFs and Images */}
      <div className="flex flex-wrap gap-4">
        {media.map((item, index) => (
          <div key={index} className="relative group">
            <img 
              src={item.url} 
              alt={item.alt} 
              className="h-32 w-32 object-cover rounded-lg"
            />
            <button
              type="button"
              onClick={() => onRemove('media', index)}
              className="absolute top-2 right-2 bg-red-500 text-white rounded-full p-1 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        ))}
      </div>

      {/* Files */}
      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((file, index) => (
            <div key={index} className="flex items-center justify-between p-2 bg-gray-50 rounded-lg">
              <div className="flex items-center gap-2">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span>{file.name}</span>
              </div>
              <button
                type="button"
                onClick={() => onRemove('files', index)}
                className="text-red-500 hover:text-red-600"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

const ClassFeed = () => {
  // Move all useState hooks to the top
  const { classId } = useParams();
  const navigate = useNavigate();
  const [userInfo, setUserInfo] = useState(null);
  const [classDetails, setClassDetails] = useState(null);
  const [posts, setPosts] = useState([]);
  const [, setPostsLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [darkMode] = useState(() => {
    return JSON.parse(localStorage.getItem('darkMode')) ?? false;
  });
  const [showNewPostForm, setShowNewPostForm] = useState(false);
  const [postTitle, setPostTitle] = useState("");
  const [content, setContent] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [postContent, setPostContent] = useState(createEmptyPostContent);
  const [activeCategory, setActiveCategory] = useState('all');
  const [editingPostId, setEditingPostId] = useState(null);
  const [menuOpen, setMenuOpen] = useState(null);
  const [likedPosts, setLikedPosts] = useState({});
  const [likesLoading, setLikesLoading] = useState({});
  const [savedPosts, setSavedPosts] = useState({});
  const [saveLoading, setSaveLoading] = useState({});
  const [likeEffects, setLikeEffects] = useState({});
  const [postCommentsVisible, setPostCommentsVisible] = useState({});
  const [postComments, setPostComments] = useState({});
  const [commentLoading, setCommentLoading] = useState({});
  const [newCommentText, setNewCommentText] = useState({});
  const [commentCounts, setCommentCounts] = useState({});
  const [assignments, setAssignments] = useState([]);
  const [assignmentsLoading, setAssignmentsLoading] = useState(false);
  const [showAssignmentModal, setShowAssignmentModal] = useState(false);
  const [activeAssignment, setActiveAssignment] = useState(null);
  const [assignmentSubmission, setAssignmentSubmission] = useState('');
  const [assignmentDraftSavedAt, setAssignmentDraftSavedAt] = useState(null);
  const [assignmentDraftReady, setAssignmentDraftReady] = useState(false);
  const [assignmentDraftStatus, setAssignmentDraftStatus] = useState('idle');
  const [assignmentDraftDirty, setAssignmentDraftDirty] = useState(false);
  const [assignmentDraftRevision, setAssignmentDraftRevision] = useState(0);
  const [assignmentDraftClosing, setAssignmentDraftClosing] = useState(false);
  const [assignmentSubmitting, setAssignmentSubmitting] = useState(false);
  const [postDraftSavedAt, setPostDraftSavedAt] = useState(null);
  const [postComposerDirty, setPostComposerDirty] = useState(false);
  const [editorUploadBusy, setEditorUploadBusy] = useState(false);
  const [postHtmlLength, setPostHtmlLength] = useState(0);
  const postComposerDialogRef = useRef(null);
  const postComposerReturnFocusRef = useRef(null);
  const postComposerWasOpenRef = useRef(false);
  const assignmentDraftRequestRef = useRef(0);
  const assignmentDraftAbortRef = useRef(null);
  const assignmentDraftStatusRef = useRef('idle');
  const latestAssignmentContextRef = useRef(null);
  const previousDraftContextRef = useRef(null);
  const latestPostComposerRef = useRef(null);
  const [userSettings, setUserSettings] = useState(() => getLocalUserSettings());
  const {
    postDrafts,
    savePostDraft: savePostDraftMemory,
    getPostDraft,
    removePostDraft: removePostDraftMemory,
    saveAssignmentMemory,
    getAssignmentMemory,
    removeAssignmentMemory,
    clearPrivateDraftMemory,
    hasRiskyDrafts,
  } = usePrivateDrafts();
  const normalizedRole = (userInfo?.role || '').toString().toUpperCase();
  const isStudent = normalizedRole === 'STUDENT';
  const canReviewSubmissions = ['TEACHER', 'ADMIN'].includes(normalizedRole);
  const activeAssignmentId = activeAssignment?.id;
  const assignmentDraftUserId = userInfo?.userId || userInfo?.id;
  const postDraftUserId = userInfo?.userId || userInfo?.id;
  const activeAssignmentMemoryContext = activeAssignmentId && assignmentDraftUserId
    ? {
        userId: assignmentDraftUserId,
        classId,
        assignmentId: activeAssignmentId,
      }
    : null;
  const rememberDraftsEnabled = userSettings.rememberDrafts !== false;
  const editorFontSizePx = getEditorFontSizePx(userSettings.editorFontSize);
  assignmentDraftStatusRef.current = assignmentDraftStatus;
  latestPostComposerRef.current = {
    showNewPostForm,
    postComposerDirty,
    classId,
    userId: postDraftUserId,
    editingPostId,
    postTitle,
    content,
    postContent,
  };
  latestAssignmentContextRef.current = {
    classId: String(classId ?? ''),
    userId: String(assignmentDraftUserId ?? ''),
    assignmentId: activeAssignmentId === null || activeAssignmentId === undefined
      ? null
      : String(activeAssignmentId),
  };

  useEffect(() => {
    if (showNewPostForm) {
      postComposerWasOpenRef.current = true;
      return;
    }
    if (!postComposerWasOpenRef.current) return;

    postComposerWasOpenRef.current = false;
    const returnTarget = postComposerReturnFocusRef.current;
    postComposerReturnFocusRef.current = null;
    const returnElement = returnTarget?.element?.isConnected
      ? returnTarget.element
      : returnTarget?.fallbackSelector
      ? document.querySelector(returnTarget.fallbackSelector)
      : null;
    if (returnElement && typeof returnElement.focus === 'function') {
      returnElement.focus();
    }
  }, [showNewPostForm]);

  // Move all useEffect hooks together
  useEffect(() => {
    // Load user info
    const storedUserInfo = sessionStorage.getItem('user_info');
    if (storedUserInfo) {
      setUserInfo(JSON.parse(storedUserInfo));
    }

    const fetchData = async () => {
      try {
        try {
          const settingsResponse = await axios.get('/user/settings');
          const normalizedSettings = normalizeUserSettings(settingsResponse.data, userInfo?.role);
          saveLocalUserSettings(normalizedSettings, userInfo?.role);
          applyGlobalUserSettings(normalizedSettings);
          setUserSettings(normalizedSettings);
        } catch {
          const localSettings = getLocalUserSettings(userInfo?.role);
          applyGlobalUserSettings(localSettings);
          setUserSettings(localSettings);
        }

        // Use the correct endpoint
        const classResponse = await axios.get(`/classes/${classId}/details`);
        setClassDetails(classResponse.data);

        // Get class posts using the posts endpoint
        const postsResponse = await axios.get(`/classes/${classId}/posts`);
        setPosts(postsResponse.data);
        const savedInfo = {};
        (postsResponse.data || []).forEach((post) => {
          savedInfo[post.id] = Boolean(post.is_saved);
        });
        setSavedPosts(savedInfo);

        setAssignmentsLoading(true);
        const assignmentsResponse = await axios.get(`/classes/${classId}/assignments`);
        setAssignments(assignmentsResponse.data || []);
        setAssignmentsLoading(false);

        setLoading(false);
      } catch (error) {
        console.error('Error fetching class data:', error);
        setError(error.response?.data?.detail || 'Failed to load class data');
        setLoading(false);
        setAssignmentsLoading(false);
        if (error.response?.status === 401) {
          navigate('/sign-in');
        }
      }
    };

    fetchData();
  }, [classId, navigate]);

  useEffect(() => {
    if (
      !isStudent
      || !activeAssignmentId
      || !assignmentDraftUserId
      || !assignmentDraftReady
      || !assignmentDraftDirty
      || !rememberDraftsEnabled
      || assignmentSubmitting
      || assignmentDraftClosing
      || assignmentDraftStatusRef.current === 'error'
    ) {
      return;
    }

    const requestVersion = ++assignmentDraftRequestRef.current;
    const expectedRevision = assignmentDraftRevision;
    const abortController = new AbortController();
    assignmentDraftAbortRef.current?.abort();
    assignmentDraftAbortRef.current = abortController;
    setAssignmentDraftStatus('pending');
    saveAssignmentMemory(
      {
        userId: assignmentDraftUserId,
        classId,
        assignmentId: activeAssignmentId,
      },
      {
        content: assignmentSubmission,
        revision: expectedRevision,
        savedAt: assignmentDraftSavedAt,
        dirty: true,
        status: 'pending',
      },
    );

    const autosaveTimer = setTimeout(() => {
      const syncDraft = async () => {
        setAssignmentDraftStatus('saving');
        saveAssignmentMemory(
          {
            userId: assignmentDraftUserId,
            classId,
            assignmentId: activeAssignmentId,
          },
          {
            content: assignmentSubmission,
            revision: expectedRevision,
            savedAt: assignmentDraftSavedAt,
            dirty: true,
            status: 'saving',
          },
        );
        try {
          const serverDraft = await saveAssignmentDraft(
            axios,
            activeAssignmentId,
            assignmentSubmission,
            expectedRevision,
            { signal: abortController.signal },
          );

          if (requestVersion !== assignmentDraftRequestRef.current) return;

          setAssignmentDraftSavedAt(serverDraft.savedAt);
          setAssignmentDraftRevision(serverDraft.revision);
          setAssignmentDraftStatus('saved');
          setAssignmentDraftDirty(false);
          saveAssignmentMemory(
            {
              userId: assignmentDraftUserId,
              classId,
              assignmentId: activeAssignmentId,
            },
            {
              content: serverDraft.content,
              revision: serverDraft.revision,
              savedAt: serverDraft.savedAt,
              dirty: false,
              status: 'saved',
            },
          );
          const nextDraft = serverDraft.hasDraft
            ? {
                content: serverDraft.content,
                updated_at: serverDraft.savedAt,
                revision: serverDraft.revision,
              }
            : null;
          setAssignments((prev) => prev.map((assignment) => (
            assignment.id === activeAssignmentId
              ? {
                  ...assignment,
                  my_draft: nextDraft,
                  my_draft_revision: serverDraft.revision,
                }
              : assignment
          )));
          setActiveAssignment((prev) => (
            prev && prev.id === activeAssignmentId
              ? {
                  ...prev,
                  my_draft: nextDraft,
                  my_draft_revision: serverDraft.revision,
                }
              : prev
          ));
        } catch (error) {
          const wasCanceled = error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError';
          if (!wasCanceled && requestVersion === assignmentDraftRequestRef.current) {
            setAssignmentDraftStatus('error');
            saveAssignmentMemory(
              {
                userId: assignmentDraftUserId,
                classId,
                assignmentId: activeAssignmentId,
              },
              {
                content: assignmentSubmission,
                revision: expectedRevision,
                savedAt: assignmentDraftSavedAt,
                dirty: true,
                status: 'error',
              },
            );
          }
        } finally {
          if (assignmentDraftAbortRef.current === abortController) {
            assignmentDraftAbortRef.current = null;
          }
        }
      };

      syncDraft();
    }, 500);

    return () => {
      clearTimeout(autosaveTimer);
      abortController.abort();
    };
  }, [
    assignmentSubmission,
    activeAssignmentId,
    assignmentDraftReady,
    assignmentDraftDirty,
    assignmentDraftUserId,
    isStudent,
    rememberDraftsEnabled,
    assignmentSubmitting,
    assignmentDraftClosing,
    assignmentDraftRevision,
    assignmentDraftSavedAt,
    classId,
    saveAssignmentMemory,
  ]);

  useEffect(() => {
    if (
      !showNewPostForm
      || !postDraftUserId
      || !rememberDraftsEnabled
      || !postComposerDirty
    ) {
      return;
    }

    const autosaveTimer = setTimeout(() => {
      const result = savePostDraftMemory({
        classId,
        userId: postDraftUserId,
        editingPostId,
        payload: {
          postTitle,
          content,
          postContent,
        },
      });
      setPostDraftSavedAt(result.savedAt);
      setPostComposerDirty(false);
    }, 500);

    return () => clearTimeout(autosaveTimer);
  }, [
    showNewPostForm,
    postDraftUserId,
    rememberDraftsEnabled,
    postComposerDirty,
    classId,
    editingPostId,
    postTitle,
    content,
    postContent,
    savePostDraftMemory,
  ]);

  useEffect(() => () => {
    const snapshot = latestPostComposerRef.current;
    if (!snapshot?.showNewPostForm || !snapshot.postComposerDirty || !snapshot.userId) {
      return;
    }
    savePostDraftMemory({
      classId: snapshot.classId,
      userId: snapshot.userId,
      editingPostId: snapshot.editingPostId,
      payload: {
        postTitle: snapshot.postTitle,
        content: snapshot.content,
        postContent: snapshot.postContent,
      },
    });
  }, [savePostDraftMemory]);

  useEffect(() => {
    const currentContext = {
      classId: String(classId ?? ''),
      userId: String(postDraftUserId ?? ''),
    };
    const previousContext = previousDraftContextRef.current;
    const snapshot = latestPostComposerRef.current;

    if (
      previousContext
      && (
        previousContext.classId !== currentContext.classId
        || previousContext.userId !== currentContext.userId
      )
    ) {
      if (snapshot?.showNewPostForm && snapshot.postComposerDirty && previousContext.userId) {
        savePostDraftMemory({
          classId: previousContext.classId,
          userId: previousContext.userId,
          editingPostId: snapshot.editingPostId,
          payload: {
            postTitle: snapshot.postTitle,
            content: snapshot.content,
            postContent: snapshot.postContent,
          },
        });
      }

      assignmentDraftRequestRef.current += 1;
      assignmentDraftAbortRef.current?.abort();
      assignmentDraftAbortRef.current = null;
      setShowAssignmentModal(false);
      setActiveAssignment(null);
      setAssignmentSubmission('');
      setAssignmentDraftReady(false);
      setAssignmentDraftSavedAt(null);
      setAssignmentDraftStatus('idle');
      setAssignmentDraftDirty(false);
      setAssignmentDraftRevision(0);
      setAssignmentDraftClosing(false);
      setAssignmentSubmitting(false);
      setShowNewPostForm(false);
      setPostTitle('');
      setContent('');
      setPostContent(createEmptyPostContent());
      setPostDraftSavedAt(null);
      setPostComposerDirty(false);
      setEditingPostId(null);
    }

    previousDraftContextRef.current = currentContext;
  }, [classId, postDraftUserId, savePostDraftMemory]);

  useEffect(() => {
    const hasCurrentRisk = (
      postComposerDirty
      || assignmentDraftDirty
      || ['pending', 'saving'].includes(assignmentDraftStatus)
      || hasRiskyDrafts({ userId: postDraftUserId })
    );
    if (!hasCurrentRisk) return undefined;

    const protectRefresh = (event) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', protectRefresh);
    return () => window.removeEventListener('beforeunload', protectRefresh);
  }, [
    assignmentDraftDirty,
    assignmentDraftStatus,
    hasRiskyDrafts,
    postComposerDirty,
    postDraftUserId,
    postDrafts,
  ]);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
    localStorage.setItem('darkMode', JSON.stringify(darkMode));
  }, [darkMode]);

  useEffect(() => {
    if (postContent.codeSnippets.length > 0) {
      setTimeout(() => {
        Prism.highlightAll();
      }, 0);
    }
  }, [postContent.codeSnippets]);

  useEffect(() => {
    const autoPlayEnabled = userSettings.autoPlayVideos === true;
    const videos = document.querySelectorAll('.html-content video');
    videos.forEach((video) => {
      video.autoplay = autoPlayEnabled;
      video.loop = autoPlayEnabled;
      video.muted = autoPlayEnabled;
      if (autoPlayEnabled) {
        video.setAttribute('playsinline', 'true');
      }
    });
  }, [posts, userSettings.autoPlayVideos]);

  useEffect(() => {
    if (!isStudent || !userSettings.emailNotifications || !userSettings.assignmentReminders) {
      return;
    }

    const nowMs = Date.now();
    const dueSoonWindowMs = 24 * 60 * 60 * 1000;
    const studentId = userInfo?.userId || userInfo?.id;

    assignments.forEach((assignment) => {
      const dueMs = new Date(assignment.due_date).getTime();
      const isDueSoon = dueMs > nowMs && dueMs - nowMs <= dueSoonWindowMs;
      const hasSubmitted = Boolean(assignment.my_submission);
      if (!isDueSoon || hasSubmitted) {
        return;
      }

      const reminderKey = `assignment-reminder:${studentId}:${assignment.id}`;
      if (localStorage.getItem(reminderKey)) {
        return;
      }

      toast(`Reminder: ${assignment.title} is due within 24 hours.`, {
        icon: '⏰',
      });
      localStorage.setItem(reminderKey, new Date().toISOString());
    });
  }, [assignments, isStudent, userInfo?.id, userInfo?.userId, userSettings.assignmentReminders, userSettings.emailNotifications]);

  useEffect(() => {
    // Get likes for all posts on initial load
    const fetchLikes = async () => {
      if (!posts.length || !classId) return;
      
      const likesInfo = {};
      
      for (const post of posts) {
        try {
          const response = await axios.get(`/classes/${classId}/posts/${post.id}/likes`);
          
          likesInfo[post.id] = {
            count: response.data.like_count,
            userLiked: response.data.user_liked
          };
        } catch (error) {
          console.error(`Error fetching likes for post ${post.id}:`, error);
        }
      }
      
      setLikedPosts(likesInfo);
    };
    
    fetchLikes();
  }, [posts, classId]);

  useEffect(() => {
    // Modify the existing useEffect that fetches posts
    const fetchPostsAndCounts = async () => {
      if (!classId) return;
      
      setPostsLoading(true);
      
      try {
        // Fetch the posts
        const response = await axios.get(`/classes/${classId}/posts`);
        
        setPosts(response.data);
        const savedInfo = {};
        (response.data || []).forEach((post) => {
          savedInfo[post.id] = Boolean(post.is_saved);
        });
        setSavedPosts(savedInfo);
        
        // Fetch comment counts immediately after posts load
        const counts = {};
        
        // We'll fetch one by one to ensure reliability
        for (const post of response.data) {
          try {
            const commentResponse = await axios.get(
              `/classes/${classId}/posts/${post.id}/comments?limit=1`
            );
            counts[post.id] = commentResponse.data.total;
          } catch (err) {
            console.error(`Failed to fetch comments for post ${post.id}:`, err);
            counts[post.id] = 0;
          }
        }
        
        // Update comment counts
        setCommentCounts(counts);
      } catch (error) {
        console.error("Error fetching posts:", error);
        setError('Failed to load posts');
      } finally {
        setPostsLoading(false);
      }
    };
    
    fetchPostsAndCounts();
  }, [classId]);

  useEffect(() => {
    // Set up the time updater when the component mounts
    const timeUpdateInterval = setupTimeUpdater();
    
    // Clean up the interval when the component unmounts
    return () => clearInterval(timeUpdateInterval);
  }, []);

  const updateAssignmentDraftState = (assignmentId, draft, revision = 0) => {
    setAssignments((prev) => prev.map((assignment) => (
      assignment.id === assignmentId
        ? { ...assignment, my_draft: draft, my_draft_revision: revision }
        : assignment
    )));
    setActiveAssignment((prev) => (
      prev && prev.id === assignmentId
        ? { ...prev, my_draft: draft, my_draft_revision: revision }
        : prev
    ));
  };

  const handleAssignmentSubmissionChange = (event) => {
    const nextContent = event.target.value;
    setAssignmentSubmission(nextContent);
    setAssignmentDraftDirty(true);
    const nextStatus = rememberDraftsEnabled ? 'pending' : 'memory-only';
    setAssignmentDraftStatus(nextStatus);
    if (activeAssignmentMemoryContext) {
      saveAssignmentMemory(activeAssignmentMemoryContext, {
        content: nextContent,
        revision: assignmentDraftRevision,
        savedAt: assignmentDraftSavedAt,
        dirty: true,
        status: nextStatus,
      });
    }
  };

  const assignmentRequestContext = (assignmentId) => ({
    classId: String(classId ?? ''),
    userId: String(assignmentDraftUserId ?? ''),
    assignmentId: String(assignmentId),
  });

  const isCurrentAssignmentClass = (context, requestVersion) => {
    const current = latestAssignmentContextRef.current;
    return (
      requestVersion === assignmentDraftRequestRef.current
      && current?.classId === context.classId
      && current?.userId === context.userId
    );
  };

  const isCurrentAssignmentRequest = (context, requestVersion) => (
    isCurrentAssignmentClass(context, requestVersion)
    && latestAssignmentContextRef.current?.assignmentId === context.assignmentId
  );

  const isCanceledAssignmentRequest = (error) => (
    error?.code === 'ERR_CANCELED'
    || error?.name === 'CanceledError'
    || error?.name === 'AbortError'
  );

  const resetAssignmentModalState = () => {
    setShowAssignmentModal(false);
    setActiveAssignment(null);
    setAssignmentSubmission('');
    setAssignmentDraftReady(false);
    setAssignmentDraftSavedAt(null);
    setAssignmentDraftStatus('idle');
    setAssignmentDraftDirty(false);
    setAssignmentDraftRevision(0);
    setAssignmentDraftClosing(false);
    setAssignmentSubmitting(false);
  };

  const dismissAssignmentModal = () => {
    assignmentDraftRequestRef.current += 1;
    assignmentDraftAbortRef.current?.abort();
    assignmentDraftAbortRef.current = null;
    resetAssignmentModalState();
  };

  const closeAssignmentModal = async () => {
    if (
      !rememberDraftsEnabled
      || !assignmentDraftReady
      || !assignmentDraftDirty
      || !activeAssignmentId
    ) {
      dismissAssignmentModal();
      return;
    }

    assignmentDraftAbortRef.current?.abort();
    const requestVersion = ++assignmentDraftRequestRef.current;
    const requestContext = assignmentRequestContext(activeAssignmentId);
    const abortController = new AbortController();
    assignmentDraftAbortRef.current = abortController;
    setAssignmentDraftClosing(true);
    setAssignmentDraftStatus('saving');
    try {
      const serverDraft = await saveAssignmentDraft(
        axios,
        activeAssignmentId,
        assignmentSubmission,
        assignmentDraftRevision,
        { signal: abortController.signal },
      );
      if (!isCurrentAssignmentRequest(requestContext, requestVersion)) return;

      updateAssignmentDraftState(
        activeAssignmentId,
        serverDraft.hasDraft
          ? {
              content: serverDraft.content,
              updated_at: serverDraft.savedAt,
              revision: serverDraft.revision,
            }
          : null,
        serverDraft.revision,
      );
      removeAssignmentMemory(requestContext);
      resetAssignmentModalState();
    } catch (error) {
      if (
        isCanceledAssignmentRequest(error)
        || !isCurrentAssignmentRequest(requestContext, requestVersion)
      ) {
        return;
      }
      setAssignmentDraftStatus('error');
      saveAssignmentMemory(requestContext, {
        content: assignmentSubmission,
        revision: assignmentDraftRevision,
        savedAt: assignmentDraftSavedAt,
        dirty: true,
        status: 'error',
      });
      toast.error('Could not save your response. Keep this tab open and try again.');
    } finally {
      if (assignmentDraftAbortRef.current === abortController) {
        assignmentDraftAbortRef.current = null;
      }
      if (isCurrentAssignmentRequest(requestContext, requestVersion)) {
        setAssignmentDraftClosing(false);
      }
    }
  };

  const discardUnsavedAssignmentChanges = () => {
    if (!confirm('Discard these unsaved assignment changes? This cannot be undone.')) {
      return;
    }
    if (activeAssignmentMemoryContext) {
      removeAssignmentMemory(activeAssignmentMemoryContext);
    }
    dismissAssignmentModal();
  };

  const openAssignmentModal = async (assignment) => {
    assignmentDraftAbortRef.current?.abort();
    assignmentDraftAbortRef.current = null;
    const requestVersion = ++assignmentDraftRequestRef.current;
    const fallbackContent = assignment.my_draft?.content || assignment.my_submission?.content || '';
    const fallbackSavedAt = assignment.my_draft?.updated_at || null;
    const fallbackRevision = assignment.my_draft?.revision ?? assignment.my_draft_revision ?? 0;
    const memoryContext = {
      userId: assignmentDraftUserId,
      classId,
      assignmentId: assignment.id,
    };
    const remembered = getAssignmentMemory(memoryContext);
    const cleanLoadError = Boolean(
      remembered && !remembered.dirty && remembered.status === 'error'
    );
    const useRememberedWithoutLoad = Boolean(
      remembered
      && (
        remembered.dirty
        || ['pending', 'saving', 'memory-only'].includes(remembered.status)
        || !rememberDraftsEnabled
      )
    );

    setActiveAssignment(assignment);
    setAssignmentSubmission(remembered?.content ?? fallbackContent);
    setAssignmentDraftSavedAt(remembered?.savedAt ?? fallbackSavedAt);
    setAssignmentDraftRevision(remembered?.revision ?? fallbackRevision);
    setShowAssignmentModal(true);
    setAssignmentDraftReady(Boolean(remembered) && !cleanLoadError);
    setAssignmentDraftDirty(Boolean(remembered?.dirty));
    setAssignmentDraftStatus(
      cleanLoadError
        ? 'loading'
        : remembered?.status
      || (rememberDraftsEnabled ? 'loading' : 'memory-only')
    );

    if (useRememberedWithoutLoad) {
      if (remembered.dirty && remembered.status !== 'error') {
        setAssignmentDraftStatus(rememberDraftsEnabled ? 'pending' : 'memory-only');
      }
      return;
    }

    if (!rememberDraftsEnabled) {
      setAssignmentDraftReady(true);
      return;
    }

    try {
      const serverDraft = await loadAssignmentDraft(axios, assignment.id);
      if (requestVersion !== assignmentDraftRequestRef.current) return;

      const recoveredContent = serverDraft.hasDraft
        ? serverDraft.content
        : (assignment.my_submission?.content || '');
      setAssignmentSubmission(recoveredContent);
      setAssignmentDraftSavedAt(serverDraft.savedAt);
      setAssignmentDraftRevision(serverDraft.revision);
      setAssignmentDraftDirty(false);
      setAssignmentDraftStatus(serverDraft.hasDraft ? 'saved' : 'idle');
      saveAssignmentMemory(memoryContext, {
        content: recoveredContent,
        revision: serverDraft.revision,
        savedAt: serverDraft.savedAt,
        dirty: false,
        status: serverDraft.hasDraft ? 'saved' : 'idle',
      });
      updateAssignmentDraftState(
        assignment.id,
        serverDraft.hasDraft
          ? {
              content: serverDraft.content,
              updated_at: serverDraft.savedAt,
              revision: serverDraft.revision,
            }
          : null,
        serverDraft.revision,
      );
    } catch {
      if (requestVersion === assignmentDraftRequestRef.current) {
        setAssignmentDraftStatus('error');
        saveAssignmentMemory(memoryContext, {
          content: fallbackContent,
          revision: fallbackRevision,
          savedAt: fallbackSavedAt,
          dirty: false,
          status: 'error',
        });
      }
    } finally {
      if (requestVersion === assignmentDraftRequestRef.current) {
        setAssignmentDraftReady(true);
      }
    }
  };

  const retryAssignmentDraftLoad = () => {
    if (!activeAssignment) return;
    if (activeAssignmentMemoryContext) {
      removeAssignmentMemory(activeAssignmentMemoryContext);
    }
    openAssignmentModal(activeAssignment);
  };

  const handleSubmitAssignment = async () => {
    if (!activeAssignment) return;
    assignmentDraftAbortRef.current?.abort();
    const requestVersion = ++assignmentDraftRequestRef.current;
    const requestContext = assignmentRequestContext(activeAssignment.id);
    const abortController = new AbortController();
    assignmentDraftAbortRef.current = abortController;
    setAssignmentSubmitting(true);

    let submitted;
    try {
      submitted = await submitAssignment(
        axios,
        activeAssignment.id,
        assignmentSubmission,
        assignmentDraftRevision,
        { signal: abortController.signal },
      );
    } catch (error) {
      const requestIsCurrent = isCurrentAssignmentRequest(
        requestContext,
        requestVersion,
      );
      if (assignmentDraftAbortRef.current === abortController) {
        assignmentDraftAbortRef.current = null;
      }
      if (
        isCanceledAssignmentRequest(error)
        || !requestIsCurrent
      ) {
        if (requestIsCurrent) setAssignmentSubmitting(false);
        return;
      }
      setAssignmentDraftStatus('error');
      setAssignmentDraftDirty(true);
      saveAssignmentMemory(requestContext, {
        content: assignmentSubmission,
        revision: assignmentDraftRevision,
        savedAt: assignmentDraftSavedAt,
        dirty: true,
        status: 'error',
      });
      toast.error(error.response?.data?.detail || 'Failed to submit assignment');
      setAssignmentSubmitting(false);
      return;
    }

    if (!isCurrentAssignmentRequest(requestContext, requestVersion)) return;

    setAssignments((previousAssignments) => previousAssignments.map((assignment) => (
      assignment.id === activeAssignment.id
        ? {
            ...assignment,
            my_submission: submitted,
            my_draft: null,
            my_draft_revision: submitted.draft_revision,
          }
        : assignment
    )));
    removeAssignmentMemory(requestContext);
    resetAssignmentModalState();
    toast.success('Assignment submitted successfully!');

    try {
      const assignmentsResponse = await axios.get(
        `/classes/${requestContext.classId}/assignments`,
        { signal: abortController.signal },
      );
      if (isCurrentAssignmentClass(requestContext, requestVersion)) {
        setAssignments(assignmentsResponse.data || []);
      }
    } catch {
      // Submission already succeeded and local state is authoritative until
      // the next normal refresh. Do not resurrect the submitted draft.
    } finally {
      if (assignmentDraftAbortRef.current === abortController) {
        assignmentDraftAbortRef.current = null;
      }
      if (isCurrentAssignmentClass(requestContext, requestVersion)) {
        setAssignmentSubmitting(false);
      }
    }
  };

  const updateExpandableList = (id, field, value) => {
    setPostComposerDirty(true);
    setPostContent(prev => ({
      ...prev,
      expandableLists: prev.expandableLists.map(list => 
        list.id === id ? { ...list, [field]: value } : list
      )
    }));
  };

  const handleRemoveMedia = (type, index) => {
    setPostComposerDirty(true);
    setPostContent(prev => ({
      ...prev,
      [type]: prev[type].filter((_, i) => i !== index)
    }));
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-indigo-100 to-purple-100 dark:from-gray-900 dark:to-gray-800">
        <Loader />
      </div>
    );
  }

  if (error) {
    return (
      <div className={`min-h-screen flex items-center justify-center ${
        darkMode ? 'bg-gray-900 text-white' : 'bg-gray-100'
      }`}>
        <div className="text-red-500 text-xl">Error: {error}</div>
      </div>
    );
  }
  const stripHtml = (html = '') => html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const currentUserId = Number(userInfo?.userId ?? userInfo?.id ?? 0);
  const currentUserName = (userInfo?.username || '').toLowerCase();
  const currentFirstName = (userInfo?.firstName || userInfo?.first_name || '').toLowerCase();

  const displayedPosts = posts.filter((post) => {
    const title = (post.title || '').toLowerCase();
    const author = (post.author || '').toLowerCase();
    const contentText = stripHtml(post.content || '').toLowerCase();

    const matchesSearch =
      !normalizedQuery ||
      title.includes(normalizedQuery) ||
      author.includes(normalizedQuery) ||
      contentText.includes(normalizedQuery);

    if (!matchesSearch) {
      return false;
    }

    const postOwnerId = Number(post.owner_id ?? post.ownerId ?? 0);
    const isMineById = !!currentUserId && !!postOwnerId && postOwnerId === currentUserId;
    const isMineByName = !!currentFirstName && author.startsWith(currentFirstName);
    const isMineByUsername = !!currentUserName && author.includes(currentUserName);
    const isMine = isMineById || isMineByName || isMineByUsername;

    if (activeCategory === 'my') {
      return isMine;
    }

    if (activeCategory === 'liked') {
      return Boolean(likedPosts[post.id]?.userLiked);
    }

    if (activeCategory === 'commented') {
      const totalComments = commentCounts[post.id] ?? post.comments ?? 0;
      return totalComments > 0;
    }

    return true;
  });

  const canManagePost = (post) => {
    const postOwnerId = Number(post?.owner_id ?? post?.ownerId ?? 0);
    return Boolean(currentUserId) && Boolean(postOwnerId) && postOwnerId === currentUserId;
  };

  const visiblePostDrafts = postDrafts.filter((draft) => {
    if (
      String(draft.userId) !== String(postDraftUserId)
      || String(draft.classId) !== String(classId)
    ) {
      return false;
    }
    const title = (draft.postTitle || '').toLowerCase();
    const contentText = stripHtml(draft.content || '').toLowerCase();
    const label = draft.editingPostId ? `edit post ${draft.editingPostId}` : 'new post draft';
    return (
      !normalizedQuery ||
      title.includes(normalizedQuery) ||
      contentText.includes(normalizedQuery) ||
      label.includes(normalizedQuery)
    );
  });

  const openPost = (postId) => {
    navigate(`/class/${classId}/post/${postId}`, {
      state: {
        postViewerContext: {
          backLabel: 'Back to Class Feed',
          returnPath: `/class-feed/${classId}`,
          postSequence: displayedPosts.map(({ id, title }) => ({ id, title })),
        },
      },
    });
  };

  const applyPostDraftToComposer = (draftPayload) => {
    if (!draftPayload) {
      return;
    }

    setPostTitle(draftPayload.postTitle || '');
    setContent(normalizePostContentForEditor(draftPayload.content || ''));
    setPostContent(clonePrivatePostContent(draftPayload.postContent));
    setPostComposerDirty(false);
  };

  const persistCurrentPostDraft = (savedAt = null, { silent = false } = {}) => {
    if (!postDraftUserId) {
      if (!silent) {
        toast.error('Unable to save draft right now.');
      }
      return null;
    }

    const result = savePostDraftMemory({
      classId,
      userId: postDraftUserId,
      editingPostId,
      payload: {
        postTitle,
        content,
        postContent,
      },
      savedAt,
    });

    setPostDraftSavedAt(result.savedAt);
    setPostComposerDirty(false);
    return result.savedAt;
  };

  const resetPostComposer = () => {
    setPostTitle('');
    setContent('');
    setPostContent(createEmptyPostContent());
    setPostDraftSavedAt(null);
    setPostComposerDirty(false);
    setEditorUploadBusy(false);
    setPostHtmlLength(0);
  };

  const closePostComposer = ({ persistDraft = true } = {}) => {
    if (
      showNewPostForm
      && rememberDraftsEnabled
      && persistDraft
      && postComposerDirty
    ) {
      persistCurrentPostDraft(null, { silent: true });
    }
    resetPostComposer();
    setEditingPostId(null);
    setShowNewPostForm(false);
  };

  const openNewPostComposer = (event) => {
    postComposerReturnFocusRef.current = {
      element: event?.currentTarget || document.activeElement,
    };
    resetPostComposer();
    setEditingPostId(null);
    setShowNewPostForm(true);
  };

  const resumePostDraft = (draft, returnFocusTarget = document.activeElement) => {
    if (!draft) {
      return;
    }

    postComposerReturnFocusRef.current = { element: returnFocusTarget };
    resetPostComposer();
    setEditingPostId(draft.editingPostId ?? null);
    applyPostDraftToComposer({
      postTitle: draft.postTitle,
      content: draft.content,
      postContent: draft.postContent,
    });
    setPostDraftSavedAt(draft.savedAt);
    setShowNewPostForm(true);
    toast.success('Draft loaded');
  };

  const deletePostDraftByScope = (scope) => {
    removePostDraftMemory({
      classId,
      userId: postDraftUserId,
      editingPostId: scope.startsWith('edit:') ? Number(scope.split(':')[1]) : null,
    });
    toast.success('Draft deleted');
  };

  const handleSignOut = async () => {
    dismissAssignmentModal();
    clearPrivateDraftMemory();
    resetPostComposer();
    setEditingPostId(null);
    setShowNewPostForm(false);
    try {
      await logoutBrowserSession();
      setUserInfo(null);
      navigate('/');
    } catch {
      window.alert('Unable to sign out. Please try again.');
    }
  };

  const handleEditPost = async (postId, returnFocusTarget = document.activeElement) => {
    const targetPost = posts.find((post) => post.id === postId);
    if (!canManagePost(targetPost)) {
      toast.error('You can only edit your own posts.');
      return;
    }

    postComposerReturnFocusRef.current = {
      element: returnFocusTarget,
      fallbackSelector: `[data-post-actions-trigger="${postId}"]`,
    };
    try {
      setLoading(true);
      
      // Use the correct endpoint with classId
      const response = await axios.get(`/classes/${classId}/posts/${postId}`);
      
      const post = response.data;
      
      // Set the form fields with the post data
      resetPostComposer();
      setPostTitle(post.title || '');
      setContent(normalizePostContentForEditor(post.content || ''));
      setEditingPostId(postId);

      const draft = getPostDraft({
        classId,
        userId: postDraftUserId,
        editingPostId: postId,
      });
      if (draft) {
        applyPostDraftToComposer(draft);
        setPostDraftSavedAt(draft.savedAt);
        toast.success('Loaded your in-tab edit draft');
      }

      setShowNewPostForm(true);
      
    } catch (error) {
      console.error('Error fetching post for editing:', error);
      toast.error('Failed to load post for editing');
    } finally {
      setLoading(false);
    }
  };

  const handleDeletePost = async (postId) => {
    const targetPost = posts.find((post) => post.id === postId);
    if (!canManagePost(targetPost)) {
      toast.error('You can only delete your own posts.');
      return;
    }

    if (!confirm('Are you sure you want to delete this post?')) return;
    
      try {
      setLoading(true);
        await axios.delete(`/classes/${classId}/posts/${postId}`);
        
      // Remove the post from the state
      setPosts((prevPosts) => prevPosts.filter((post) => post.id !== postId));
      toast.success('Post deleted successfully');
    } catch (error) {
      console.error('Error deleting post:', error);
      toast.error('Failed to delete post');
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (editorUploadBusy) {
      toast.error('Wait for the media upload to finish before publishing.');
      return;
    }
    if (postHtmlLength > MAX_POST_HTML_LENGTH) {
      toast.error('This post is too large to publish. Remove some text or formatting and try again.');
      return;
    }
    if (loading) {
      return;
    }
    
    if (!postTitle.trim()) {
      toast.error('Please enter a post title');
      return;
    }
    
    try {
      setLoading(true);
      
      const postData = buildPostRequestPayload({
        title: postTitle,
        content,
        postContent,
      });
      
      let response;
      
      if (editingPostId) {
        // Update existing post with the correct endpoint
        response = await axios.put(
          `/classes/${classId}/posts/${editingPostId}`, 
          postData
        );
        
        // Update the post in the state
        setPosts((prevPosts) => prevPosts.map((post) => (
          post.id === editingPostId ? { ...post, ...response.data } : post
        )));

        removePostDraftMemory({
          classId,
          userId: postDraftUserId,
          editingPostId,
        });
        
        toast.success('Post updated successfully');
      } else {
        // Create new post
        response = await axios.post(
          `/classes/${classId}/posts`, 
          postData
        );
        
        // Add the new post to the state
        setPosts((prevPosts) => [response.data, ...prevPosts]);

        removePostDraftMemory({
          classId,
          userId: postDraftUserId,
          editingPostId: null,
        });
        
        toast.success('Post created successfully');
      }
      
      closePostComposer({ persistDraft: false });
    } catch {
      toast.error(editingPostId ? 'Failed to update post' : 'Failed to create post');
    } finally {
      setLoading(false);
    }
  };

  const handleSavePostDraft = () => {
    const savedAt = persistCurrentPostDraft();
    if (savedAt) {
      toast.success('Post draft saved in this tab');
    } else {
      toast.error('Nothing to save in draft yet');
    }
  };

  const handleDiscardPostDraft = async () => {
    if (!confirm('Discard this saved draft? This cannot be undone.')) {
      return;
    }

    removePostDraftMemory({
      classId,
      userId: postDraftUserId,
      editingPostId,
    });
    setPostDraftSavedAt(null);
    setPostComposerDirty(false);

    if (!editingPostId) {
      resetPostComposer();
      toast.success('Draft discarded');
      return;
    }

    try {
      const response = await axios.get(`/classes/${classId}/posts/${editingPostId}`);

      const post = response.data;
      setPostTitle(post.title || '');
      setContent(normalizePostContentForEditor(post.content || ''));
      setPostContent(createEmptyPostContent());
      setPostComposerDirty(false);
      toast.success('Draft discarded and post reset');
    } catch {
      resetPostComposer();
      toast.success('Draft discarded');
    }
  };

  const handleLikePost = async (postId) => {
    // Prevent multiple clicks
    if (likesLoading[postId]) return;
    
    // Start loading
    setLikesLoading(prev => ({ ...prev, [postId]: true }));
    
    try {
      // Optimistic update
      const isCurrentlyLiked = likedPosts[postId]?.userLiked || false;
      const currentCount = likedPosts[postId]?.count || 0;
      
      setLikedPosts(prev => ({
        ...prev,
        [postId]: {
          count: isCurrentlyLiked ? currentCount - 1 : currentCount + 1,
          userLiked: !isCurrentlyLiked
        }
      }));
      
      // Trigger heart animation
      setLikeEffects(prev => ({
        ...prev,
        [postId]: true
      }));
      
      // After animation completes
      setTimeout(() => {
        setLikeEffects(prev => ({
          ...prev,
          [postId]: false
        }));
      }, 1000);
      
      // Actually call the API
      const response = await axios.post(`/classes/${classId}/posts/${postId}/like`, {});
      
      // Update with actual data from server
      setLikedPosts(prev => ({
        ...prev,
        [postId]: {
          count: response.data.like_count,
          userLiked: response.data.action === 'liked'
        }
      }));
      
    } catch (error) {
      console.error('Error liking post:', error);
      toast.error('Failed to like post');
      
      // Revert optimistic update on error
      const response = await axios.get(`/classes/${classId}/posts/${postId}/likes`);
      
      setLikedPosts(prev => ({
        ...prev,
        [postId]: {
          count: response.data.like_count,
          userLiked: response.data.user_liked
        }
      }));
    } finally {
      // End loading
      setLikesLoading(prev => ({ ...prev, [postId]: false }));
    }
  };

  const handleToggleSavePost = async (postId) => {
    if (saveLoading[postId]) return;

    setSaveLoading((prev) => ({ ...prev, [postId]: true }));
    const previous = Boolean(savedPosts[postId]);
    setSavedPosts((prev) => ({ ...prev, [postId]: !previous }));

    try {
      const response = await axios.post(
        `/classes/${classId}/posts/${postId}/save`,
        {}
      );

      setSavedPosts((prev) => ({ ...prev, [postId]: Boolean(response.data?.is_saved) }));
    } catch (error) {
      console.error('Error saving post:', error);
      setSavedPosts((prev) => ({ ...prev, [postId]: previous }));
      toast.error('Failed to update saved post');
    } finally {
      setSaveLoading((prev) => ({ ...prev, [postId]: false }));
    }
  };

  const loadCommentsForPost = async (postId) => {
    if (commentLoading[postId]) return;
    
    setCommentLoading(prev => ({ ...prev, [postId]: true }));
    
    try {
      const response = await axios.get(`/classes/${classId}/posts/${postId}/comments?limit=3`);
      
      setPostComments(prev => ({
        ...prev,
        [postId]: response.data.comments
      }));
      
      setCommentCounts(prev => ({
        ...prev,
        [postId]: response.data.total
      }));
    } catch (error) {
      console.error(`Error loading comments for post ${postId}:`, error);
      toast.error('Failed to load comments');
    } finally {
      setCommentLoading(prev => ({ ...prev, [postId]: false }));
    }
  };

  const toggleComments = async (postId) => {
    // If comments aren't already loaded, load them
    if (!postComments[postId]) {
      await loadCommentsForPost(postId);
    }
    
    // Toggle visibility
    setPostCommentsVisible(prev => ({
      ...prev,
      [postId]: !prev[postId]
    }));
  };

  const handleSubmitComment = async (postId, e) => {
    e.preventDefault();
    
    const commentText = newCommentText[postId];
    if (!commentText || !commentText.trim()) {
      toast.error('Comment cannot be empty');
      return;
    }
    
    try {
      const response = await axios.post(
        `/classes/${classId}/posts/${postId}/comments`,
        { content: commentText }
      );
      
      // Update comments list with new comment
      setPostComments(prev => ({
        ...prev,
        [postId]: [response.data, ...(prev[postId] || [])]
      }));
      
      // Update comment count
      setCommentCounts(prev => ({
        ...prev,
        [postId]: (prev[postId] || 0) + 1
      }));
      
      // Clear input
      setNewCommentText(prev => ({
        ...prev,
        [postId]: ''
      }));
      
      toast.success('Comment added');
    } catch (error) {
      console.error('Error posting comment:', error);
      toast.error('Failed to post comment');
    }
  };

  return (
    <div className={`min-h-screen flex flex-col transition-all duration-500 ${darkMode ? 'bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200' : 'bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900'}`}>
      {/* Navbar */}
      <Navbar
        userInfo={userInfo}
        onSignOut={handleSignOut}
        darkMode={darkMode}
        logo="logo.png"
      />

      {/* Side Panel */}
      <div className="fixed left-0 h-full w-64 bg-gray-50/70 dark:bg-gray-800/50 backdrop-blur-md border-r border-gray-200 dark:border-gray-700 p-6">
        {/* Categories */}
        <div className="space-y-2">
          <button
            className={`w-full text-left px-4 py-2 rounded-lg transition-colors ${
              activeCategory === 'all'
                ? 'bg-blue-500 text-white'
                : 'hover:bg-gray-100 dark:hover:bg-gray-700'
            }`}
            onClick={() => setActiveCategory('all')}
          >
            All Posts
          </button>
          <button
            className={`w-full text-left px-4 py-2 rounded-lg transition-colors ${
              activeCategory === 'my'
                ? 'bg-blue-500 text-white'
                : 'hover:bg-gray-100 dark:hover:bg-gray-700'
            }`}
            onClick={() => setActiveCategory('my')}
          >
            My Posts
          </button>
        </div>
      </div>

      {/* Main Content - Add margin for side panel */}
      <div className="ml-64 flex-1">
        {/* Posts Feed */}
        <div className="max-w-5xl mx-auto px-8 pt-32">
          {/* Blog Header - Moved down */}
          <div className="flex justify-between items-center mb-12">
            <div className="flex items-center gap-4 flex-wrap">
              <h1 className="text-2xl font-medium">
                {classDetails?.name || 'Loading class...'}
              </h1>

              <div className="relative w-72 max-w-full">
                <input
                  type="text"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  placeholder="Search posts by title, author, or content..."
                  className={`w-full pl-10 pr-10 py-2 rounded-lg border ${
                    darkMode
                      ? 'bg-gray-800 border-gray-700 text-white'
                      : 'bg-white border-gray-300 text-gray-900'
                  } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                />
                <svg
                  className="absolute left-3 top-2.5 w-5 h-5 text-gray-400"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                  />
                </svg>
                {searchQuery && (
                  <button
                    type="button"
                    onClick={() => setSearchQuery('')}
                    className="absolute right-3 top-2 text-gray-400 hover:text-gray-600 dark:hover:text-gray-200"
                    aria-label="Clear search"
                  >
                    ✕
                  </button>
                )}
              </div>

              <div className="flex items-center space-x-3">
                <span>Filter by:</span>
                <select
                  value={activeCategory}
                  onChange={(e) => setActiveCategory(e.target.value)}
                  className={`rounded-lg py-2 px-3 ${
                  darkMode 
                    ? 'bg-gray-800 border-gray-700' 
                    : 'bg-white border-gray-300'
                  } border`}
                >
                  <option value="all">All Posts</option>
                  <option value="my">My Posts</option>
                  <option value="liked">Liked by Me</option>
                  <option value="commented">Has Comments</option>
                </select>
              </div>
            </div>
            <div className="flex items-center space-x-6">
              <motion.button 
                onClick={openNewPostComposer}
                className={`px-6 py-2 rounded-lg text-white ${
                  darkMode 
                    ? 'bg-gradient-to-r from-teal-600 to-cyan-600 hover:from-teal-500 hover:to-cyan-500' 
                    : 'bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500'
                } transition-all duration-300 shadow-lg hover:shadow-xl`}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                Create New Post
              </motion.button>
            </div>
          </div>

            {/* Assignments Panel */}
            <div className={`mb-10 rounded-2xl p-6 shadow-lg ${darkMode ? 'bg-gray-800' : 'bg-white'}`}>
              <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                <div>
                  <h2 className="text-xl font-semibold">Assignments</h2>
                  <p className="text-sm text-gray-500 dark:text-gray-400">
                    Track upcoming work and submit directly here.
                  </p>
                </div>
                {assignmentsLoading && (
                  <span className="text-sm text-gray-500 dark:text-gray-400">Loading assignments...</span>
                )}
              </div>

              {assignments.length === 0 && !assignmentsLoading && (
                <div className="text-sm text-gray-500 dark:text-gray-400 mt-4">
                  No assignments yet.
                </div>
              )}

              <div className="mt-4 grid gap-4">
                {assignments.map((assignment) => {
                  const submission = assignment.my_submission;
                  const draft = assignment.my_draft;
                  const dueDate = new Date(assignment.due_date);
                  const isOverdue = new Date() > dueDate && !submission;
                  const isDueSoon = !isOverdue && !submission && (dueDate.getTime() - Date.now()) <= (24 * 60 * 60 * 1000);
                  const isClosed = new Date() > dueDate && !assignment.allow_late && !submission;
                  const isClassVisibleAssignment = assignment.visibility === 'class';

                  return (
                    <div
                      key={assignment.id}
                      className="rounded-xl border p-4 border-gray-200 bg-white text-gray-800"
                    >
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div>
                          <h3 className="text-lg font-semibold">{assignment.title}</h3>
                          <p className="text-sm text-gray-600">
                            Due: {dueDate.toLocaleString()}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          {isClassVisibleAssignment && (
                            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-blue-500/10 text-blue-500">
                              Visible to Students
                            </span>
                          )}
                          <span
                            className={`px-3 py-1 rounded-full text-xs font-semibold ${
                              assignment.allow_late
                                ? 'bg-emerald-500/10 text-emerald-500'
                                : 'bg-rose-500/10 text-rose-500'
                            }`}
                          >
                            {assignment.allow_late ? 'Late Allowed' : 'Late Locked'}
                          </span>
                          {draft && !submission && (
                            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-amber-500/10 text-amber-500">
                              Draft Saved
                            </span>
                          )}
                          {userSettings.assignmentReminders && isDueSoon && (
                            <span className="px-3 py-1 rounded-full text-xs font-semibold bg-orange-500/10 text-orange-500">
                              Due Soon
                            </span>
                          )}
                          {isStudent && (
                            <button
                              onClick={() => openAssignmentModal(assignment)}
                              disabled={isClosed}
                              className={`px-4 py-2 rounded-lg text-sm font-medium ${
                                isClosed
                                  ? 'bg-gray-300 text-gray-500 cursor-not-allowed'
                                  : submission
                                  ? 'bg-emerald-500/10 text-emerald-500'
                                  : isOverdue
                                    ? 'bg-rose-500/10 text-rose-500'
                                    : 'bg-blue-500/10 text-blue-500'
                              }`}
                            >
                              {submission ? 'View Submission' : draft ? 'Resume Draft' : isClosed ? 'Closed' : isOverdue ? 'Submit Late' : 'Submit'}
                            </button>
                          )}
                          {canReviewSubmissions && (
                            <button
                              onClick={() => navigate(`/class/${classId}/assignment/${assignment.id}/submissions`)}
                              className="px-4 py-2 rounded-lg text-sm font-medium bg-gray-100 text-gray-700"
                            >
                              Open Submissions
                            </button>
                          )}
                        </div>
                      </div>
                      <p className="mt-2 text-sm text-gray-600">
                        {assignment.description || 'No description provided.'}
                      </p>
                      {!assignment.allow_late && (
                        <div className="mt-2 text-xs text-rose-500">
                          Late submissions close after the due date.
                        </div>
                      )}
                      {submission && (
                        <div className="mt-3 text-xs text-gray-500">
                          Submitted {new Date(submission.submitted_at).toLocaleString()} •{' '}
                          <span className={submission.is_late ? 'text-rose-500' : 'text-emerald-500'}>
                            {submission.is_late ? 'Late' : 'On time'}
                          </span>
                        </div>
                      )}

                    </div>
                  );
                })}
              </div>
            </div>

          {visiblePostDrafts.length > 0 && (
            <div className="mb-10 rounded-2xl p-6 shadow-lg bg-white text-gray-900 border border-gray-200">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="text-xl font-semibold">Your Drafts</h2>
                  <p className="text-sm text-gray-500">
                    Only visible in this tab and cleared on refresh or sign out. Click Resume to continue writing.
                  </p>
                </div>
                <span className="text-xs font-semibold px-3 py-1 rounded-full bg-amber-500/10 text-amber-500">
                  {visiblePostDrafts.length} Draft{visiblePostDrafts.length === 1 ? '' : 's'}
                </span>
              </div>

              <div className="mt-4 space-y-4">
                {visiblePostDrafts.map((draft) => {
                  const previewText = stripHtml(draft.content || '').slice(0, 220);
                  return (
                    <div
                      key={draft.key}
                      className="rounded-xl border p-4 border-gray-200 bg-gray-50"
                    >
                      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
                        <div>
                          <div className="flex items-center gap-2">
                            <h3 className="text-lg font-semibold">
                              {draft.postTitle || (draft.editingPostId ? `Draft for Post #${draft.editingPostId}` : 'Untitled Draft')}
                            </h3>
                            <span className="text-xs font-semibold px-2 py-1 rounded-full bg-amber-500/10 text-amber-500">
                              Draft
                            </span>
                          </div>
                          <p className="mt-2 text-sm text-gray-700">
                            {previewText || 'No body content yet.'}
                          </p>
                          <p className="mt-2 text-xs text-gray-600">
                            {draft.savedAt
                              ? `Saved ${new Date(draft.savedAt).toLocaleString()}`
                              : 'Saved recently'}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          <button
                            onClick={(event) => resumePostDraft(draft, event.currentTarget)}
                            className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-500/10 text-blue-500 hover:bg-blue-500/20"
                          >
                            Resume
                          </button>
                          <button
                            onClick={() => deletePostDraftByScope(draft.scope)}
                            className="px-4 py-2 rounded-lg text-sm font-medium bg-rose-500/10 text-rose-500 hover:bg-rose-500/20"
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          <div className="mb-4 text-sm text-gray-600 dark:text-gray-200">
            Showing {displayedPosts.length} of {posts.length} posts
            {searchQuery ? ` for "${searchQuery}"` : ''}
          </div>

          {/* Posts Grid */}
          <div className="space-y-8">
            {displayedPosts.length === 0 ? (
              <div className="rounded-xl p-8 text-center bg-white text-gray-700 border border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600">
                No posts match your current search/filter.
              </div>
            ) : displayedPosts.map((post) => (
              <motion.div
                key={post.id}
                layout
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className="mb-6 p-6 rounded-xl shadow-sm bg-white text-gray-900 border border-gray-200 relative"
              >
                {/* Post Header and Details */}
                <div className="flex justify-between items-start mb-4">
                  <div className="flex items-center">
                    <div className="w-10 h-10 rounded-full flex items-center justify-center bg-gray-200">
                      {post.author_profile_image ? (
                        <img
                          src={mediaPath(post.author_profile_image)}
                          alt={post.author || 'Author'}
                          className="w-full h-full rounded-full object-cover"
                        />
                      ) : (
                        post.author?.[0] || '?'
                      )}
                      </div>
                    <div className="ml-3">
                      <h3 className="font-medium text-gray-900">
                        {post.author || 'Unknown Author'}
                        </h3>
                      </div>
                    </div>

                  {/* Add post actions menu here */}
                  {canManagePost(post) && (
                    <div className="relative flex items-center gap-2">
                      <button
                        data-post-actions-trigger={post.id}
                        onClick={(e) => {
                          e.stopPropagation();
                          setMenuOpen(menuOpen === post.id ? null : post.id);
                        }}
                        aria-label={`Post actions for ${post.title || 'untitled post'}`}
                        className="p-1 rounded-full hover:bg-gray-200 transition-colors"
                      >
                        <svg className="w-5 h-5 text-gray-500" fill="currentColor" viewBox="0 0 20 20">
                          <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
                        </svg>
                      </button>

                      {menuOpen === post.id && (
                        <div
                          className="absolute right-0 mt-1 w-48 rounded-md shadow-lg z-10 bg-white border border-gray-200"
                        >
                          <div className="py-1" role="menu" aria-orientation="vertical">
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                const actionsTrigger = e.currentTarget
                                  .closest('[role="menu"]')
                                  ?.parentElement
                                  ?.previousElementSibling;
                                handleEditPost(post.id, actionsTrigger);
                                setMenuOpen(null);
                              }}
                              className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-100"
                              role="menuitem"
                            >
                              Edit Post
                            </button>
                            <button
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeletePost(post.id);
                                setMenuOpen(null);
                              }}
                              className="w-full text-left px-4 py-2 text-sm text-red-600 hover:bg-gray-100"
                              role="menuitem"
                            >
                              Delete Post
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                  </div>

                {/* Post Title - without label */}
                <div 
                  className="mb-4 px-4 py-3 rounded-lg border cursor-pointer bg-blue-50 border-blue-100"
                  onClick={() => openPost(post.id)}
                >
                  <h4 className="text-xl font-bold text-gray-800">
                    {post.title}
                  </h4>
                </div>
              
                {/* Post Content */}
                <div onClick={() => openPost(post.id)}>
                  <RichTextContent
                    html={post.content}
                    compact
                    className="html-content mb-4 cursor-pointer max-w-none text-gray-800"
                    testId={`class-feed-post-preview-${post.id}`}
                    ariaLabel={`Preview of ${post.title || 'untitled post'}`}
                  />
                </div>
                
                {/* Comments Section */}
                <AnimatePresence>
                  {postCommentsVisible[post.id] && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.3 }}
                      className="mt-4 pt-4 border-t border-gray-200 overflow-hidden"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {/* New Comment Form */}
                      <form onSubmit={(e) => handleSubmitComment(post.id, e)} className="mb-4">
                        <div className="flex items-start gap-2">
                          <div className="w-8 h-8 rounded-full bg-gray-300 flex items-center justify-center flex-shrink-0 text-sm">
                            {userInfo?.profile_image ? (
                              <img
                                src={mediaPath(userInfo.profile_image)}
                                alt={userInfo?.username || 'User'}
                                className="w-full h-full rounded-full object-cover"
                              />
                            ) : (
                              userInfo?.first_name?.[0] || userInfo?.firstName?.[0] || '?'
                            )}
                    </div>
                          <div className="flex-1">
                            <textarea
                              value={newCommentText[post.id] || ''}
                              onChange={(e) => setNewCommentText(prev => ({
                                ...prev,
                                [post.id]: e.target.value
                              }))}
                              placeholder="Add a comment..."
                              className="w-full p-2 text-sm bg-gray-50 border border-gray-300 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500"
                              rows={1}
                            />
                            <div className="flex justify-end mt-1">
                              <button
                                type="submit"
                                className="px-3 py-1 text-xs bg-blue-500 text-white rounded-lg hover:bg-blue-600"
                              >
                                Post
                              </button>
                    </div>
                  </div>
                        </div>
                      </form>
                      
                      {/* Comments List */}
                      {commentLoading[post.id] ? (
                        <div className="flex justify-center py-4">
                          <div className="w-6 h-6 border-2 border-t-blue-500 border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin" />
                        </div>
                      ) : postComments[post.id]?.length > 0 ? (
                        <div className="space-y-3">
                          {postComments[post.id].map(comment => (
                            <CommentThread
                              key={comment.id}
                              comment={comment}
                              classId={classId}
                              postId={post.id}
                              onReply={(_newComment) => {
                                // Handle new reply
                                setCommentCounts(prev => ({
                                  ...prev, 
                                  [post.id]: (prev[post.id] || 0) + 1
                                }));
                              }}
                              onLike={() => {/* handle like if needed */}}
                            />
                          ))}
                          
                          {/* Show more comments link */}
                          {commentCounts[post.id] > (postComments[post.id]?.length || 0) && (
                            <div 
                              onClick={() => openPost(post.id)}
                              className="text-center py-2 text-sm text-blue-500 hover:text-blue-700 cursor-pointer"
                            >
                              View all {commentCounts[post.id]} comments
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="py-4 text-center text-gray-700 text-sm">
                          No comments yet. Be the first to comment!
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
                
                {/* Post Actions/Stats */}
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-gray-200">
                  <div className="flex items-center space-x-6">
                    {/* Like button with animations */}
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        handleLikePost(post.id);
                      }}
                      className="flex items-center space-x-1 text-gray-700 hover:text-red-500 transition-colors relative"
                      disabled={likesLoading[post.id]}
                    >
                      <div className="relative">
                        {likedPosts[post.id]?.userLiked ? (
                          <IoMdHeart className="w-5 h-5 text-red-500" />
                        ) : (
                          <IoMdHeartEmpty className="w-5 h-5" />
                        )}
                        
                        {/* Heart animation effect */}
                        <AnimatePresence>
                          {likeEffects[post.id] && (
                            <motion.div
                              className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-10"
                              initial={{ scale: 1, opacity: 0.8 }}
                              animate={{ scale: 2, opacity: 0 }}
                              exit={{ opacity: 0 }}
                              transition={{ duration: 0.8 }}
                            >
                              <IoMdHeart className="w-5 h-5 text-red-500" />
                            </motion.div>
                          )}
                        </AnimatePresence>
                      </div>
                      
                      <span>{likedPosts[post.id]?.count || 0}</span>
                    </button>
                    
                    {/* Comment button (existing or new) */}
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleComments(post.id);
                      }}
                      className="flex items-center space-x-1 text-gray-700 hover:text-blue-500 transition-colors"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                      </svg>
                      {/* Ensure we're checking if commentCounts[post.id] exists */}
                      <span>Comment{commentCounts[post.id] ? ` (${commentCounts[post.id]})` : ''}</span>
                    </button>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleToggleSavePost(post.id);
                      }}
                      className={`flex items-center space-x-1 transition-colors ${savedPosts[post.id] ? 'text-blue-600' : 'text-gray-700 hover:text-blue-500'}`}
                      disabled={saveLoading[post.id]}
                    >
                      <svg className="w-5 h-5" fill={savedPosts[post.id] ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v17l-7-4-7 4V5z" />
                      </svg>
                      <span>{savedPosts[post.id] ? 'Saved' : 'Save'}</span>
                    </button>
                  </div>
                  
                  {/* Add the timestamp here */}
                  <span className="text-sm text-gray-600" data-timestamp={post.created_at}>
                    {formatRelativeTime(post.created_at)}
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>

        {/* Assignment Submission Modal */}
        <AnimatePresence>
          {showAssignmentModal && activeAssignment && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50"
            >
              <motion.div
                initial={{ scale: 0.9, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                exit={{ scale: 0.9, opacity: 0 }}
                className="bg-white rounded-lg p-6 max-w-5xl w-full shadow-xl text-gray-900"
              >
                <div className="mb-4">
                  <h3 className="text-xl font-semibold">{activeAssignment.title}</h3>
                  <p className="text-sm text-gray-500">
                    Due: {new Date(activeAssignment.due_date).toLocaleString()}
                  </p>
                </div>
                <div className="grid gap-4 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
                  <div className="rounded-xl border p-4 border-gray-200 bg-gray-50">
                    <div className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                      Assignment Prompt
                    </div>
                    <div className="mt-3 space-y-3">
                      <div>
                        <div className="text-sm font-medium text-gray-500">Question</div>
                        <div className="mt-1 text-base font-semibold text-gray-900">
                          {activeAssignment.title}
                        </div>
                      </div>
                      <div>
                        <div className="text-sm font-medium text-gray-500">Details</div>
                        <div className="mt-1 whitespace-pre-wrap text-sm text-gray-700">
                          {activeAssignment.description || 'No additional instructions provided.'}
                        </div>
                      </div>
                    </div>
                  </div>
                  <div>
                    <div className="mb-2 flex items-center justify-between text-sm">
                      <span className="font-medium text-gray-700">Your Response</span>
                      <span className="text-xs text-gray-500">
                        {!rememberDraftsEnabled
                          ? 'Kept only in this tab; account autosave is off'
                          : !assignmentDraftReady
                          ? 'Loading saved draft...'
                          : assignmentDraftClosing || assignmentDraftStatus === 'saving'
                          ? 'Saving securely to your account...'
                          : assignmentDraftStatus === 'error' && !assignmentDraftDirty
                          ? 'Could not load your saved draft; retry when ready'
                          : assignmentDraftStatus === 'error'
                          ? 'Autosave failed — keep this tab open'
                          : assignmentDraftStatus === 'pending'
                          ? 'Waiting to save securely...'
                          : assignmentDraftSavedAt
                          ? `Saved to your account ${new Date(assignmentDraftSavedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
                          : 'Draft autosaves securely to your account'}
                      </span>
                    </div>
                    <textarea
                      value={assignmentSubmission}
                      onChange={handleAssignmentSubmissionChange}
                      disabled={!assignmentDraftReady || assignmentDraftClosing || assignmentSubmitting}
                      rows={14}
                      placeholder="Write your submission..."
                      className="w-full min-h-[320px] p-3 rounded-lg border bg-white border-gray-300 text-gray-900"
                      style={{ fontSize: `${editorFontSizePx}px` }}
                    />
                  </div>
                </div>
                <div className="mt-4 flex justify-end gap-3">
                  {assignmentDraftStatus === 'error' && !assignmentDraftDirty && (
                    <button
                      onClick={retryAssignmentDraftLoad}
                      disabled={assignmentDraftClosing || assignmentSubmitting}
                      className="px-4 py-2 rounded-lg bg-amber-100 text-amber-700"
                    >
                      Retry loading
                    </button>
                  )}
                  {assignmentDraftStatus === 'error' && assignmentDraftDirty && (
                    <button
                      onClick={discardUnsavedAssignmentChanges}
                      disabled={assignmentDraftClosing || assignmentSubmitting}
                      className="px-4 py-2 rounded-lg bg-rose-100 text-rose-700"
                    >
                      Discard unsaved changes
                    </button>
                  )}
                  <button
                    onClick={closeAssignmentModal}
                    disabled={assignmentDraftClosing || assignmentSubmitting}
                    className="px-4 py-2 rounded-lg bg-gray-100 text-gray-700"
                  >
                    {assignmentDraftClosing ? 'Saving...' : 'Cancel'}
                  </button>
                  <button
                    onClick={handleSubmitAssignment}
                    disabled={assignmentSubmitting || assignmentDraftClosing || !assignmentDraftReady}
                    className="px-4 py-2 rounded-lg text-white bg-blue-600 hover:bg-blue-500"
                  >
                    {assignmentSubmitting ? 'Submitting...' : 'Submit'}
                  </button>
                </div>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

      {/* New Post Modal */}
      <AnimatePresence>
        {showNewPostForm && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center p-4 z-50"
          >
            <motion.div
              ref={postComposerDialogRef}
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className="bg-white rounded-lg p-6 max-w-4xl w-full shadow-xl max-h-[90vh] overflow-y-auto text-gray-900"
              role="dialog"
              aria-modal="true"
              aria-labelledby="post-composer-dialog-title"
              tabIndex={-1}
              onKeyDown={(event) => {
                if (event.key === 'Escape') {
                  if (event.defaultPrevented) return;
                  event.preventDefault();
                  event.stopPropagation();
                  if (!loading && !editorUploadBusy) {
                    closePostComposer();
                  }
                  return;
                }
                containDialogFocus(event, postComposerDialogRef.current);
              }}
            >
              <h2 id="post-composer-dialog-title" className="mb-4 text-2xl font-bold text-gray-900">
                {editingPostId ? 'Edit post' : 'Create post'}
              </h2>
              <div className="mb-4 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gray-300 flex items-center justify-center">
                  {userInfo?.profile_image ? (
                    <img
                      src={mediaPath(userInfo.profile_image)}
                      alt={userInfo?.username || 'User'}
                      className="w-full h-full rounded-full object-cover"
                    />
                  ) : (
                    <svg
                      className="w-6 h-6 text-gray-600"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth="2"
                        d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
                      />
                    </svg>
                  )}
                </div>
                <span className="text-sm text-gray-600">
                  Posting as {userInfo?.firstName || userInfo?.first_name || userInfo?.username || 'Current user'}
                </span>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                {/* Title Input - professional styling */}
                <div className="mb-5 p-4 rounded-lg border bg-blue-50 border-blue-100">
                  <label htmlFor="post-title" className="block text-base font-bold text-gray-800 mb-2">
                    Post Title (Required)
                  </label>
                <input
                  autoFocus
                  type="text"
                    id="post-title"
                    value={postTitle}
                    onChange={(e) => {
                      setPostTitle(e.target.value);
                      setPostComposerDirty(true);
                    }}
                    className="w-full p-3 rounded-lg border text-lg bg-white border-blue-200 text-gray-800"
                    placeholder="Enter a descriptive title for your post"
                  required
                />
                  <div className="mt-2 text-xs text-gray-500">
                    This will be displayed at the top of your post
                  </div>
                </div>

                {/* Content Input */}
                <div className="relative">
                  <Suspense
                    fallback={(
                      <div className="flex h-32 items-center justify-center rounded-lg border border-gray-200 bg-gray-50 text-sm text-gray-600">
                        Loading the editor&hellip;
                      </div>
                    )}
                  >
                    <LitBlogsEditor
                      value={content}
                      editorFontSize={userSettings.editorFontSize}
                      disabled={loading}
                      onUploadStateChange={setEditorUploadBusy}
                      onContentLimitChange={({ length }) => setPostHtmlLength(length)}
                      onChange={(nextContent) => {
                        setContent(nextContent);
                        setPostComposerDirty(true);
                      }}
                    />
                  </Suspense>
                  {postHtmlLength > MAX_POST_HTML_LENGTH && (
                    <div
                      className="mt-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
                      role="alert"
                    >
                      This post is too large to publish. Remove some text or formatting until the
                      formatted content is {MAX_POST_HTML_LENGTH.toLocaleString('en-US')} characters
                      or fewer ({postHtmlLength.toLocaleString('en-US')} currently).
                    </div>
                  )}
                  
                  {/* Add the MediaPreview component here */}
                  <MediaPreview 
                    media={postContent.media}
                    files={postContent.files}
                    onRemove={handleRemoveMedia}
                  />
                  
                  {/* Code Snippets Display */}
                  {postContent.codeSnippets.map((snippet, _index) => (
                    <div key={snippet.id} className="mt-4 rounded-lg overflow-hidden border border-gray-300">
                      <div className="flex items-center justify-between p-2 bg-gray-100">
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-mono text-gray-600">
                            {snippet.language}
                          </span>
                        </div>
                        <button
                          type="button"
                          onClick={() => {
                            setPostComposerDirty(true);
                            setPostContent(prev => ({
                              ...prev,
                              codeSnippets: prev.codeSnippets.filter(s => s.id !== snippet.id)
                            }));
                          }}
                          className="text-gray-500 hover:text-red-500 px-2"
                        >
                          ×
                        </button>
                      </div>
                      <div className="p-4 font-mono text-sm bg-gray-50">
                        <pre className="max-h-[250px] overflow-y-auto">
                          <code className={`language-${snippet.language || 'javascript'}`}>
                            {snippet.code.trim()}
                          </code>
                        </pre>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Expandable Lists */}
                {postContent.expandableLists.map(list => (
                  <div key={list.id} className="mt-4 border rounded-lg overflow-hidden">
                    <div 
                      className="p-4 cursor-pointer flex items-center gap-2 bg-gray-100"
                      onClick={() => updateExpandableList(list.id, 'isCollapsed', !list.isCollapsed)}
                    >
                      <span className="transform transition-transform duration-200" style={{
                        transform: list.isCollapsed ? 'rotate(-90deg)' : 'rotate(0deg)'
                      }}>
                        ▼
                      </span>
                      <input
                        type="text"
                        value={list.title}
                        onChange={(e) => updateExpandableList(list.id, 'title', e.target.value)}
                        className="flex-1 bg-transparent border-none focus:ring-0 text-gray-900"
                        placeholder="Write a title"
                        onClick={e => e.stopPropagation()}
                      />
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          setPostComposerDirty(true);
                          setPostContent(prev => ({
                            ...prev,
                            expandableLists: prev.expandableLists.filter(item => item.id !== list.id)
                          }));
                        }}
                        className="text-gray-500 hover:text-red-500"
                      >
                        ×
                      </button>
                    </div>
                    {!list.isCollapsed && (
                      <div className="p-4">
                        <textarea
                          value={list.content}
                          onChange={(e) => updateExpandableList(list.id, 'content', e.target.value)}
                          className="w-full p-2 rounded border bg-white border-gray-300 text-gray-900"
                          placeholder="Add content to expand"
                          rows="3"
                        />
                      </div>
                    )}
                  </div>
                ))}

                {/* Action Buttons */}
                <div className="flex items-center justify-between gap-4">
                  <span className="text-xs text-gray-500">
                    {!rememberDraftsEnabled
                      ? 'Kept only in this tab until you close the editor'
                      : postDraftSavedAt
                      ? `Kept only in this tab · Saved ${new Date(postDraftSavedAt).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}`
                      : 'Kept only in this tab; it is cleared on refresh or sign out'}
                  </span>
                  <div className="flex gap-4">
                    <motion.button
                      type="button"
                      onClick={handleSavePostDraft}
                      disabled={loading || editorUploadBusy || postHtmlLength > MAX_POST_HTML_LENGTH}
                      className="px-6 py-2 rounded-lg bg-amber-500 text-white hover:bg-amber-400"
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                    >
                      Save Draft
                    </motion.button>
                    <motion.button
                      type="button"
                      onClick={handleDiscardPostDraft}
                      disabled={loading || editorUploadBusy}
                      className="px-6 py-2 rounded-lg bg-rose-600 text-white hover:bg-rose-500"
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                    >
                      Discard Draft
                    </motion.button>
                  <motion.button
                    type="button"
                    onClick={closePostComposer}
                    disabled={loading || editorUploadBusy}
                    className="px-6 py-2 rounded-lg bg-gray-200 hover:bg-gray-300"
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    Cancel
                  </motion.button>
                  <motion.button
                    type="submit"
                    disabled={loading || editorUploadBusy || postHtmlLength > MAX_POST_HTML_LENGTH}
                    className="px-6 py-2 rounded-lg text-white bg-blue-600 hover:bg-blue-700"
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    {editorUploadBusy
                      ? 'Uploading media…'
                      : loading
                      ? 'Saving…'
                      : editingPostId
                      ? 'Update Post'
                      : 'Publish'}
                  </motion.button>
                  </div>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="ml-64">
        <Footer darkMode={darkMode} />
      </div>
    </div>
  );
};

export default ClassFeed; 


