import { useState, useEffect } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import Loader from './components/Loader';
import './LitBlogs.css';
import { IoMdHeart, IoMdHeartEmpty } from 'react-icons/io';
import toast from 'react-hot-toast';
import CommentThread from './components/CommentThread';
import RichTextContent from './components/RichTextContent';
import { formatRelativeTime, setupTimeUpdater } from './utils/timeUtils';
import { mediaPath } from './utils/urlUtils';
import Footer from './components/Footer';

const PostView = () => {
  const { classId, postId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const viewerContext = location.state?.postViewerContext || null;
  const reviewSequence = Array.isArray(viewerContext?.postSequence) ? viewerContext.postSequence : [];
  const currentReviewIndex = reviewSequence.findIndex((item) => String(item.id) === String(postId));
  const previousReviewPost = currentReviewIndex > 0 ? reviewSequence[currentReviewIndex - 1] : null;
  const nextReviewPost =
    currentReviewIndex >= 0 && currentReviewIndex < reviewSequence.length - 1
      ? reviewSequence[currentReviewIndex + 1]
      : null;
  
  const [post, setPost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userInfo, setUserInfo] = useState(null);
  const [darkMode, setDarkMode] = useState(false);
  const [liked, setLiked] = useState(false);
  const [likeCount, setLikeCount] = useState(0);
  const [likeLoading, setLikeLoading] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveLoading, setSaveLoading] = useState(false);
  const [showLikeEffect, setShowLikeEffect] = useState(false);
  const [comments, setComments] = useState([]);
  const [totalComments, setTotalComments] = useState(0);
  const [hasMoreComments, setHasMoreComments] = useState(false);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [commentsExpanded, setCommentsExpanded] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [commentSubmitting, setCommentSubmitting] = useState(false);

  const getInitialFromUser = (value) => {
    if (!value) return '?';

    if (typeof value === 'string') {
      const trimmed = value.trim();
      return trimmed ? trimmed[0].toUpperCase() : '?';
    }

    const firstName = value.first_name || value.firstName || '';
    const lastName = value.last_name || value.lastName || '';
    const username = value.username || '';
    const email = value.email || '';
    const source = firstName || lastName || username || email;
    return source ? source[0].toUpperCase() : '?';
  };

  const getDisplayNameFromUser = (value) => {
    if (!value) return 'Unknown Author';
    if (typeof value === 'string') return value;

    const firstName = value.first_name || value.firstName || '';
    const lastName = value.last_name || value.lastName || '';
    const fullName = `${firstName} ${lastName}`.trim();
    return fullName || value.username || value.email || 'Unknown Author';
  };

  useEffect(() => {
    const storedDarkMode = JSON.parse(localStorage.getItem('darkMode'));
    if (storedDarkMode !== null) {
      setDarkMode(storedDarkMode);
    } else {
      const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      setDarkMode(systemPrefersDark);
    }
  }, []);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [darkMode]);

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [postId]);

  useEffect(() => {
    // Load user info
    const storedUserInfo = sessionStorage.getItem('user_info');
    if (storedUserInfo) {
      setUserInfo(JSON.parse(storedUserInfo));
    }

    const fetchPost = async () => {
      try {
        setLoading(true);
        // Fetch the post
        const response = await axios.get(`/classes/${classId}/posts/${postId}`);
        
        // Process the post data
        const postData = response.data;
        
        // Set the post data
        setPost(postData);
        
        // Set like status
        setLiked(postData.user_liked || false);
        setLikeCount(postData.likes || 0);
        setSaved(Boolean(postData.is_saved));
        
        // Load comments
        fetchComments();
        
      } catch (error) {
        console.error('Error fetching post:', error);
        setError('Failed to load post. Please try again later.');
      } finally {
        setLoading(false);
      }
    };

    fetchPost();
  }, [classId, postId]);

  useEffect(() => {
    const fetchLikes = async () => {
      if (!post || !post.id) return;
      
      try {
        const response = await axios.get(`/classes/${classId}/posts/${post.id}/likes`);
        
        setLiked(response.data.user_liked);
        setLikeCount(response.data.like_count);
      } catch (error) {
        console.error('Error fetching like status:', error);
      }
    };
    
    fetchLikes();
  }, [post]);

  useEffect(() => {
    // Also fetch comments
    fetchComments();
  }, [postId, classId]);

  const fetchComments = async (skip = 0) => {
    try {
      const response = await axios.get(
        `/classes/${classId}/posts/${postId}/comments?skip=${skip}&limit=5`
      );
      
      if (skip === 0) {
        setComments(response.data.comments);
      } else {
        setComments([...comments, ...response.data.comments]);
      }
      
      setTotalComments(response.data.total);
      setHasMoreComments(response.data.has_more);
      setCommentsLoading(false);
    } catch (error) {
      console.error('Error fetching comments:', error);
      setCommentsLoading(false);
    }
  };

  const handleBack = () => {
    if (viewerContext?.selectedClass) {
      navigate('/teacher-dashboard', {
        state: {
          selectedClass: viewerContext.selectedClass,
          classDetailsTab: viewerContext.classDetailsTab || 'Blogs',
        },
      });
    } else if (viewerContext?.returnPath) {
      navigate(viewerContext.returnPath);
    } else if (userInfo?.role === 'TEACHER') {
      navigate('/teacher-dashboard');
    } else {
      navigate(`/class-feed/${classId}`);
    }
  };

  const handleReviewNavigation = (targetPostId) => {
    if (!targetPostId) {
      return;
    }

    navigate(`/class/${classId}/post/${targetPostId}`, {
      state: {
        postViewerContext: viewerContext,
      },
    });
  };

  const handleLike = async () => {
    if (likeLoading) return;
    setLikeLoading(true);
    
    try {
      // Optimistic update
      setLiked(!liked);
      setLikeCount(liked ? likeCount - 1 : likeCount + 1);
      
      // Show animation effect
      setShowLikeEffect(true);
      setTimeout(() => {
        setShowLikeEffect(false);
      }, 1000);
      
      // Call API
      const response = await axios.post(`/classes/${classId}/posts/${post.id}/like`, {});
      
      // Update with actual data
      setLiked(response.data.action === 'liked');
      setLikeCount(response.data.like_count);
    } catch (error) {
      console.error('Error liking post:', error);
      toast.error('Failed to like post');
      
      // Revert on error
      const response = await axios.get(`/classes/${classId}/posts/${post.id}/likes`);
      
      setLiked(response.data.user_liked);
      setLikeCount(response.data.like_count);
    } finally {
      setLikeLoading(false);
    }
  };

  const handleCommentSubmit = async (e) => {
    e.preventDefault();
    
    if (!newComment.trim()) {
      toast.error('Comment cannot be empty');
      return;
    }
    
    setCommentSubmitting(true);
    
    try {
      const response = await axios.post(
        `/classes/${classId}/posts/${postId}/comments`,
        { content: newComment }
      );
      
      // Add new comment to the list
      setComments([response.data, ...comments]);
      setTotalComments(totalComments + 1);
      
      // Clear the input
      setNewComment('');
      
      // Expand comments section if it's not already
      setCommentsExpanded(true);
      
      toast.success('Comment added');
    } catch (error) {
      console.error('Error posting comment:', error);
      toast.error('Failed to post comment');
    } finally {
      setCommentSubmitting(false);
    }
  };

  const handleToggleSave = async () => {
    if (saveLoading || !post?.id) return;

    setSaveLoading(true);
    const previous = saved;
    setSaved(!previous);

    try {
      const response = await axios.post(
        `/classes/${classId}/posts/${post.id}/save`,
        {}
      );
      setSaved(Boolean(response.data?.is_saved));
    } catch (error) {
      console.error('Error saving post:', error);
      setSaved(previous);
      toast.error('Failed to update saved post');
    } finally {
      setSaveLoading(false);
    }
  };

  const handleLoadMoreComments = () => {
    fetchComments(comments.length);
  };

  const handleCommentReply = (_newReply) => {
    // No need to update state as the child component handles displaying the reply
    // Just update the total count
    setTotalComments(totalComments + 1);
  };

  const handleCommentLike = (_commentId, _newLikeCount, _isLiked) => {
    // Update like count in state if needed for total calculations
  };

  const handleCommentButtonClick = () => {
    // Toggle comments expansion
    setCommentsExpanded(!commentsExpanded);
    
    // If comments aren't loaded yet, fetch them
    if (!comments.length && !commentsLoading) {
      fetchComments();
    }
    
    // Scroll to comments section smoothly if expanding
    if (!commentsExpanded) {
      setTimeout(() => {
        document.getElementById('comments-section')?.scrollIntoView({
          behavior: 'smooth',
          block: 'start'
        });
      }, 100);
    }
  };

  useEffect(() => {
    const timeUpdateInterval = setupTimeUpdater();
    return () => clearInterval(timeUpdateInterval);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader />
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-red-500 text-xl">{error}</div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen ${darkMode ? 'bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200' : 'bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900'}`}>
      <div className="max-w-4xl mx-auto px-4 py-8">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="bg-white rounded-lg shadow-xl overflow-hidden border border-gray-200"
        >
          {/* Back Button */}
          <div className="p-4 border-b border-gray-200 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <motion.button
              onClick={handleBack}
              className="flex items-center gap-2 text-blue-500 hover:text-blue-600"
              whileHover={{ x: -5 }}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              {viewerContext?.backLabel || (userInfo?.role === 'TEACHER' ? 'Back to Dashboard' : 'Back to Class')}
            </motion.button>

            {currentReviewIndex >= 0 && reviewSequence.length > 1 && (
              <div className="flex items-center gap-2 self-start sm:self-auto">
                <span className="text-xs text-gray-600">
                  Post {currentReviewIndex + 1} of {reviewSequence.length}
                </span>
                <button
                  onClick={() => handleReviewNavigation(previousReviewPost?.id)}
                  disabled={!previousReviewPost}
                  className="px-3 py-1.5 rounded-lg text-sm border transition-colors border-gray-300 text-gray-700 disabled:text-gray-400"
                >
                  Previous
                </button>
                <button
                  onClick={() => handleReviewNavigation(nextReviewPost?.id)}
                  disabled={!nextReviewPost}
                  className="px-3 py-1.5 rounded-lg text-sm bg-blue-600 text-white disabled:opacity-50"
                >
                  Next
                </button>
              </div>
            )}
          </div>

          {/* Post Content */}
          <div className="p-6">
            {/* Author Info */}
            <div className="flex items-center space-x-3 mb-6">
              <div className="w-12 h-12 rounded-full bg-gray-300 flex items-center justify-center">
                {post?.author?.profile_image ? (
                  <img
                    src={mediaPath(post.author.profile_image)}
                    alt={getDisplayNameFromUser(post.author)}
                    className="w-full h-full rounded-full object-cover"
                  />
                ) : (
                  getInitialFromUser(post.author)
                )}
              </div>
              <div>
                <h3 className="font-medium text-lg text-gray-900">
                  {getDisplayNameFromUser(post.author)}
                </h3>
                <span className="text-sm text-gray-600" data-timestamp={post.created_at}>
                  {formatRelativeTime(post.created_at)}
                </span>
              </div>
            </div>

            {/* Post Title - without label */}
            <div className="mb-6 px-5 py-4 rounded-lg border bg-blue-50 border-blue-100">
              <h1 className="text-2xl font-bold text-gray-800">
                {post.title}
              </h1>
            </div>

            {/* Post Content */}
            <div className="max-w-none mt-6 text-gray-800">
              <RichTextContent
                html={post.content || ''}
                className="html-content"
                testId="post-view-content"
                ariaLabel="Post content"
              />
            </div>

            {/* Interactions */}
            <div className="mt-8 pt-6 border-t border-gray-200">
              <div className="flex items-center space-x-6">
                <button 
                  onClick={handleLike}
                  className="flex items-center space-x-2 text-gray-700 hover:text-red-500 transition-colors"
                  disabled={likeLoading}
                >
                  <div className="relative">
                    {liked ? (
                      <IoMdHeart className="w-6 h-6 text-red-500" />
                    ) : (
                      <IoMdHeartEmpty className="w-6 h-6" />
                    )}
                    
                    {/* Heart animation effect */}
                    <AnimatePresence>
                      {showLikeEffect && (
                        <motion.div
                          className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 z-10"
                          initial={{ scale: 1, opacity: 0.8 }}
                          animate={{ scale: 2, opacity: 0 }}
                          exit={{ opacity: 0 }}
                          transition={{ duration: 0.8 }}
                        >
                          <IoMdHeart className="w-6 h-6 text-red-500" />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                  <span>{likeCount} {likeCount === 1 ? 'Like' : 'Likes'}</span>
                </button>
                
                <button 
                  onClick={handleCommentButtonClick}
                  className="flex items-center space-x-2 text-gray-700 hover:text-blue-500 transition-colors"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  <span>Comment{totalComments > 0 ? ` (${totalComments})` : ''}</span>
                </button>

                <button
                  onClick={handleToggleSave}
                  className={`flex items-center space-x-2 transition-colors ${saved ? 'text-blue-600' : 'text-gray-700 hover:text-blue-500'}`}
                  disabled={saveLoading}
                >
                  <svg className="w-6 h-6" fill={saved ? 'currentColor' : 'none'} stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 5a2 2 0 012-2h10a2 2 0 012 2v17l-7-4-7 4V5z" />
                  </svg>
                  <span>{saved ? 'Saved' : 'Save'}</span>
                </button>
              </div>
            </div>

            {/* Comments Section */}
            <div id="comments-section" className="mt-8 pt-4 border-t border-gray-200">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium text-gray-900">
                  Comments ({totalComments})
                </h3>
                <button
                  onClick={() => setCommentsExpanded(!commentsExpanded)}
                  className="text-sm text-blue-500 flex items-center gap-1"
                >
                  {commentsExpanded ? 'Hide comments' : 'Show comments'}
                  <svg 
                    className={`w-4 h-4 transition-transform ${commentsExpanded ? 'rotate-180' : 'rotate-0'}`} 
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>
              </div>
              
              {/* New Comment Form */}
              <form onSubmit={handleCommentSubmit} className="mb-6">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-full bg-gray-300 flex items-center justify-center flex-shrink-0">
                    {userInfo?.profile_image ? (
                      <img
                        src={mediaPath(userInfo.profile_image)}
                        alt={getDisplayNameFromUser(userInfo)}
                        className="w-full h-full rounded-full object-cover"
                      />
                    ) : (
                      getInitialFromUser(userInfo)
                    )}
                  </div>
                  <div className="flex-1">
                    <textarea
                      value={newComment}
                      onChange={(e) => setNewComment(e.target.value)}
                      placeholder="Add a comment..."
                      className="w-full p-3 bg-gray-50 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                      rows={2}
                    />
                    <div className="flex justify-end mt-2">
                      <button
                        type="submit"
                        disabled={commentSubmitting}
                        className="px-4 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 disabled:opacity-50 flex items-center gap-2"
                      >
                        {commentSubmitting ? (
                          <>
                            <div className="w-4 h-4 border-2 border-t-transparent border-white rounded-full animate-spin" />
                            Posting...
                          </>
                        ) : 'Post Comment'}
                      </button>
                    </div>
                  </div>
                </div>
              </form>
              
              {/* Comments List */}
              <AnimatePresence>
                {commentsExpanded && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3 }}
                    className="overflow-hidden"
                  >
                    {commentsLoading ? (
                      <div className="flex justify-center py-8">
                        <div className="w-8 h-8 border-4 border-t-blue-500 border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin" />
                      </div>
                    ) : comments.length > 0 ? (
                      <div className="space-y-4">
                        {comments.map(comment => (
                          <CommentThread
                            key={comment.id}
                            comment={comment}
                            classId={classId}
                            postId={postId}
                            onReply={handleCommentReply}
                            onLike={handleCommentLike}
                          />
                        ))}
                        
                        {/* Load More Comments */}
                        {hasMoreComments && (
                          <div className="flex justify-center my-4">
                            <button
                              onClick={handleLoadMoreComments}
                              className="px-4 py-2 text-sm text-blue-500 hover:text-blue-700 border border-blue-300 rounded-lg hover:bg-blue-50"
                            >
                              Load more comments
                            </button>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="py-8 text-center text-gray-700">
                        No comments yet. Be the first to comment!
                      </div>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </motion.div>
      </div>
      <Footer darkMode={darkMode} />
    </div>
  );
};

export default PostView; 

