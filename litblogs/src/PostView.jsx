import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
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
import ReactHtmlParser from 'react-html-parser';
import Loader from './components/Loader';
import './LitBlogs.css';
import { IoMdHeart, IoMdHeartEmpty } from 'react-icons/io';
import toast from 'react-hot-toast';
import CommentThread from './components/CommentThread';
import { formatRelativeTime, setupTimeUpdater } from './utils/timeUtils';

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

// Function to get file icon based on type
const getFileIcon = (fileType) => {
  switch (fileType) {
    case 'image':
      return '🖼️';
    case 'video':
      return '🎬';
    case 'pdf':
      return '📄';
    case 'word':
      return '📝';
    case 'excel':
      return '📊';
    case 'powerpoint':
      return '📑';
    case 'text':
      return '📃';
    default:
      return '📁';
  }
};

// Add this helper function to decode HTML entities
const decodeHTMLEntities = (html) => {
  const textarea = document.createElement('textarea');
  textarea.innerHTML = html;
  return textarea.value;
};

const processHTMLWithDOM = (html) => {
  if (!html) return '';
  
  // Check if the HTML contains video tags as text
  if (html.includes('<video') && html.includes('</video>')) {
    // Create a temporary div to parse the HTML
    const tempContainer = document.createElement('div');
    tempContainer.innerHTML = html;
    
    // Find all text nodes that might contain video tags
    const findTextNodesWithVideos = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.textContent.includes('<video') && node.textContent.includes('</video>')) {
          // Replace the text node with actual HTML
          const tempDiv = document.createElement('div');
          tempDiv.innerHTML = node.textContent;
          
          // Replace the text node with the parsed HTML
          node.parentNode.replaceChild(tempDiv, node);
        }
      } else if (node.nodeType === Node.ELEMENT_NODE) {
        // Recursively process child nodes
        Array.from(node.childNodes).forEach(findTextNodesWithVideos);
      }
    };
    
    // Process all nodes
    findTextNodesWithVideos(tempContainer);
    
    // Continue with the rest of the processing
    // ...
    
    return tempContainer.innerHTML;
  }
  
  // Create a temporary div to parse the HTML
  const tempContainer = document.createElement('div');
  tempContainer.innerHTML = html;
  
  // Process videos directly
  const videos = tempContainer.querySelectorAll('video');
  videos.forEach(video => {
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
        source.setAttribute('src', `http://localhost:8000${src}`);
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
    const colorMatch = style.match(/color:\s*([^;]+)/i);
    if (colorMatch && colorMatch[1]) {
      const color = colorMatch[1].trim();
      el.style.setProperty('color', color, 'important');
    }
  });
  
  // Handle background colors separately
  const elementsWithBg = tempContainer.querySelectorAll('[style*="background-color"]');
  elementsWithBg.forEach(el => {
    const style = el.getAttribute('style');
    const bgMatch = style.match(/background-color:\s*([^;]+)/i);
    if (bgMatch && bgMatch[1]) {
      const bgColor = bgMatch[1].trim();
      el.style.setProperty('background-color', bgColor, 'important');
      // Make sure text remains visible with highlighting
      el.style.setProperty('color', 'inherit', 'important');
    }
  });
  
  // Process images - ensure they display properly and fix URLs
  const images = tempContainer.querySelectorAll('img');
  images.forEach(img => {
    // Fix relative URLs by ensuring they start with the correct base URL
    const src = img.getAttribute('src');
    if (src && src.startsWith('/uploads/')) {
      // Make sure the URL is absolute by adding the base URL
      img.src = `http://localhost:8000${src}`;
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
    
    // Add error handling for images
    img.onerror = "this.onerror=null; this.src='/placeholder-image.png'; this.alt='Image failed to load';";
  });
  
  // Process file attachments
  const fileAttachments = tempContainer.querySelectorAll('.file-attachment');
  fileAttachments.forEach(attachment => {
    // Check if the file-actions div contains encoded HTML
    const actionsDiv = attachment.querySelector('.file-actions');
    if (actionsDiv && actionsDiv.innerHTML.includes('&lt;button')) {
      // The HTML is encoded, decode it
      actionsDiv.innerHTML = decodeHTMLEntities(actionsDiv.innerHTML);
    }
    
    // Now extract the file URL from the button if it exists
    const removeBtn = attachment.querySelector('.remove-btn');
    let fileUrl = null;
    
    if (removeBtn) {
      fileUrl = removeBtn.getAttribute('data-file-url');
      console.log("Found URL in remove button:", fileUrl);
    }
    
    // Get the filename from the file-name div
    const fileNameDiv = attachment.querySelector('.file-name');
    let fileName = fileNameDiv ? fileNameDiv.textContent.trim() : 'download';
    
    // Clear the actions div and add the view buttons
    if (actionsDiv) {
      actionsDiv.innerHTML = '';
      
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
      //     const fullUrl = fileUrl.startsWith('http') ? fileUrl : `http://localhost:8000${fileUrl}`;
          
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
      //     closeBtn.innerHTML = '&times;';
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
      
      // Add download button - make it a direct link with token
      if (fileUrl) {
        const downloadBtn = document.createElement('a');
        downloadBtn.className = 'download-btn';
        downloadBtn.textContent = 'Preview';
        downloadBtn.style.padding = '4px 8px';
        downloadBtn.style.borderRadius = '4px';
        downloadBtn.style.fontSize = '12px';
        downloadBtn.style.cursor = 'pointer';
        downloadBtn.style.backgroundColor = '#e0f2fe';
        downloadBtn.style.color = '#0369a1';
        downloadBtn.style.border = '1px solid #bae6fd';
        downloadBtn.style.marginLeft = '4px';
        downloadBtn.style.textDecoration = 'none';
        downloadBtn.style.display = 'inline-block';
        
        // Set the href to directly download the file
        const fullUrl = fileUrl.startsWith('http') ? fileUrl : `http://localhost:8000${fileUrl}`;
        downloadBtn.href = fullUrl;
        downloadBtn.download = fileName; // This tells the browser to download instead of navigate
        downloadBtn.target = '_blank'; // Open in new tab as fallback
        
        actionsDiv.appendChild(downloadBtn);
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
          videoUrl = `http://localhost:8000${videoUrl}`;
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
          source.setAttribute('src', `http://localhost:8000${src}`);
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
  
  // Add this debugging code to the processHTMLWithDOM function
  console.log("Original HTML:", html);
  console.log("Processed HTML:", tempContainer.innerHTML);

  // Also add specific debugging for videos
  const allVideos = tempContainer.querySelectorAll('video');
  console.log("Found videos:", allVideos.length);
  allVideos.forEach((video, index) => {
    console.log(`Video ${index} HTML:`, video.outerHTML);
  });
  
  return tempContainer.innerHTML;
};

const PostView = () => {
  const { classId, postId } = useParams();
  const navigate = useNavigate();
  const [post, setPost] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userInfo, setUserInfo] = useState(null);
  const [darkMode, setDarkMode] = useState(false);
  const [liked, setLiked] = useState(false);
  const [likeCount, setLikeCount] = useState(0);
  const [likeLoading, setLikeLoading] = useState(false);
  const [showLikeEffect, setShowLikeEffect] = useState(false);
  const [comments, setComments] = useState([]);
  const [totalComments, setTotalComments] = useState(0);
  const [hasMoreComments, setHasMoreComments] = useState(false);
  const [commentsLoading, setCommentsLoading] = useState(true);
  const [commentsExpanded, setCommentsExpanded] = useState(false);
  const [newComment, setNewComment] = useState('');
  const [commentSubmitting, setCommentSubmitting] = useState(false);
  const contentRef = useRef(null);

  // Add this state
  const [isTeacher, setIsTeacher] = useState(false);

  const toggleDarkMode = () => {
    setDarkMode((prevDarkMode) => {
      const newDarkMode = !prevDarkMode;
      localStorage.setItem('darkMode', JSON.stringify(newDarkMode));
      return newDarkMode;
    });
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
    // Load user info
    const storedUserInfo = localStorage.getItem('user_info');
    if (storedUserInfo) {
      setUserInfo(JSON.parse(storedUserInfo));
    }

    const fetchPost = async () => {
      try {
        setLoading(true);
        const token = localStorage.getItem('token');
        
        // Fetch the post
        const response = await axios.get(`http://localhost:8000/api/classes/${classId}/posts/${postId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        
        // Get user info from localStorage
        const userInfoStr = localStorage.getItem('userInfo');
        if (userInfoStr) {
          const parsedUserInfo = JSON.parse(userInfoStr);
          setUserInfo(parsedUserInfo);
        }
        
        // Process the post data
        const postData = response.data;
        
        // Set the post data
        setPost(postData);
        
        // Set like status
        setLiked(postData.user_liked || false);
        setLikeCount(postData.likes || 0);
        
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
    if (post && post.content) {
      console.log("Post Content:", post.content);
      
      // Check for font-family styles
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = post.content;
      
      const elements = tempDiv.querySelectorAll('[style*="font-family"]');
      console.log("Elements with font-family:", elements.length);
      
      elements.forEach(el => {
        console.log("Font family style:", el.getAttribute('style'));
      });
    }
  }, [post]);

  useEffect(() => {
    const fetchLikes = async () => {
      if (!post || !post.id) return;
      
      try {
        const token = localStorage.getItem('token');
        const response = await axios.get(`http://localhost:8000/api/classes/${classId}/posts/${post.id}/likes`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        
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
      const token = localStorage.getItem('token');
      const response = await axios.get(
        `http://localhost:8000/api/classes/${classId}/posts/${postId}/comments?skip=${skip}&limit=5`,
        { headers: { Authorization: `Bearer ${token}` } }
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
    if (userInfo?.role === 'TEACHER') {
      navigate('/teacher-dashboard');
    } else {
      navigate(`/class-feed/${classId}`);
    }
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
      const token = localStorage.getItem('token');
      const response = await axios.post(`http://localhost:8000/api/classes/${classId}/posts/${post.id}/like`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      // Update with actual data
      setLiked(response.data.action === 'liked');
      setLikeCount(response.data.like_count);
    } catch (error) {
      console.error('Error liking post:', error);
      toast.error('Failed to like post');
      
      // Revert on error
      const token = localStorage.getItem('token');
      const response = await axios.get(`http://localhost:8000/api/classes/${classId}/posts/${post.id}/likes`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
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
      const token = localStorage.getItem('token');
      const response = await axios.post(
        `http://localhost:8000/api/classes/${classId}/posts/${postId}/comments`,
        { content: newComment },
        { headers: { Authorization: `Bearer ${token}` } }
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

  const handleLoadMoreComments = () => {
    fetchComments(comments.length);
  };

  const handleCommentReply = (newReply) => {
    // No need to update state as the child component handles displaying the reply
    // Just update the total count
    setTotalComments(totalComments + 1);
  };

  const handleCommentLike = (commentId, newLikeCount, isLiked) => {
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

    /* Remove Tailwind prose color overrides */
    .prose :where(p, span, div, strong, em, b, i, u, strike):not(:where([class~="not-prose"] *)) {
      color: unset !important;
    }

    /* Preserve inline styles */
    .prose [style] {
      color: unset !important;
    }

    .prose span[style*="color:"] {
      color: var(--mce-color) !important;
    }

    .prose span[style*="background-color:"] {
      background-color: var(--mce-bg) !important;
    }

    .prose span[style*="font-size:"] {
      font-size: var(--mce-size) !important;
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
      border-radius:background-color: #f9f9f9;
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
      max-width: 600px !important;
      width: 100% !important;
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
8px;
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
      max-width: 600px !important;
      width: 100% !important;
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
    // Add global function for file preview if it doesn't exist
    if (!window.previewFile) {
      window.previewFile = function(url, type) {
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
        closeBtn.innerHTML = '&times;';
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
          video.style.maxWidth = '100%';
          content.appendChild(video);
        } else if (type === 'pdf') {
          const iframe = document.createElement('iframe');
          iframe.src = url;
          iframe.style.width = '800px';
          iframe.style.height = '600px';
          content.appendChild(iframe);
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
    }
    
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
            source.setAttribute('src', `http://localhost:8000${src}`);
            // Force the video to reload with the new source
            video.load();
          }
        }
      });
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
      
      // Create a temporary container to parse the content
      const tempDiv = document.createElement('div');
      
      // First decode any HTML entities
      let decodedHtml = htmlContent
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, '&');
      
      tempDiv.innerHTML = decodedHtml;
      
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
          let srcUrl = source.getAttribute('src');
          if (!srcUrl) return;
          
          // Fix the source URL if needed
          if (srcUrl.startsWith('/uploads/')) {
            srcUrl = `http://localhost:8000${srcUrl}`;
          }
          
          // Get the video type
          const videoType = source.getAttribute('type') || 'video/mp4';
          
          // Create a new video element with proper attributes
          const newVideo = document.createElement('video');
          newVideo.controls = true;
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
        contentDiv.innerHTML = tempDiv.innerHTML;
        
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
      
      // Replace the encoded HTML with decoded HTML
      const decodedHtml = htmlContent
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, '&');
      
      // Update the content
      contentDiv.innerHTML = decodedHtml;
      
      // Now find and fix all videos
      const videos = contentDiv.querySelectorAll('video');
      console.log("Found videos after decoding:", videos.length);
      
      videos.forEach((video, index) => {
        console.log(`Processing video ${index}:`, video.outerHTML);
        
        // Ensure the video has controls attribute
        if (!video.hasAttribute('controls')) {
          video.setAttribute('controls', 'true');
        }
        
        // Make sure the video has proper styling
        video.style.maxWidth = '100%';
        video.style.borderRadius = '4px';
        video.style.margin = '10px 0';
        video.style.display = 'block';
        
        // Fix video sources
        const source = video.querySelector('source');
        if (source) {
          const src = source.getAttribute('src');
          if (src) {
            // Make sure the URL is absolute
            if (src.startsWith('/uploads/')) {
              source.setAttribute('src', `http://localhost:8000${src}`);
            }
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

  useEffect(() => {
    // Get user info from localStorage
    const userInfo = JSON.parse(localStorage.getItem('user_info') || '{}');
    setIsTeacher(userInfo?.role === 'TEACHER');
    
    // Only fetch AI detection for teachers
    if (userInfo?.role === 'TEACHER') {
      fetchAiDetection();
    }
    
    // Rest of your existing code...
  }, [postId, classId]);

  // Update the AI detection UI section
  {isTeacher && aiDetection && (
    <div className="mb-4">
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold">AI Detection Results</h3>
        <button
          onClick={() => setShowAiAnalysis(!showAiAnalysis)}
          className="text-blue-500 hover:text-blue-700"
        >
          {showAiAnalysis ? "Hide Analysis" : "Show Analysis"}
        </button>
      </div>
      
      <div className={`flex items-center mt-2 ${
        aiDetection.status === 'pending' ? 'text-gray-500' :
        aiDetection.is_ai ? 'text-red-600' : 'text-green-600'
      }`}>
        <div className={`w-3 h-3 rounded-full mr-2 ${
          aiDetection.status === 'pending' ? 'bg-gray-400' :
          aiDetection.is_ai ? 'bg-red-500' : 'bg-green-500'
        }`}></div>
        <span>
          {aiDetection.status === 'pending' ? 'Analysis in progress...' :
           aiDetection.is_ai ? 
           `AI-generated content (${Math.round(aiDetection.ai_probability * 100)}% certainty)` : 
           `Human-written content (${Math.round(aiDetection.human_probability * 100)}% certainty)`}
        </span>
      </div>
      
      {showAiAnalysis && aiDetection.status === 'completed' && (
        <div className="mt-4 space-y-4">
          <div className="border dark:border-gray-700 rounded-lg p-4">
            <h4 className="text-sm font-medium mb-2">Detailed Analysis</h4>
            <div 
              className="prose dark:prose-invert text-sm" 
              dangerouslySetInnerHTML={{ __html: aiDetection.detailed_analysis }}
            ></div>
          </div>
          
          <div className="border dark:border-gray-700 rounded-lg p-4">
            <h4 className="text-sm font-medium mb-2">Sentence-by-Sentence Analysis</h4>
            <pre className="text-xs overflow-x-auto whitespace-pre-wrap bg-gray-50 dark:bg-gray-800 p-3 rounded">
              {aiDetection.sentence_analysis}
            </pre>
          </div>
        </div>
      )}
    </div>
  )}

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
          className="bg-white dark:bg-gray-800 rounded-lg shadow-xl overflow-hidden"
        >
          {/* Back Button */}
          <div className="p-4 border-b dark:border-gray-700">
            <motion.button
              onClick={handleBack}
              className="flex items-center gap-2 text-blue-500 hover:text-blue-600"
              whileHover={{ x: -5 }}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
              </svg>
              {userInfo?.role === 'TEACHER' ? 'Back to Dashboard' : 'Back to Class'}
            </motion.button>
          </div>

          {/* Post Content */}
          <div className="p-6">
            {/* Author Info */}
            <div className="flex items-center space-x-3 mb-6">
              <div className="w-12 h-12 rounded-full bg-gray-300 flex items-center justify-center">
                {post.author?.first_name?.[0] || '?'}
              </div>
              <div>
                <h3 className="font-medium text-lg dark:text-white">
                  {post.author ? `${post.author.first_name} ${post.author.last_name}` : 'Unknown Author'}
                </h3>
                <span className="text-sm text-gray-500 dark:text-gray-400" data-timestamp={post.created_at}>
                  {formatRelativeTime(post.created_at)}
                </span>
              </div>
            </div>

            {/* Post Title - without label */}
            <div className={`mb-6 px-5 py-4 rounded-lg border ${darkMode ? 'bg-gray-750 border-gray-600' : 'bg-blue-50 border-blue-100'}`}>
              <h1 className={`text-2xl font-bold ${darkMode ? 'text-white' : 'text-gray-800'}`}>
                {post.title}
              </h1>
            </div>

            {/* Post Content */}
            <div className="prose dark:prose-invert max-w-none mt-6">
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
            <div className="mt-8 pt-6 border-t dark:border-gray-700">
              <div className="flex items-center space-x-6">
                <button 
                  onClick={handleLike}
                  className="flex items-center space-x-2 text-gray-500 hover:text-red-500 dark:text-gray-400 dark:hover:text-red-400 transition-colors"
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
                  className="flex items-center space-x-2 text-gray-500 hover:text-blue-500 dark:text-gray-400 dark:hover:text-blue-400 transition-colors"
                >
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                  </svg>
                  <span>Comment{totalComments > 0 ? ` (${totalComments})` : ''}</span>
                </button>
              </div>
            </div>

            {/* Comments Section */}
            <div id="comments-section" className="mt-8 pt-4 border-t dark:border-gray-700">
              <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-medium dark:text-white">
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
                  <div className="w-10 h-10 rounded-full bg-gray-300 dark:bg-gray-700 flex items-center justify-center flex-shrink-0">
                    {userInfo?.first_name?.[0] || '?'}
                  </div>
                  <div className="flex-1">
                    <textarea
                      value={newComment}
                      onChange={(e) => setNewComment(e.target.value)}
                      placeholder="Add a comment..."
                      className="w-full p-3 bg-gray-50 dark:bg-gray-800 border dark:border-gray-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
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
                            token={localStorage.getItem('token')}
                            onReply={handleCommentReply}
                            onLike={handleCommentLike}
                          />
                        ))}
                        
                        {/* Load More Comments */}
                        {hasMoreComments && (
                          <div className="flex justify-center my-4">
                            <button
                              onClick={handleLoadMoreComments}
                              className="px-4 py-2 text-sm text-blue-500 hover:text-blue-700 dark:text-blue-400 dark:hover:text-blue-300 border border-blue-300 dark:border-blue-700 rounded-lg hover:bg-blue-50 dark:hover:bg-blue-900/30"
                            >
                              Load more comments
                            </button>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="py-8 text-center text-gray-500 dark:text-gray-400">
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
    </div>
  );
};

export default PostView;