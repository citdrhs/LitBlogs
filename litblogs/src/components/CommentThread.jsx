import { useState } from 'react';
import { IoMdHeart, IoMdHeartEmpty } from 'react-icons/io';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import toast from 'react-hot-toast';

const CommentThread = ({ 
  comment, 
  classId, 
  postId, 
  token, 
  onReply, 
  onLike, 
  depth = 0, 
  maxDepth = 3 
}) => {
  const [expanded, setExpanded] = useState(true);
  const [showReplies, setShowReplies] = useState(depth < 2);
  const [expandedReplies, setExpandedReplies] = useState([]);
  const [loadingMore, setLoadingMore] = useState(false);
  const [likeLoading, setLikeLoading] = useState(false);
  const [showLikeEffect, setShowLikeEffect] = useState(false);
  const [replyFormVisible, setReplyFormVisible] = useState(false);
  const [replyText, setReplyText] = useState('');
  const [likeCount, setLikeCount] = useState(comment.likes);
  const [userLiked, setUserLiked] = useState(comment.user_liked);
  
  const toggleExpanded = () => {
    setExpanded(!expanded);
  };

  const toggleShowReplies = async () => {
    if (!showReplies && comment.replies.length === 0 && comment.has_more_replies) {
      // Load replies if they haven't been loaded yet
      await loadMoreReplies();
    }
    setShowReplies(!showReplies);
  };

  const loadMoreReplies = async () => {
    if (loadingMore) return;
    
    setLoadingMore(true);
    try {
      const response = await axios.get(
        `/comments/${comment.id}/replies?skip=${comment.replies.length}`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      // Update comment with new replies
      comment.replies = [...comment.replies, ...response.data.replies];
      comment.has_more_replies = response.data.has_more;
      
      // Force a re-render
      setExpandedReplies([...expandedReplies]);
    } catch (error) {
      console.error('Error loading more replies:', error);
      toast.error('Failed to load replies');
    } finally {
      setLoadingMore(false);
    }
  };

  const handleLike = async () => {
    if (likeLoading) return;
    
    setLikeLoading(true);
    try {
      // Optimistic update
      setUserLiked(!userLiked);
      setLikeCount(userLiked ? likeCount - 1 : likeCount + 1);
      
      // Show animation
      setShowLikeEffect(true);
      setTimeout(() => {
        setShowLikeEffect(false);
      }, 1000);
      
      // Call API
      const response = await axios.post(
        `/comments/${comment.id}/like`,
        {}, 
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      // Update with actual data from server
      setLikeCount(response.data.like_count);
      setUserLiked(response.data.action === 'liked');
      
      // Call parent handler if provided
      if (onLike) onLike(comment.id, response.data.like_count, response.data.action === 'liked');
      
    } catch (error) {
      console.error('Error liking comment:', error);
      toast.error('Failed to like comment');
      
      // Revert optimistic update
      setUserLiked(comment.user_liked);
      setLikeCount(comment.likes);
    } finally {
      setLikeLoading(false);
    }
  };
  
  const handleSubmitReply = async (e) => {
    e.preventDefault();
    
    if (!replyText.trim()) {
      toast.error('Comment cannot be empty');
      return;
    }
    
    try {
      const response = await axios.post(
        `/classes/${classId}/posts/${postId}/comments`,
        {
          content: replyText,
          parent_id: comment.id
        },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      // Add the new reply to the comment
      comment.replies.unshift(response.data);
      comment.reply_count = (comment.reply_count || 0) + 1;
      
      // Reset form and state
      setReplyText('');
      setReplyFormVisible(false);
      setShowReplies(true);
      
      // Update expanded state
      setExpandedReplies([...expandedReplies]);
      
      // Call parent handler if provided
      if (onReply) onReply(response.data);
      
      toast.success('Reply added');
    } catch (error) {
      console.error('Error posting reply:', error);
      toast.error('Failed to post reply');
    }
  };
  
  // Calculate padding based on depth to create indentation
  const leftPadding = depth * 20;
  
  return (
    <div className="comment-thread" style={{ marginLeft: `${leftPadding}px` }}>
      {/* Comment Header - Always visible */}
      <div 
        className={`flex items-center gap-2 p-2 rounded-t ${depth > 0 ? "border-l-2 border-gray-300 dark:border-gray-600 pl-4" : ""}`}
        onClick={toggleExpanded}
      >
        <div className="w-8 h-8 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center">
          {comment.user.first_name?.[0] || comment.user.username?.[0] || '?'}
        </div>
        <div className="flex-1">
          <div className="font-medium text-sm">
            {comment.user.first_name} {comment.user.last_name}
          </div>
          <div className="text-xs text-gray-500 dark:text-gray-400">
            {new Date(comment.created_at).toLocaleString()}
          </div>
        </div>
        <button 
          className="text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          onClick={(e) => {
            e.stopPropagation();
            toggleExpanded();
          }}
        >
          <svg className={`w-5 h-5 transition-transform ${expanded ? 'rotate-0' : 'rotate-180'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </button>
      </div>
      
      {/* Comment Content */}
      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            {/* Comment Body */}
            <div className="p-3 pt-0">
              <div className="text-sm mb-3">{comment.content}</div>
              
              {/* Comment Actions */}
              <div className="flex items-center gap-4 text-xs">
                <button 
                  onClick={handleLike}
                  className="flex items-center gap-1 text-gray-500 hover:text-red-500 dark:text-gray-400 dark:hover:text-red-400 transition-colors"
                  disabled={likeLoading}
                >
                  <div className="relative">
                    {userLiked ? (
                      <IoMdHeart className="w-4 h-4 text-red-500" />
                    ) : (
                      <IoMdHeartEmpty className="w-4 h-4" />
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
                          <IoMdHeart className="w-4 h-4 text-red-500" />
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                  {likeCount}
                </button>
                
                <button 
                  onClick={() => {
                    setReplyFormVisible(!replyFormVisible);
                    if (!replyFormVisible) setShowReplies(true);
                  }}
                  className="flex items-center gap-1 text-gray-500 hover:text-blue-500 dark:text-gray-400 dark:hover:text-blue-400 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                  </svg>
                  Reply
                </button>
              </div>
              
              {/* Reply Form */}
              <AnimatePresence>
                {replyFormVisible && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.2 }}
                    className="mt-3 overflow-hidden"
                  >
                    <form onSubmit={handleSubmitReply} className="border rounded dark:border-gray-700">
                      <textarea
                        value={replyText}
                        onChange={(e) => setReplyText(e.target.value)}
                        placeholder="Write a reply..."
                        className="w-full p-2 text-sm bg-transparent border-b dark:border-gray-700 focus:outline-none focus:border-blue-500"
                        rows={2}
                      />
                      <div className="flex justify-end p-2 gap-2">
                        <button
                          type="button"
                          onClick={() => setReplyFormVisible(false)}
                          className="px-3 py-1 text-xs rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                        >
                          Cancel
                        </button>
                        <button
                          type="submit"
                          className="px-3 py-1 text-xs bg-blue-500 text-white rounded hover:bg-blue-600"
                        >
                          Reply
                        </button>
                      </div>
                    </form>
                  </motion.div>
                )}
              </AnimatePresence>
              
              {/* Show replies toggle */}
              {comment.reply_count > 0 && (
                <div 
                  className="mt-2 text-xs text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 cursor-pointer flex items-center gap-1"
                  onClick={toggleShowReplies}
                >
                  <svg 
                    className={`w-4 h-4 transition-transform ${showReplies ? 'rotate-90' : 'rotate-0'}`} 
                    fill="none" 
                    stroke="currentColor" 
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                  </svg>
                  {showReplies ? 'Hide' : 'Show'} {comment.reply_count} {comment.reply_count === 1 ? 'reply' : 'replies'}
                </div>
              )}
              
              {/* Replies */}
              <AnimatePresence>
                {showReplies && comment.replies && comment.replies.length > 0 && (
                  <motion.div
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: 'auto', opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.3 }}
                    className="mt-3 overflow-hidden"
                  >
                    <div className="space-y-3">
                      {comment.replies.map(reply => (
                        <CommentThread
                          key={reply.id}
                          comment={reply}
                          classId={classId}
                          postId={postId}
                          token={token}
                          onReply={onReply}
                          onLike={onLike}
                          depth={depth + 1}
                          maxDepth={maxDepth}
                        />
                      ))}
                    </div>
                    
                    {/* Load more replies button */}
                    {comment.has_more_replies && (
                      <button
                        onClick={loadMoreReplies}
                        disabled={loadingMore}
                        className="mt-2 text-xs text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 flex items-center gap-1"
                      >
                        {loadingMore ? (
                          <>
                            <div className="w-3 h-3 border-2 border-t-blue-500 border-r-transparent border-b-transparent border-l-transparent rounded-full animate-spin" />
                            Loading...
                          </>
                        ) : (
                          <>
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                            </svg>
                            Load more replies
                          </>
                        )}
                      </button>
                    )}
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default CommentThread;
