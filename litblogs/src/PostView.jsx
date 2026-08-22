import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import axios from 'axios';
import Prism from 'prismjs';
import 'prismjs/themes/prism-tomorrow.css';  // Dark theme
import 'prismjs/components/prism-javascript';
import 'prismjs/components/prism-python';
import 'prismjs/components/prism-java';
import 'prismjs/components/prism-markup'; // For HTML
import 'prismjs/components/prism-css';
import 'prismjs/components/prism-sql';
import 'prismjs/components/prism-csharp';
import Loader from './components/Loader';
import './LitBlogs.css';
import { IoMdHeart, IoMdHeartEmpty } from 'react-icons/io';
import toast from 'react-hot-toast';
import CommentThread from './components/CommentThread';
import { mountInlinePdfViewers, openPdfViewerModal } from './components/PdfViewerModal';
import { formatRelativeTime, setupTimeUpdater } from './utils/timeUtils';
import { mediaPath } from './utils/urlUtils';
import { shouldAutoPlayVideos } from './utils/userSettings';
import Footer from './components/Footer';
import {
  createSanitizedRichTextContainer,
  normalizeRichTextUrl,
  serializeSanitizedRichText,
} from './utils/richTextSecurity';

const applyVideoPlaybackPreference = (video) => {
  const autoPlayEnabled = shouldAutoPlayVideos();
  video.autoplay = autoPlayEnabled;
  video.loop = autoPlayEnabled;
  video.muted = autoPlayEnabled;
  if (autoPlayEnabled) {
    video.setAttribute('playsinline', 'true');
  }
};

// Function to determine file type from URL
const getFileTypeFromUrl = (url) => {
  if (!url) return 'unknown';
  
  const extension = url.split('.').pop().toLowerCase();
  
  // Image types
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(extension)) {
    return 'image';
  }
  
  // Video types
  if (['mp4', 'webm', 'ogg', 'mov'].includes(extension)) {
    return 'video';
  }
  
  // Document types
  if (extension === 'pdf') {
    return 'pdf';
  }
  
  if (['doc', 'docx'].includes(extension)) {
    return 'word';
  }
  
  if (['xls', 'xlsx'].includes(extension)) {
    return 'excel';
  }
  
  if (['ppt', 'pptx'].includes(extension)) {
    return 'powerpoint';
  }
  
  // Text types
  if (['txt', 'md', 'json', 'xml', 'html', 'css', 'js'].includes(extension)) {
    return 'text';
  }
  
  // Default
  return 'file';
};

// Function to check if a file type is previewable
const isPreviewable = (fileType) => {
  return ['image', 'video', 'pdf', 'text'].includes(fileType);
};

const processHTMLWithDOM = (html) => {
  if (!html) return '';
  const tempContainer = createSanitizedRichTextContainer(html);
  
  // Process videos directly
  const videos = tempContainer.querySelectorAll('video');
  videos.forEach(video => {
    applyVideoPlaybackPreference(video);

    // Add styling directly to the video element
    video.style.maxWidth = '100%';
    video.style.borderRadius = '4px';
    video.style.margin = '10px 0';
    video.style.display = 'block';
    
    // Fix video sources
    const source = video.querySelector('source');
    if (source) {
      const src = source.getAttribute('src');
      if (src && src.startsWith('/uploads/')) {
        source.setAttribute('src', mediaPath(src));
      }
    }
  });
  
  // First, preserve headings by marking them
  const headings = tempContainer.querySelectorAll('h1, h2, h3, h4, h5, h6');
  headings.forEach(heading => {
    // Get the tag name to determine the heading level
    const level = heading.tagName.toLowerCase();
    heading.setAttribute('data-heading', level);
    heading.classList.add('preserved-heading');
    
    // Add size styles according to heading level
    if (level === 'h1') heading.style.fontSize = '1.8em';
    if (level === 'h2') heading.style.fontSize = '1.5em';
    if (level === 'h3') heading.style.fontSize = '1.3em';
    if (level === 'h4') heading.style.fontSize = '1.1em';
    
    heading.style.fontWeight = 'bold';
    heading.style.margin = '0.5em 0';
  });
  
  // Process all elements with font-family styles
  const elementsWithFontFamily = tempContainer.querySelectorAll('[style*="font-family"]');
  console.log("Found elements with font-family:", elementsWithFontFamily.length);
  
  elementsWithFontFamily.forEach(el => {
    // Get the original style
    const style = el.getAttribute('style');
    console.log("Original style:", style);
    
    // Extract font-family value
    const fontMatch = style.match(/font-family:\s*([^;]+)/i);
    if (fontMatch && fontMatch[1]) {
      const fontFamily = fontMatch[1].trim();
      console.log("Found font-family:", fontFamily);
      
      // Apply direct inline style with important
      el.style.setProperty('font-family', fontFamily, 'important');
      
      // Add a data attribute for CSS targeting
      el.setAttribute('data-font-family', fontFamily);
      el.classList.add('custom-font');
    }
  });
  
  // Process color styles without overriding display properties
  const elementsWithColor = tempContainer.querySelectorAll('[style*="color"]');
  elementsWithColor.forEach(el => {
    const style = el.getAttribute('style');
    const colorMatch = style.match(/(?:^|;)\s*color\s*:\s*([^;]+)/i);
    if (colorMatch && colorMatch[1]) {
      const color = colorMatch[1].trim();
      el.style.setProperty('color', color, 'important');
    }
  });
  
  // Handle background colors separately
  const elementsWithBg = tempContainer.querySelectorAll('[style*="background-color"]');
  elementsWithBg.forEach(el => {
    const style = el.getAttribute('style');
    const bgMatch = style.match(/(?:^|;)\s*background-color\s*:\s*([^;]+)/i);
    const explicitColorMatch = style.match(/(?:^|;)\s*color\s*:\s*([^;]+)/i);
    if (bgMatch && bgMatch[1]) {
      const bgColor = bgMatch[1].trim();
      el.style.setProperty('background-color', bgColor, 'important');
      // Only fallback color if no explicit text color is present.
      if (!explicitColorMatch || !explicitColorMatch[1]) {
        el.style.setProperty('color', 'inherit', 'important');
      }
    }
  });
  
  // Process images - ensure they display properly and fix URLs
  const images = tempContainer.querySelectorAll('img');
  images.forEach(img => {
    // Fix relative URLs by ensuring they start with the correct base URL
    const src = img.getAttribute('src');
    if (src && src.startsWith('/uploads/')) {
      // Make sure the URL is absolute by adding the base URL
      img.src = mediaPath(src);
    }
    
    // IMPORTANT: Do NOT override existing styles or attributes
    // Only add responsive behavior if no width/height is specified
    if (!img.style.width && !img.style.height && !img.hasAttribute('width') && !img.hasAttribute('height')) {
      img.style.maxWidth = '100%';
      img.style.height = 'auto';
    }
    
    // Preserve alignment classes
    if (img.classList.contains('float-left')) {
      img.style.float = 'left';
      img.style.marginRight = '1rem';
      img.style.marginBottom = '0.5rem';
    } else if (img.classList.contains('float-right')) {
      img.style.float = 'right';
      img.style.marginLeft = '1rem';
      img.style.marginBottom = '0.5rem';
    } else if (img.classList.contains('mx-auto') || img.classList.contains('d-block')) {
      img.style.display = 'block';
      img.style.marginLeft = 'auto';
      img.style.marginRight = 'auto';
    }
    
    // Add a base class for all images
    img.classList.add('post-image');
    
  });
  
  // Process file attachments
  const fileAttachments = tempContainer.querySelectorAll('.file-attachment');
  fileAttachments.forEach(attachment => {
    const actionsDiv = attachment.querySelector('.file-actions');
    
    // Now extract the file URL from the button if it exists
    const removeBtn = attachment.querySelector('.remove-btn');
    let fileUrl = attachment.getAttribute('data-file-url');
    
    if (!fileUrl && removeBtn) {
      fileUrl = removeBtn.getAttribute('data-file-url');
      console.log("Found URL in remove button:", fileUrl);
    }
    
    // Get the filename from the file-name div
    const fileNameDiv = attachment.querySelector('.file-name');
    let fileName = fileNameDiv ? fileNameDiv.textContent.trim() : 'download';
    
    // Clear the actions div and add the view buttons
    if (actionsDiv) {
      actionsDiv.replaceChildren();
      
      // Add preview button for supported file types
      // if (fileUrl && isPreviewable(getFileTypeFromUrl(fileUrl))) {
      //   const previewBtn = document.createElement('button');
      //   previewBtn.className = 'preview-btn';
      //   previewBtn.textContent = 'Preview';
      //   previewBtn.setAttribute('type', 'button');
      //   previewBtn.style.padding = '4px 8px';
      //   previewBtn.style.borderRadius = '4px';
      //   previewBtn.style.fontSize = '12px';
      //   previewBtn.style.cursor = 'pointer';
      //   previewBtn.style.backgroundColor = '#e0f2fe';
      //   previewBtn.style.color = '#0369a1';
      //   previewBtn.style.border = '1px solid #bae6fd';
      //   previewBtn.style.marginRight = '4px';
        
      //   // Simplified preview function
      //   previewBtn.addEventListener('click', function() {
      //     const fileType = getFileTypeFromUrl(fileUrl);
      //     const fullUrl = mediaPath(fileUrl);
          
      //     // Create modal for preview
      //     const modal = document.createElement('div');
      //     modal.style.position = 'fixed';
      //     modal.style.top = '0';
      //     modal.style.left = '0';
      //     modal.style.width = '100%';
      //     modal.style.height = '100%';
      //     modal.style.backgroundColor = 'rgba(0,0,0,0.8)';
      //     modal.style.zIndex = '9999';
      //     modal.style.display = 'flex';
      //     modal.style.alignItems = 'center';
      //     modal.style.justifyContent = 'center';
          
      //     // Create close button
      //     const closeBtn = document.createElement('button');
      //     closeBtn.textContent = '×';
      //     closeBtn.style.position = 'absolute';
      //     closeBtn.style.top = '20px';
      //     closeBtn.style.right = '20px';
      //     closeBtn.style.fontSize = '30px';
      //     closeBtn.style.color = 'white';
      //     closeBtn.style.background = 'none';
      //     closeBtn.style.border = 'none';
      //     closeBtn.style.cursor = 'pointer';
      //     closeBtn.onclick = function() {
      //       document.body.removeChild(modal);
      //     };
          
      //     // Create content container
      //     const content = document.createElement('div');
      //     content.style.maxWidth = '90%';
      //     content.style.maxHeight = '90%';
      //     content.style.overflow = 'auto';
      //     content.style.backgroundColor = 'white';
      //     content.style.borderRadius = '8px';
      //     content.style.padding = '20px';
          
      //     // Add content based on file type
      //     if (fileType === 'image') {
      //       const img = document.createElement('img');
      //       img.src = fullUrl;
      //       img.style.maxWidth = '100%';
      //       content.appendChild(img);
      //     } else if (fileType === 'video') {
      //       const video = document.createElement('video');
      //       video.src = fullUrl;
      //       video.controls = true;
      //       video.style.maxWidth = '100%';
      //       content.appendChild(video);
      //     } else if (fileType === 'pdf') {
      //       const iframe = document.createElement('iframe');
      //       iframe.src = fullUrl;
      //       iframe.style.width = '800px';
      //       iframe.style.height = '600px';
      //       content.appendChild(iframe);
      //     } else if (fileType === 'text') {
      //       // For text files, fetch and display content
      //       fetch(fullUrl)
      //         .then(response => response.text())
      //         .then(text => {
      //           const pre = document.createElement('pre');
      //           pre.style.whiteSpace = 'pre-wrap';
      //           pre.style.fontFamily = 'monospace';
      //           pre.textContent = text;
      //           content.appendChild(pre);
      //         });
      //     } else {
      //       // For unsupported preview types
      //       const message = document.createElement('p');
      //       message.textContent = 'Preview not available for this file type. Please download the file to view it.';
      //       content.appendChild(message);
      //     }
          
      //     modal.appendChild(closeBtn);
      //     modal.appendChild(content);
      //     document.body.appendChild(modal);
      //   });
        
      //   actionsDiv.appendChild(previewBtn);
      // }
      
      // Add preview and open actions
      if (fileUrl) {
        const fullUrl = normalizeRichTextUrl(fileUrl, 'attachment');
        if (!fullUrl) {
          return;
        }
        const fileType = getFileTypeFromUrl(fileUrl);

        if (fileType === 'pdf') {
          const pdfContainer = document.createElement('div');
          pdfContainer.setAttribute('data-inline-pdf-viewer', 'true');
          pdfContainer.setAttribute('data-pdf-url', fullUrl);
          pdfContainer.setAttribute('data-pdf-title', fileName || 'PDF Document');
          pdfContainer.style.width = '100%';
          pdfContainer.style.display = 'block';
          attachment.replaceWith(pdfContainer);
          return;
        }

        if (isPreviewable(fileType)) {
          const previewBtn = document.createElement('button');
          previewBtn.className = 'preview-btn';
          previewBtn.textContent = 'Preview';
          previewBtn.setAttribute('type', 'button');
          previewBtn.style.padding = '4px 8px';
          previewBtn.style.borderRadius = '4px';
          previewBtn.style.fontSize = '12px';
          previewBtn.style.cursor = 'pointer';
          previewBtn.style.backgroundColor = '#e0f2fe';
          previewBtn.style.color = '#0369a1';
          previewBtn.style.border = '1px solid #bae6fd';
          previewBtn.style.marginRight = '4px';
          previewBtn.addEventListener('click', function() {
            if (typeof window.previewFile === 'function') {
              window.previewFile(fullUrl, fileType);
            }
          });
          actionsDiv.appendChild(previewBtn);
        }

        const openBtn = document.createElement('a');
        openBtn.className = 'download-btn';
        openBtn.textContent = 'Open';
        openBtn.style.padding = '4px 8px';
        openBtn.style.borderRadius = '4px';
        openBtn.style.fontSize = '12px';
        openBtn.style.cursor = 'pointer';
        openBtn.style.backgroundColor = '#e6fffa';
        openBtn.style.color = '#319795';
        openBtn.style.border = '1px solid #b2f5ea';
        openBtn.style.marginLeft = '4px';
        openBtn.style.textDecoration = 'none';
        openBtn.style.display = 'inline-block';
        openBtn.href = fullUrl;
        openBtn.target = '_blank';
        openBtn.rel = 'noopener noreferrer';

        actionsDiv.appendChild(openBtn);
      }
    }
  });
  
  // Process video elements
  const videoWrappers = tempContainer.querySelectorAll('.video-wrapper');
  videoWrappers.forEach(wrapper => {
    // Remove the delete overlay when viewing
    const deleteOverlay = wrapper.querySelector('.video-delete-overlay');
    if (deleteOverlay) {
      deleteOverlay.remove();
    }
    
    // Fix video URLs if needed
    const video = wrapper.querySelector('video');
    if (video) {
      const source = video.querySelector('source');
      if (source) {
        // First try to get URL from source src attribute
        let videoUrl = source.getAttribute('src');
        
        // If undefined or empty, try to get from the hidden data div
        if (!videoUrl || videoUrl === 'undefined') {
          const videoData = wrapper.querySelector('.video-data');
          if (videoData) {
            videoUrl = videoData.getAttribute('data-video-url');
            const videoType = videoData.getAttribute('data-video-type');
            
            if (videoUrl) {
              // Update the source with the correct URL and type
              source.setAttribute('src', videoUrl);
              if (videoType) {
                source.setAttribute('type', videoType);
              }
            }
          }
        }
        
        // Make sure the URL is absolute
        if (videoUrl && videoUrl.startsWith('/uploads/')) {
          videoUrl = mediaPath(videoUrl);
          source.setAttribute('src', videoUrl);
        }
        
        // Reload the video to apply changes
        video.load();
      }
    }
  });
  
  // Also handle direct video tags (not in wrappers)
  const videosDirect = tempContainer.querySelectorAll('video:not(.video-wrapper video)');
  videosDirect.forEach(video => {
    // Fix video URLs if needed
    const source = video.querySelector('source');
    if (source) {
      const src = source.getAttribute('src');
      if (src) {
        // Make sure the URL is absolute
        if (src.startsWith('/uploads/')) {
          source.setAttribute('src', mediaPath(src));
        }
        
        // Ensure the video has proper styling
        video.style.maxWidth = '100%';
        video.style.borderRadius = '4px';
        video.style.margin = '10px 0';
        
        // Reload the video to apply changes
        video.load();
      }
    }
  });
  
  // User-supplied controls were removed when the container was created. Keep
  // only the inert preview controls constructed above during final serialization.
  return serializeSanitizedRichText(tempContainer, { mode: 'editor' });
};

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
  const contentRef = useRef(null);

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
        
        // Apply syntax highlighting after content is loaded
        setTimeout(() => {
          Prism.highlightAll();
        }, 100);
        
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
    if (typeof window !== 'undefined') {
      const highlight = async () => {
        await new Promise(resolve => setTimeout(resolve, 0));
        Prism.highlightAll();
      };
      highlight();
    }
  }, [post]);

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

  // Add these styles to your richTextStyles in PostView.jsx
  const richTextStyles = `
    .prose {
      max-width: none;
    }
    
    .prose * {
      font-family: inherit;
    }

    /* Let TinyMCE inline styles render naturally in full post view */
    .prose [style*="color:"],
    .prose [style*="background-color:"],
    .prose [style*="font-size:"],
    .prose [style*="font-family:"],
    .prose [style*="text-decoration:"],
    .prose [style*="font-weight:"],
    .prose [style*="font-style:"] {
      all: revert;
    }

    /* Basic formatting */
    .prose u {
      text-decoration: underline !important;
    }
    
    .prose s, .prose strike, .prose del {
      text-decoration: line-through !important;
    }
    
    .prose b, .prose strong {
      font-weight: bold !important;
    }
    
    .prose i, .prose em {
      font-style: italic !important;
    }
    
    /* Image styles */
    .post-image {
      max-width: 100%;
      height: auto;
      margin-bottom: 1rem;
      border-radius: 0.375rem;
    }
    
    /* File attachment styles */
    .file-attachment {
      display: flex;
      align-items: center;
      padding: 10px;
      margin: 10px 0;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      background-color: #f9f9f9;
    }
    
    .dark .file-attachment {
      background-color: rgba(255, 255, 255, 0.05);
      border-color: rgba(255, 255, 255, 0.1);
    }
    
    .file-attachment .file-icon {
      margin-right: 12px;
      font-size: 24px;
      color: #4a5568;
    }
    
    .file-attachment .file-info {
      flex-grow: 1;
    }
    
    .file-attachment .file-name {
      font-weight: 500;
      margin-bottom: 2px;
    }
    
    .file-attachment .file-size {
      font-size: 12px;
      color: #718096;
    }
    
    .file-attachment .file-actions {
      display: flex;
      gap: 8px;
    }
    
    .file-attachment .file-actions button {
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 12px;
      cursor: pointer;
    }
    
    .file-attachment .preview-btn {
      background-color: #ebf8ff;
      color: #3182ce;
      border: 1px solid #bee3f8;
    }
    
    .file-attachment .download-btn {
      background-color: #e6fffa;
      color: #319795;
      border: 1px solid #b2f5ea;
    }
    
    .dark .file-attachment .preview-btn {
      background-color: rgba(49, 130, 206, 0.2);
      border-color: rgba(190, 227, 248, 0.3);
    }
    
    .dark .file-attachment .download-btn {
      background-color: rgba(49, 151, 149, 0.2);
      border-color: rgba(178, 245, 234, 0.3);
    }

    /* Image alignment classes */
    img.float-left {
      float: left;
      margin-right: 1rem;
      margin-bottom: 0.5rem;
    }
    
    img.float-right {
      float: right;
      margin-left: 1rem;
      margin-bottom: 0.5rem;
    }
    
    img.mx-auto.d-block {
      display: block;
      margin-left: auto;
      margin-right: auto;
    }
    
    /* Clear floats after images */
    .html-content::after {
      content: "";
      clear: both;
      display: table;
    }
    
    /* Preserve width/height attributes */
    img[width], img[height] {
      width: auto;
      height: auto;
      max-width: 100%;
    }
    
    /* Preserve inline styles */
    img[style] {
      /* This ensures inline styles take precedence */
    }

    /* Video styles */
    .html-content video {
      width: min(100%, 860px) !important;
      max-width: 100% !important;
      height: auto !important;
      aspect-ratio: 16 / 9;
      object-fit: contain;
      border-radius: 8px !important;
      margin: 20px 0 !important;
      display: block !important;
      background-color: #000 !important;
    }
    
    .html-content .video-container {
      margin: 20px 0 !important;
      position: relative !important;
    }
    
    /* Force controls to be visible */
    .html-content video::-webkit-media-controls {
      display: flex !important;
      visibility: visible !important;
      opacity: 1 !important;
    }
    
    .html-content video::-webkit-media-controls-enclosure {
      display: flex !important;
      visibility: visible !important;
      opacity: 1 !important;
    }
  `;

  useEffect(() => {
    // Always register the page-level preview handler so attachments use this implementation.
    window.previewFile = function(url, type) {
        if (type === 'pdf') {
          openPdfViewerModal({ fileUrl: url, title: 'PDF Preview' });
          return;
        }

        // Create modal for preview
        const modal = document.createElement('div');
        modal.style.position = 'fixed';
        modal.style.top = '0';
        modal.style.left = '0';
        modal.style.width = '100%';
        modal.style.height = '100%';
        modal.style.backgroundColor = 'rgba(0,0,0,0.8)';
        modal.style.zIndex = '9999';
        modal.style.display = 'flex';
        modal.style.alignItems = 'center';
        modal.style.justifyContent = 'center';
        
        // Create close button
        const closeBtn = document.createElement('button');
        closeBtn.textContent = '×';
        closeBtn.style.position = 'absolute';
        closeBtn.style.top = '20px';
        closeBtn.style.right = '20px';
        closeBtn.style.fontSize = '30px';
        closeBtn.style.color = 'white';
        closeBtn.style.background = 'none';
        closeBtn.style.border = 'none';
        closeBtn.style.cursor = 'pointer';
        closeBtn.onclick = function() {
          document.body.removeChild(modal);
        };
        
        // Create content container
        const content = document.createElement('div');
        content.style.maxWidth = '90%';
        content.style.maxHeight = '90%';
        content.style.overflow = 'auto';
        content.style.backgroundColor = 'white';
        content.style.borderRadius = '8px';
        content.style.padding = '20px';
        
        // Add content based on file type
        if (type === 'image') {
          const img = document.createElement('img');
          img.src = url;
          img.style.maxWidth = '100%';
          content.appendChild(img);
        } else if (type === 'video') {
          const video = document.createElement('video');
          video.src = url;
          video.controls = true;
          applyVideoPlaybackPreference(video);
          video.style.maxWidth = '100%';
          content.appendChild(video);
        } else if (type === 'text') {
          // For text files, fetch and display content
          fetch(url)
            .then(response => response.text())
            .then(text => {
              const pre = document.createElement('pre');
              pre.style.whiteSpace = 'pre-wrap';
              pre.style.fontFamily = 'monospace';
              pre.textContent = text;
              content.appendChild(pre);
            });
        } else {
          // For unsupported preview types
          const message = document.createElement('p');
          message.textContent = 'Preview not available for this file type. Please download the file to view it.';
          content.appendChild(message);
        }
        
        modal.appendChild(closeBtn);
        modal.appendChild(content);
        document.body.appendChild(modal);
      };
    
    // Set up the time updater when the component mounts
    const timeUpdateInterval = setupTimeUpdater();
    
    // Clean up the interval when the component unmounts
    return () => clearInterval(timeUpdateInterval);
  }, []);

  useEffect(() => {
    if (contentRef.current && post && post.content) {
      // Process videos after the content is rendered
      const videoElements = contentRef.current.querySelectorAll('video');
      console.log("Found video elements after render:", videoElements.length);
      
      videoElements.forEach(video => {
        applyVideoPlaybackPreference(video);

        // Ensure the video has proper styling
        video.style.maxWidth = '100%';
        video.style.borderRadius = '4px';
        video.style.margin = '10px 0';
        video.style.display = 'block';
        
        // Fix video sources
        const source = video.querySelector('source');
        if (source) {
          const src = source.getAttribute('src');
          if (src && src.startsWith('/uploads/')) {
            source.setAttribute('src', mediaPath(src));
            // Force the video to reload with the new source
            video.load();
          }
        }
      });

      const cleanupInlinePdfViewers = mountInlinePdfViewers(contentRef.current);
      return () => {
        cleanupInlinePdfViewers();
      };
    }
  }, [post?.content]);

  // Update the forceRenderVideos function to remove delete buttons

  const forceRenderVideos = () => {
    // Get the content container
    const contentDiv = document.querySelector('.html-content');
    if (!contentDiv) return;
    
    console.log("Forcing video rendering...");
    
    // First, remove any delete buttons or editor controls
    const deleteButtons = contentDiv.querySelectorAll('.video-delete-btn, .editor-only-control');
    deleteButtons.forEach(button => {
      button.remove();
    });
    
    // Look for any text that contains video tags (encoded or not)
    const htmlContent = contentDiv.innerHTML;
    
    // First, try to find any encoded video tags
    if (htmlContent.includes('&lt;video') || htmlContent.includes('<video')) {
      console.log("Found video tags in content");
      
      const tempDiv = createSanitizedRichTextContainer(htmlContent);
      
      // Remove any delete buttons again (in case they were in the decoded HTML)
      const moreDeleteButtons = tempDiv.querySelectorAll('.video-delete-btn, .editor-only-control');
      moreDeleteButtons.forEach(button => {
        button.remove();
      });
      
      // Find all video elements in the content
      const videoElements = tempDiv.querySelectorAll('video');
      console.log("Found video elements:", videoElements.length);
      
      if (videoElements.length > 0) {
        // Process each video element without clearing the content
        videoElements.forEach((video, index) => {
          // Get the parent element (wrapper or container)
          const videoParent = video.parentElement;
          const isWrapper = videoParent.classList.contains('video-wrapper') || 
                            videoParent.classList.contains('mceNonEditable');
          
          // Get the source element
          const source = video.querySelector('source');
          if (!source) return;
          
          // Get the source URL
          const srcUrl = normalizeRichTextUrl(source.getAttribute('src'), 'video');
          if (!srcUrl) return;
          
          // Get the video type
          const videoType = source.getAttribute('type') || 'video/mp4';
          
          // Create a new video element with proper attributes
          const newVideo = document.createElement('video');
          newVideo.controls = true;
          applyVideoPlaybackPreference(newVideo);
          newVideo.width = '100%';
          newVideo.style.maxWidth = '600px';
          newVideo.style.display = 'block';
          newVideo.style.borderRadius = '8px';
          newVideo.style.backgroundColor = '#000';
          newVideo.style.margin = '10px 0';
          
          // Create a new source element
          const newSource = document.createElement('source');
          newSource.src = srcUrl;
          newSource.type = videoType;
          
          // Add source to video
          newVideo.appendChild(newSource);
          
          // Add fallback text
          newVideo.appendChild(document.createTextNode('Your browser does not support the video tag.'));
          
          // Create a container for the video if it's not already in one
          let newContainer;
          if (isWrapper) {
            // If it's already in a wrapper, replace just the video
            videoParent.replaceChild(newVideo, video);
            
            // Remove any delete overlay
            const deleteOverlay = videoParent.querySelector('.video-delete-overlay');
            if (deleteOverlay) {
              deleteOverlay.remove();
            }
          } else {
            // Create a new container
            newContainer = document.createElement('div');
            newContainer.className = 'video-container';
            newContainer.style.margin = '20px 0';
            newContainer.appendChild(newVideo);
            
            // Replace the old video with the new container
            videoParent.replaceChild(newContainer, video);
          }
          
          console.log(`Processed video ${index} with source:`, srcUrl);
          
          // Force the video to load
          newVideo.load();
        });
        
        // Update the content with the processed HTML
        contentDiv.replaceChildren(...tempDiv.childNodes);
        
        return true; // Videos were rendered
      }
    }
    
    return false; // No videos were rendered
  };

  // Call this function after the content is rendered
  useEffect(() => {
    if (post?.content) {
      // Wait for the DOM to update
      setTimeout(() => {
        const videosRendered = forceRenderVideos();
        
        if (!videosRendered) {
          // If no videos were rendered by our function, try the other methods
          fixVideoHtmlEntities();
        }
      }, 300);
    }
  }, [post?.content]);

  // Update the fixVideoHtmlEntities function to properly handle video controls
  const fixVideoHtmlEntities = () => {
    // Find all elements that might contain encoded video tags
    const contentDiv = document.querySelector('.html-content');
    if (!contentDiv) return;
    
    // Look for text that contains encoded video tags
    const htmlContent = contentDiv.innerHTML;
    
    // Check if there are encoded video tags
    if (htmlContent.includes('&lt;video') && htmlContent.includes('&lt;/video&gt;')) {
      console.log("Found encoded video tags, fixing...");
      
      const decodedContainer = createSanitizedRichTextContainer(htmlContent);
      contentDiv.replaceChildren(...decodedContainer.childNodes);
      
      // Now find and fix all videos
      const videos = contentDiv.querySelectorAll('video');
      console.log("Found videos after decoding:", videos.length);
      
      videos.forEach((video, index) => {
        console.log(`Processing video ${index}:`, video.outerHTML);
        
        // Ensure the video has controls attribute
        if (!video.hasAttribute('controls')) {
          video.setAttribute('controls', 'true');
        }
        applyVideoPlaybackPreference(video);
        
        // Make sure the video has proper styling
        video.style.maxWidth = '100%';
        video.style.borderRadius = '4px';
        video.style.margin = '10px 0';
        video.style.display = 'block';
        
        // Fix video sources
        const source = video.querySelector('source');
        if (source) {
          const src = normalizeRichTextUrl(source.getAttribute('src'), 'video');
          if (src) {
            source.setAttribute('src', src);
            console.log(`Video ${index} source:`, source.getAttribute('src'));
          }
        }
        
        // Force the video to reload with the new attributes
        try {
          video.load();
          console.log(`Video ${index} reloaded`);
        } catch (e) {
          console.error(`Error reloading video ${index}:`, e);
        }
      });
    }
    
    // Also check for videos that might already be in the DOM but missing controls
    const existingVideos = contentDiv.querySelectorAll('video');
    existingVideos.forEach((video, index) => {
      applyVideoPlaybackPreference(video);

      if (!video.hasAttribute('controls')) {
        video.setAttribute('controls', 'true');
        video.load();
        console.log(`Added controls to existing video ${index}`);
      }
    });
  };

  // Add this to your CSS in PostView.jsx
  const postViewStyles = `
    .video-delete-btn, 
    .editor-only-control,
    .video-delete-overlay {
      display: none !important;
      visibility: hidden !important;
      opacity: 0 !important;
      pointer-events: none !important;
    }
    
    .video-container {
      position: relative;
      margin: 1rem 0;
    }
    
    video {
      max-width: 100%;
      border-radius: 8px;
    }
  `;

  // Add this to your useEffect
  useEffect(() => {
    // Add the styles to the document
    const styleElement = document.createElement('style');
    styleElement.textContent = postViewStyles;
    document.head.appendChild(styleElement);
    
    return () => {
      // Clean up on unmount
      styleElement.remove();
    };
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
              <style dangerouslySetInnerHTML={{ __html: richTextStyles }} />
              <div 
                className="html-content"
                dangerouslySetInnerHTML={{ 
                  __html: processHTMLWithDOM(post.content)
                }}
                ref={contentRef}
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

