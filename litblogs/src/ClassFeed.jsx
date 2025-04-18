import { useState, useEffect } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import axios from 'axios';
import EmojiPicker from 'emoji-picker-react';
import { GiphyFetch } from '@giphy/js-fetch-api';
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
import { Editor } from '@tinymce/tinymce-react';
import './LitBlogs.css';
import { toast } from 'react-hot-toast';
import { IoMdHeart, IoMdHeartEmpty } from 'react-icons/io';
import CommentThread from './components/CommentThread';
import { formatRelativeTime, setupTimeUpdater } from './utils/timeUtils';

const expandableListStyles = `
  .expandable-list {
    margin: 8px 0;
  }

  .expandable-header {
    display: flex;
    align-items: center;
    gap: 8px;
    cursor: pointer;
    padding: 8px;
    border-radius: 4px;
    background: rgba(0, 0, 0, 0.05);
  }

  .dark .expandable-header {
    background: rgba(255, 255, 255, 0.05);
  }

  .expandable-header .arrow {
    transition: transform 0.2s;
    display: inline-block;
    font-size: 12px;
  }

  .expandable-header.collapsed .arrow {
    transform: rotate(-90deg);
  }

  .expandable-content {
    padding: 8px 8px 8px 24px;
    margin-top: 4px;
    display: block;
  }

  .expandable-header.collapsed + .expandable-content {
    display: none;
  }

  .expandable-header .title {
    font-weight: 500;
  }
`;

const codeStyles = `
  .code-snippet {
    margin: 1rem 0;
    border-radius: 0.5rem;
    overflow: hidden;
    background: #2d2d2d;
  }

  .code-header {
    padding: 0.5rem 1rem;
    background: rgba(255,255,255,0.1);
    color: #fff;
  }

  .code-snippet pre {
    margin: 0;
    padding: 1rem;
  }

  .code-snippet code {
    font-family: 'Fira Code', monospace;
    font-size: 0.9em;
  }
`;

const glassStyles = `
  .glass-card {
    background: rgba(255, 255, 255, 0.05);
    backdrop-filter: blur(10px);
    border: 1px solid rgba(255, 255, 255, 0.1);
    transition: all 0.3s ease;
  }

  .glass-card:hover {
    background: rgba(255, 255, 255, 0.1);
    transform: translateY(-2px);
  }

  .dark .glass-card {
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid rgba(255, 255, 255, 0.05);
  }

  .dark .glass-card:hover {
    background: rgba(0, 0, 0, 0.3);
  }

  @keyframes shimmer {
    0% {
      background-position: -1000px 0;
    }
    100% {
      background-position: 1000px 0;
    }
  }

  .animate-shimmer {
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 0) 0%,
      rgba(255, 255, 255, 0.05) 50%,
      rgba(255, 255, 255, 0) 100%
    );
    background-size: 1000px 100%;
    animation: shimmer 2s infinite linear;
  }
`;

const richTextStyles = `
  .prose {
    max-width: none;
  }
  
  .prose p {
    margin: 1em 0;
  }
  
  .prose h1, .prose h2, .prose h3, .prose h4 {
    margin: 1.5em 0 0.5em;
    font-weight: 600;
  }
  
  .prose ul, .prose ol {
    margin: 1em 0;
    padding-left: 1.5em;
  }
  
  .prose li {
    margin: 0.5em 0;
  }
  
  .prose blockquote {
    border-left: 4px solid #e5e7eb;
    padding-left: 1em;
    margin: 1em 0;
    font-style: italic;
  }
  
  .dark .prose blockquote {
    border-left-color: #4b5563;
  }
`;

// Add this after your imports
Prism.manual = true;

const MOCK_POSTS = [
  {
    id: 1,
    author: "Sritha Kankanala",
    title: "Cow Blog Post: Gene Editing",
    content: "What is gene editing exactly? In simple terms, gene editing is a technology that lets scientists make precise changes to the DNA inside living organisms. DNA is like the instruction manual for every living thing—it tells organisms how to develop and function.",
    isNew: true,
    likes: 1,
    comments: 0,
    timestamp: "1d"
  },
  // ... other mock posts
];

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
            <div key={index} className="flex items-center justify-between p-2 bg-gray-50 dark:bg-gray-700 rounded-lg">
              <div className="flex items-center gap-2">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                <span>{file.name}</span>
              </div>
              <button
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

// Update the TinyMCE configuration to better preserve image attributes and styles
const TINYMCE_CONFIG = {
  height: 400,
  menubar: false,
  plugins: [
    'advlist', 'autolink', 'lists', 'link', 'image', 'charmap', 'preview',
    'anchor', 'searchreplace', 'visualblocks', 'code', 'fullscreen',
    'insertdatetime', 'table', 'help', 'wordcount',
    'quickbars', 'emoticons'
  ],
  toolbar: [
    'formatselect | fontsizeinput | forecolor backcolor | blocks',
    'bold italic underline strikethrough | alignleft aligncenter alignright | bullist numlist | image customvideoupload customfileupload removeformat'
  ],
  block_formats: 'Paragraph=p; Title=h1; Heading=h2; Subheading=h3; Small Heading=h4; Blockquote=blockquote',
  
  // Use the built-in font size input instead of the fontsize plugin
  font_size_input_default_unit: 'pt',
  font_size_formats: '8pt 10pt 12pt 14pt 16pt 18pt 24pt 36pt 48pt',
  
  forced_root_block: 'p',
  content_style: `
    body { 
      font-family: Arial, sans-serif;
      font-size: 14px;
      margin: 1rem;
      padding-bottom: 2rem;
      max-height: 400px;
      overflow-y: auto !important;
    }
    h1 { font-size: 1.8em; font-weight: bold; margin: 0.5em 0; }
    h2 { font-size: 1.5em; font-weight: bold; margin: 0.5em 0; }
    h3 { font-size: 1.3em; font-weight: bold; margin: 0.5em 0; }
    h4 { font-size: 1.1em; font-weight: bold; margin: 0.5em 0; }
    blockquote { border-left: 3px solid #ccc; margin-left: 1em; padding-left: 1em; font-style: italic; }
    
    /* File attachment styles */
    .file-attachment {
      display: flex;
      align-items: center;
      padding: 10px;
      margin: 10px 0;
      border: 1px solid #e0e0e0;
      border-radius: 8px;
      background-color: #f9f9f9;
      user-select: none; /* Prevent text selection */
      pointer-events: auto; /* Allow clicking buttons */
      cursor: default; /* Show default cursor for the container */
    }
    
    .file-attachment * {
      cursor: default;
      user-select: none;
    }
    
    .file-attachment .file-icon {
      margin-right: 12px;
      font-size: 24px;
      color: #4a5568;
    }
    
    .file-attachment .file-info {
      flex-grow: 1;
      flex-shrink: 1;
      min-width: 0; /* Allow text to wrap */
      overflow: hidden; /* Prevent overflow */
    }
    
    .file-attachment .file-name {
      font-weight: 500;
      margin-bottom: 2px;
      word-break: break-word;
      overflow-wrap: break-word;
      white-space: normal;
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
      cursor: pointer !important; /* Force pointer cursor for buttons */
      pointer-events: auto !important; /* Ensure buttons are clickable */
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 12px;
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
    
    .file-attachment .remove-btn {
      background-color: #fff5f5;
      color: #e53e3e;
      border: 1px solid #fed7d7;
    }
    
    /* Fix dropdown spacing */
    .tox-collection__item-label {
      padding-left: 4px !important;
    }
    .tox-collection__item-icon {
      padding-right: 4px !important;
    }
    .tox-tbtn__select-label {
      margin-left: 0 !important;
    }
    
    /* Editor-only elements - only visible in the editor */
    .mce-content-body .editor-only {
      display: inline-block;
    }
    
    /* Hide editor-only elements in the published content */
    .html-content .editor-only {
      display: none;
    }
  `,
  statusbar: false,
  extended_valid_elements: 'span[style|class],div[class|data-*|contenteditable],img[*|style|class|width|height|align|data-*],a[*],button[*]',
  inline_styles: true,
  paste_as_text: false,
  paste_data_images: true,
  automatic_uploads: true,
  file_picker_types: 'file image media',
  paste_retain_style_properties: 'color,background-color,font-size',
  browser_spellcheck: true,
  font_formats: 'Arial=arial,helvetica,sans-serif;' +
                'Courier New=courier new,courier,monospace;' +
                'Georgia=georgia,times new roman,times,serif;' +
                'Tahoma=tahoma,arial,helvetica,sans-serif;' +
                'Times New Roman=times new roman,times,serif;' +
                'Trebuchet MS=trebuchet ms,geneva,sans-serif;' +
                'Verdana=verdana,geneva,sans-serif',
  
  // Enhanced image handling
  image_advtab: true,
  image_dimensions: true,
  image_class_list: [
    { title: 'None', value: '' },
    { title: 'Responsive', value: 'img-fluid' },
    { title: 'Left Aligned', value: 'float-left' },
    { title: 'Right Aligned', value: 'float-right' },
    { title: 'Centered', value: 'mx-auto d-block' }
  ],
  
  // Preserve styles when editing
  preserve_styles: true,
  
  // Add image_upload_handler to handle direct uploads from TinyMCE's default dialog
  images_upload_handler: async function (blobInfo, progress) {
    return new Promise((resolve, reject) => {
      const formData = new FormData();
      formData.append('file', blobInfo.blob(), blobInfo.filename());
      
      const token = localStorage.getItem('token');
      
      axios.post('http://localhost:8000/api/upload', formData, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'multipart/form-data'
        },
        onUploadProgress: (e) => {
          progress(e.loaded / e.total * 100);
        }
      })
      .then(response => {
        resolve(response.data.url);
      })
      .catch(error => {
        reject('Image upload failed: ' + error.message);
      });
    });
  },
  
  // Critical settings for image resizing and alignment
  object_resizing: true,
  resize_img_proportional: true,
  
  // Don't convert URLs - this is critical
  convert_urls: false,
  relative_urls: false,
  
  // Ensure all styles are preserved
  valid_styles: '*[*]',
  
  // Configure non-editable classes
  noneditable_noneditable_class: 'mceNonEditable',
  noneditable_editable_class: 'mceEditable',
  
  // Allow the noneditable plugin to work with our elements
  protect: [
    /\<div[^>]*class="file\-attachment"[^>]*\>[\s\S]*?\<\/div\>/g
  ],
  
  setup: function(editor) {
    // Customize the image button to show our enhanced dialog
    editor.ui.registry.addButton('image', {
      icon: 'image',
      tooltip: 'Insert image',
      onAction: function() {
        // Create custom image dialog
        editor.windowManager.open({
          title: 'Insert Image',
          body: {
            type: 'panel',
            items: [
              {
                type: 'selectbox',
                name: 'source',
                label: 'Image Source',
                items: [
                  { value: 'upload', text: 'Upload from Computer' },
                  { value: 'url', text: 'Insert from URL' }
                ]
              },
              {
                type: 'input',
                name: 'url',
                label: 'Image URL',
                enabled: false
              },
              {
                type: 'dropzone',
                name: 'file',
                label: 'Upload Image'
              }
            ]
          },
          buttons: [
            {
              type: 'cancel',
              text: 'Cancel'
            },
            {
              type: 'submit',
              text: 'Insert',
              primary: true
            }
          ],
          initialData: {
            source: 'upload'
          },
          onChange: function(api, details) {
            if (details.name === 'source') {
              // Toggle fields based on selected source
              if (details.value === 'upload') {
                api.setEnabled('file', true);
                api.setEnabled('url', false);
              } else {
                api.setEnabled('file', false);
                api.setEnabled('url', true);
              }
            }
          },
          onSubmit: async function(api) {
            const data = api.getData();
            
            try {
              if (data.source === 'upload' && data.file) {
                // Handle file upload
                const file = data.file;
                const formData = new FormData();
                formData.append('file', file);
                
                const token = localStorage.getItem('token');
                const response = await axios.post(
                  'http://localhost:8000/api/upload',
                  formData,
                  {
                    headers: {
                      'Authorization': `Bearer ${token}`,
                      'Content-Type': 'multipart/form-data'
                    }
                  }
                );
                
                // Insert the uploaded image
                editor.insertContent(`<img src="${response.data.url}" alt="${file.name}" style="max-width: 100%; height: auto;" />`);
              } else if (data.source === 'url' && data.url) {
                // Insert image from URL
                editor.insertContent(`<img src="${data.url}" alt="Image from URL" style="max-width: 100%; height: auto;" />`);
              }
              
              api.close();
            } catch (error) {
              console.error('Error handling image:', error);
              editor.notificationManager.open({
                text: 'Failed to process image. Please try again.',
                type: 'error'
              });
              api.close();
            }
          }
        });
      }
    });

    // Add custom file upload button
    editor.ui.registry.addButton('customfileupload', {
      icon: 'upload',
      tooltip: 'Upload File',
      onAction: function() {
        // Create a file input element
        const input = document.createElement('input');
        input.setAttribute('type', 'file');
        input.setAttribute('accept', '*/*'); // Accept all file types
        
        // Trigger click on the input element
        input.click();
        
        // Handle file selection
        input.onchange = async function() {
          if (input.files && input.files[0]) {
            const file = input.files[0];
            
            try {
              // Upload the file to the server
              const formData = new FormData();
              formData.append('file', file);
              
              const token = localStorage.getItem('token');
              const response = await axios.post(
                'http://localhost:8000/api/upload',
                formData,
                {
                  headers: {
                    'Authorization': `Bearer ${token}`,
                    'Content-Type': 'multipart/form-data'
                  }
                }
              );
              
              // Get the file URL from the response
              const fileUrl = response.data.url;
              const fileSize = formatFileSize(file.size);
              const fileName = file.name;
              const fileType = getFileType(file.name);
              
              // Create HTML for the file attachment
              let fileHtml = `
                <div class="mceNonEditable file-attachment" 
                     data-file-url="${fileUrl}" 
                     data-file-name="${fileName}" 
                     data-file-size="${fileSize}" 
                     data-file-type="${fileType}">
                  <div class="file-icon">${getFileIcon(fileType)}</div>
                  <div class="file-info">
                    <div class="file-name" style="word-break: break-word; overflow-wrap: break-word;">${fileName}</div>
                    <div class="file-size">${fileSize}</div>
                  </div>
                  <div class="file-actions">
                    <button class="remove-btn editor-only" type="button" data-file-url="${fileUrl}" onclick="this.closest('.file-attachment').remove();">Remove</button>
                  </div>
                </div>
              `;
              
              // Insert the file attachment at the cursor position
              editor.insertContent(fileHtml);
              
            } catch (error) {
              console.error('Error uploading file:', error);
              toast.error('Failed to upload file. Please try again.');
            }
          }
        };
      }
    });
    
    // Add custom handlers for file preview
    editor.on('init', function() {
      // Add global function for file preview
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
    });
    
    // Register the deleteFileFromServer function with the editor
    editor.addCommand('deleteFileFromServer', function(ui, url) {
      deleteFileFromServer(url);
    });
    
    // This is critical for preserving image dimensions
    editor.on('ObjectResized', function(e) {
      if (e.target.nodeName === 'IMG') {
        // Set both style and attributes for maximum compatibility
        e.target.setAttribute('width', e.width);
        e.target.setAttribute('height', e.height);
        e.target.style.width = e.width + 'px';
        e.target.style.height = e.height + 'px';
      }
    });
    
    // Add this to ensure content is not modified during save
    editor.on('BeforeSetContent', function(e) {
      // Don't modify content when setting it in the editor
    });
    
    editor.on('GetContent', function(e) {
      // Don't modify content when retrieving it from the editor
    });
    
    // Listen for clicks on the editor content
    editor.on('click', function(e) {
      // Check if the clicked element is a remove button
      if (e.target.classList.contains('remove-btn') && e.target.dataset.fileUrl) {
        // Get the file URL from the data attribute
        const fileUrl = e.target.dataset.fileUrl;
        
        // Delete the file from the server
        deleteFileFromServer(fileUrl);
      }
    });
    
    // Add custom video upload button
    editor.ui.registry.addButton('customvideoupload', {
      icon: 'embed',
      tooltip: 'Upload Video',
      onAction: function() {
        // Create a file input element
        const input = document.createElement('input');
        input.setAttribute('type', 'file');
        input.setAttribute('accept', 'video/*');
        
        // Handle file selection
        input.onchange = async function() {
          if (input.files && input.files[0]) {
            const file = input.files[0];
            
            // Check file size (limit to 100MB)
            const maxSize = 100 * 1024 * 1024; // 100MB in bytes
            if (file.size > maxSize) {
              toast.error(`Video file is too large. Maximum size is 100MB.`);
              return;
            }
            
            // Check file type
            const validTypes = ['video/mp4', 'video/webm', 'video/ogg'];
            if (!validTypes.includes(file.type)) {
              toast.error('Please upload a valid video file (MP4, WebM, or OGG).');
              return;
            }
            
            try {
              // Show loading toast
              const loadingToast = toast.loading('Uploading video...');
              
              // Create form data for upload
              const formData = new FormData();
              formData.append('file', file);
              
              // Upload the video
              const token = localStorage.getItem('token');
              const response = await axios.post('http://localhost:8000/api/upload', formData, {
                headers: {
                  'Authorization': `Bearer ${token}`,
                  'Content-Type': 'multipart/form-data'
                }
              });
              
              // Get the uploaded file URL and log for debugging
              console.log("Video upload response:", response.data);
              
              // Check if the response contains the expected data
              // Handle both url and file_url formats
              let videoUrl = null;
              if (response.data && response.data.url) {
                videoUrl = response.data.url;
              } else if (response.data && response.data.file_url) {
                videoUrl = response.data.file_url;
              } else {
                console.error("Invalid response format:", response.data);
                toast.error('Server returned an invalid response. Please try again.');
                toast.dismiss(loadingToast);
                return;
              }
              
              console.log("Video URL:", videoUrl);
              
              // Ensure the URL is properly formatted
              const fullVideoUrl = videoUrl && videoUrl.startsWith('/') 
                ? `http://localhost:8000${videoUrl}` 
                : videoUrl && videoUrl.startsWith('http') 
                  ? videoUrl 
                  : `http://localhost:8000/${videoUrl}`;
                  
              console.log("Full video URL:", fullVideoUrl);
              
              // Create a cleaner HTML for the video with a delete button overlay
              let videoHtml = `
                <figure class="video-container" contenteditable="false">
                  <video controls width="100%" style="max-width: 600px; border-radius: 4px; display: block;">
                    <source src="${fullVideoUrl}" type="${file.type}">
                    Your browser does not support the video tag.
                  </video>
                  <div class="editor-only-control" style="position: absolute; top: 8px; right: 8px; z-index: 10;">
                    <button type="button" class="video-delete-btn" style="background: rgba(239, 68, 68, 0.9); color: white; border: none; border-radius: 50%; width: 28px; height: 28px; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 18px; font-weight: bold; box-shadow: 0 2px 4px rgba(0,0,0,0.2);" data-video-url="${videoUrl}" onclick="event.stopPropagation(); this.closest('.video-container').remove(); window.deleteVideoFromServer('${videoUrl}');">×</button>
                  </div>
                </figure>
              `;
              
              // Insert the video HTML
              editor.insertContent(videoHtml);
              
              // Add hover effect for the delete button using JavaScript
              editor.on('NodeChange', function() {
                const videoWrappers = editor.getBody().querySelectorAll('.video-container');
                videoWrappers.forEach(wrapper => {
                  if (!wrapper.dataset.eventAdded) {
                    wrapper.dataset.eventAdded = 'true';
                    
                    const deleteOverlay = wrapper.querySelector('.video-delete-overlay');
                    
                    wrapper.addEventListener('mouseenter', function() {
                      deleteOverlay.style.display = 'block';
                    });
                    
                    wrapper.addEventListener('mouseleave', function() {
                      deleteOverlay.style.display = 'none';
                    });
                  }
                });
              });
              
              // Dismiss loading toast and show success
              toast.dismiss(loadingToast);
              toast.success('Video uploaded successfully!');
            } catch (error) {
              console.error('Error uploading video:', error);
              toast.error('Failed to upload video. Please try again.');
            }
          }
        };
        
        // Trigger the file input click
        input.click();
      }
    });
    
    // Listen for clicks on the editor content
    editor.on('click', function(e) {
      // Check if the clicked element is a remove button
      if (e.target.classList.contains('remove-btn')) {
        // Get the file or video URL from the data attribute
        const fileUrl = e.target.dataset.fileUrl || e.target.dataset.videoUrl;
        
        if (fileUrl) {
          // Delete the file from the server
          deleteFileFromServer(fileUrl);
        }
      }
    });
  },
};

// Helper functions for file handling
function formatFileSize(bytes) {
  if (bytes === 0) return '0 Bytes';
  const k = 1024;
  const sizes = ['Bytes', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function getFileType(filename) {
  const ext = filename.split('.').pop().toLowerCase();
  
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg'].includes(ext)) {
    return 'image';
  } else if (['mp4', 'webm', 'ogg', 'mov'].includes(ext)) {
    return 'video';
  } else if (ext === 'pdf') {
    return 'pdf';
  } else if (['txt', 'md', 'html', 'css', 'js', 'json', 'xml'].includes(ext)) {
    return 'text';
  } else if (['doc', 'docx'].includes(ext)) {
    return 'word';
  } else if (['xls', 'xlsx'].includes(ext)) {
    return 'excel';
  } else if (['ppt', 'pptx'].includes(ext)) {
    return 'powerpoint';
  } else {
    return 'other';
  }
}

function isPreviewable(fileType) {
  return ['image', 'video', 'pdf', 'text'].includes(fileType);
}

function getFileIcon(fileType) {
  switch (fileType) {
    case 'image':
      return '🖼️';
    case 'video':
      return '🎬';
    case 'pdf':
      return '📄';
    case 'text':
      return '📝';
    case 'word':
      return '📘';
    case 'excel':
      return '📊';
    case 'powerpoint':
      return '📑';
    default:
      return '📁';
  }
}

// Update the processHTMLWithDOM function to handle different media types

const processHTMLWithDOM = (html) => {
  if (!html) return '';
  
  // Create a temporary div to parse the HTML
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = html;
  
  // Remove editor-only controls
  const editorControls = tempDiv.querySelectorAll('.editor-only-control, .video-delete-btn');
  editorControls.forEach(control => {
    control.remove();
  });
  
  // Track what types of media we've found
  let mediaTypes = {
    video: false,
    file: false,
    image: false,
    audio: false
  };
  
  // First, clean up any raw HTML in text nodes
  let mediaPlaceholderAdded = false;
  
  const cleanRawHTML = (node) => {
    if (node.nodeType === Node.TEXT_NODE) {
      // Check for various media-related HTML tags
      if (node.textContent.includes('<video') || 
          node.textContent.includes('</video>') ||
          node.textContent.includes('<figure class="video-container"') ||
          node.textContent.includes('</figure>')) {
        mediaTypes.video = true;
        
        // If we haven't added a placeholder yet, add one
        if (!mediaPlaceholderAdded) {
          const placeholder = document.createElement('div');
          placeholder.className = 'media-placeholder video-placeholder';
          placeholder.innerHTML = '<span class="text-blue-500">[View post to see video content]</span>';
          node.parentNode.replaceChild(placeholder, node);
          mediaPlaceholderAdded = true;
        } else {
          // Otherwise, just remove the node
          node.parentNode.removeChild(node);
        }
      } else if (node.textContent.includes('<a class="file-attachment"') ||
                node.textContent.includes('data-file-url')) {
        mediaTypes.file = true;
        
        // If we haven't added a placeholder yet, add one for files
        if (!mediaPlaceholderAdded) {
          const placeholder = document.createElement('div');
          placeholder.className = 'media-placeholder file-placeholder';
          placeholder.innerHTML = '<span class="text-blue-500">[View post to see attached files]</span>';
          node.parentNode.replaceChild(placeholder, node);
          mediaPlaceholderAdded = true;
        } else {
          // Otherwise, just remove the node
          node.parentNode.removeChild(node);
        }
      }
    } else if (node.nodeType === Node.ELEMENT_NODE) {
      // Process all child nodes
      const childNodes = Array.from(node.childNodes);
      childNodes.forEach(cleanRawHTML);
    }
  };
  
  cleanRawHTML(tempDiv);
  
  // Now replace actual media elements with placeholders
  if (!mediaPlaceholderAdded) {
    // Check for different types of media elements
    const videoElements = tempDiv.querySelectorAll('video, .video-wrapper, figure.video-container');
    const fileElements = tempDiv.querySelectorAll('.file-attachment, a[href*=".pdf"], a[href*=".doc"], a[href*=".xls"], a[href*=".ppt"], a[href*=".zip"]');
    const audioElements = tempDiv.querySelectorAll('audio');
    const iframeElements = tempDiv.querySelectorAll('iframe');
    
    // Set flags for what we found
    if (videoElements.length > 0) mediaTypes.video = true;
    if (fileElements.length > 0) mediaTypes.file = true;
    if (audioElements.length > 0) mediaTypes.audio = true;
    
    // Create appropriate placeholders based on what we found
    if (mediaTypes.video) {
      const placeholder = document.createElement('div');
      placeholder.className = 'media-placeholder video-placeholder';
      placeholder.innerHTML = '<span class="text-blue-500">[View post to see video content]</span>';
      
      // Replace the first video element with the placeholder
      if (videoElements.length > 0) {
        videoElements[0].parentNode.replaceChild(placeholder, videoElements[0]);
        
        // Remove the rest
        for (let i = 1; i < videoElements.length; i++) {
          videoElements[i].parentNode.removeChild(videoElements[i]);
        }
      }
    }
    
    if (mediaTypes.file) {
      const placeholder = document.createElement('div');
      placeholder.className = 'media-placeholder file-placeholder';
      placeholder.innerHTML = '<span class="text-blue-500">[View post to see attached files]</span>';
      
      // Replace the first file element with the placeholder
      if (fileElements.length > 0) {
        fileElements[0].parentNode.replaceChild(placeholder, fileElements[0]);
        
        // Remove the rest
        for (let i = 1; i < fileElements.length; i++) {
          fileElements[i].parentNode.removeChild(fileElements[i]);
        }
      }
    }
    
    if (mediaTypes.audio) {
      const placeholder = document.createElement('div');
      placeholder.className = 'media-placeholder audio-placeholder';
      placeholder.innerHTML = '<span class="text-blue-500">[View post to see audio content]</span>';
      
      // Replace the first audio element with the placeholder
      if (audioElements.length > 0) {
        audioElements[0].parentNode.replaceChild(placeholder, audioElements[0]);
      }
    }
    
    // Handle iframes (could be embedded content)
    if (iframeElements.length > 0) {
      const placeholder = document.createElement('div');
      placeholder.className = 'media-placeholder embed-placeholder';
      placeholder.innerHTML = '<span class="text-blue-500">[View post to see embedded content]</span>';
      
      // Replace the first iframe with the placeholder
      iframeElements[0].parentNode.replaceChild(placeholder, iframeElements[0]);
      
      // Remove the rest
      for (let i = 1; i < iframeElements.length; i++) {
        iframeElements[i].parentNode.removeChild(iframeElements[i]);
      }
    }
  }
  
  return tempDiv.innerHTML;
};

// Update the truncateHTML function to better preserve content structure

const truncateHTML = (htmlContent, maxLength = 200) => {
  if (!htmlContent) return '';
  
  // Create a temporary div to parse the HTML
  const tempDiv = document.createElement('div');
  tempDiv.innerHTML = htmlContent;
  
  // Remove videos, file attachments, and other media elements from the preview
  const videosAndMedia = tempDiv.querySelectorAll('video, .video-wrapper, .mceNonEditable, .file-attachment, iframe, audio');
  videosAndMedia.forEach(element => {
    // Replace with a placeholder
    const placeholder = document.createElement('div');
      placeholder.className = 'media-placeholder file-placeholder';
      placeholder.innerHTML = '<span class="text-blue-500">[View post to see attached files]</span>';
    element.parentNode.replaceChild(placeholder, element);
  });
  
  // Get text content for length check
  const textContent = tempDiv.textContent || tempDiv.innerText || '';
  
  // If content is short enough, return the modified HTML
  if (textContent.length <= maxLength) {
    return tempDiv.innerHTML;
  }
  
  // For longer content, we need to truncate while preserving HTML structure
  return tempDiv.innerHTML + '<span class="text-blue-500">... (read more)</span>';
};

// Add this function to handle file deletion
async function deleteFileFromServer(url) {
  try {
    // Extract the file path from the URL
    // The URL format is /uploads/user_id/filename
    const filePath = url.replace('/uploads/', '');
    
    const token = localStorage.getItem('token');
    await axios.delete(`http://localhost:8000/api/upload/${filePath}`, {
      headers: { 
        'Authorization': `Bearer ${token}`
      }
    });
    
    console.log('File deleted successfully from server');
  } catch (error) {
    console.error('Error deleting file from server:', error);
  }
}

// Make the deleteFileFromServer function available globally
window.deleteFileFromServer = deleteFileFromServer;

// Add a global function to delete the video from the server
if (!window.deleteVideoFromServer) {
  window.deleteVideoFromServer = function(videoUrl) {
    if (!videoUrl) return;
    
    // Extract the file path from the URL
    let filePath = videoUrl;
    if (videoUrl.includes('/uploads/')) {
      filePath = videoUrl.split('/uploads/')[1];
    }
    
    // Get the token
    const token = localStorage.getItem('token');
    if (!token) return;
    
    // Delete the file from the server
    axios.delete(`http://localhost:8000/api/upload/${filePath}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(response => {
      console.log('Video deleted successfully:', response.data);
      toast.success('Video deleted successfully');
    })
    .catch(error => {
      console.error('Error deleting video:', error);
      toast.error('Failed to delete video from server');
    });
  };
}

// Add this function at the top of your file, before any component definitions
// Make sure it's outside of any component or function scope

// Define the deleteVideoFromServer function globally
function defineGlobalFunctions() {
  // Add a global function to delete the video from the server
  window.deleteVideoFromServer = function(videoUrl) {
    if (!videoUrl) return;
    
    // Extract the file path from the URL
    let filePath = videoUrl;
    if (videoUrl.includes('/uploads/')) {
      filePath = videoUrl.split('/uploads/')[1];
    }
    
    // Get the token
    const token = localStorage.getItem('token');
    if (!token) return;
    
    // Delete the file from the server
    axios.delete(`http://localhost:8000/api/upload/${filePath}`, {
      headers: { 'Authorization': `Bearer ${token}` }
    })
    .then(response => {
      console.log('Video deleted successfully:', response.data);
      toast.success('Video deleted successfully');
    })
    .catch(error => {
      console.error('Error deleting video:', error);
      toast.error('Failed to delete video from server');
    });
  };
  
  // Make the deleteFileFromServer function available globally if it exists
  if (typeof deleteFileFromServer === 'function') {
    window.deleteFileFromServer = deleteFileFromServer;
  }
}

// Call this function immediately to define the global functions
defineGlobalFunctions();

// Add this CSS variable definition near the top of your file with the other style variables

const editorStyles = `
  /* Hide editor-only controls when not in editor */
  .html-content .editor-only-control {
    display: none !important;
  }
  
  .html-content .video-delete-btn {
    display: none !important;
  }
  
  /* Style for media placeholders */
  .media-placeholder {
    padding: 12px;
    background-color: rgba(59, 130, 246, 0.1);
    border-radius: 6px;
    margin: 8px 0;
    text-align: center;
  }
  
  .video-placeholder {
    border-left: 3px solid #3b82f6;
  }
`;

const ClassFeed = () => {
  // Move all useState hooks to the top
  const { classId } = useParams();
  const navigate = useNavigate();
  const [userInfo, setUserInfo] = useState(null);
  const [classDetails, setClassDetails] = useState(null);
  const [posts, setPosts] = useState(MOCK_POSTS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [darkMode, setDarkMode] = useState(() => {
    return JSON.parse(localStorage.getItem('darkMode')) ?? false;
  });
  const [newPost, setNewPost] = useState("");
  const [showNewPostForm, setShowNewPostForm] = useState(false);
  const [postTitle, setPostTitle] = useState("");
  const [postCategory, setPostCategory] = useState("");
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [showGifPicker, setShowGifPicker] = useState(false);
  const [showPollForm, setShowPollForm] = useState(false);
  const [pollOptions, setPollOptions] = useState(['', '']);
  const [content, setContent] = useState('');
  const [gifSearchTerm, setGifSearchTerm] = useState('');
  const [gifs, setGifs] = useState([]);
  const [showCodeEditor, setShowCodeEditor] = useState(false);
  const [codeLanguage, setCodeLanguage] = useState('javascript');
  const [codeContent, setCodeContent] = useState('');
  const [postContent, setPostContent] = useState({
    text: "",
    media: [],
    expandableLists: [],
    codeSnippets: [],
    files: []
  });
  const [activeCategory, setActiveCategory] = useState('all');
  const [activePostMenu, setActivePostMenu] = useState(null);
  const [editingPostId, setEditingPostId] = useState(null);
  const [menuOpen, setMenuOpen] = useState(null);
  const [likedPosts, setLikedPosts] = useState({});
  const [likesLoading, setLikesLoading] = useState({});
  const [likeEffects, setLikeEffects] = useState({});
  const [postCommentsVisible, setPostCommentsVisible] = useState({});
  const [postComments, setPostComments] = useState({});
  const [commentLoading, setCommentLoading] = useState({});
  const [newCommentText, setNewCommentText] = useState({});
  const [commentCounts, setCommentCounts] = useState({});

  const gf = new GiphyFetch('FEzk8anVjSKZIiInlJWd4Jo4OuYBjV9B');

  // Add this to your component's useEffect that runs on mount
  useEffect(() => {
    // Ensure global functions are defined
    defineGlobalFunctions();
    
    // Rest of your existing useEffect code...
  }, []);

  // Move all useEffect hooks together
  useEffect(() => {
    // Load user info
    const storedUserInfo = localStorage.getItem('user_info');
    if (storedUserInfo) {
      setUserInfo(JSON.parse(storedUserInfo));
    }

    const fetchData = async () => {
      try {
        const token = localStorage.getItem('token');
        if (!token) {
          navigate('/sign-in');
          return;
        }

        // Use the correct endpoint
        const classResponse = await axios.get(`http://localhost:8000/api/classes/${classId}/details`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        setClassDetails(classResponse.data);

        // Get class posts using the posts endpoint
        const postsResponse = await axios.get(`http://localhost:8000/api/classes/${classId}/posts`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        setPosts(postsResponse.data);

        setLoading(false);
      } catch (error) {
        console.error('Error fetching class data:', error);
        setError(error.response?.data?.detail || 'Failed to load class data');
        setLoading(false);
        if (error.response?.status === 401) {
          navigate('/sign-in');
        }
      }
    };

    fetchData();
  }, [classId, navigate]);

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
    const styleSheet = document.createElement("style");
    styleSheet.innerText = expandableListStyles + codeStyles + glassStyles + richTextStyles + editorStyles;
    document.head.appendChild(styleSheet);

    const handleExpandableClick = (e) => {
      const header = e.target.closest('.expandable-header');
      if (header) {
        header.classList.toggle('collapsed');
      }
    };

    document.addEventListener('click', handleExpandableClick);

    return () => {
      document.removeEventListener('click', handleExpandableClick);
      styleSheet.remove();
    };
  }, []);

  // Add the new useEffect for click outside menu
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (activePostMenu && !event.target.closest('.post-menu')) {
        setActivePostMenu(null);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [activePostMenu]);

  useEffect(() => {
    // Get likes for all posts on initial load
    const fetchLikes = async () => {
      const token = localStorage.getItem('token');
      if (!token || !posts.length) return;
      
      const likesInfo = {};
      
      for (const post of posts) {
        try {
          const response = await axios.get(`http://localhost:8000/api/classes/${classId}/posts/${post.id}/likes`, {
            headers: { Authorization: `Bearer ${token}` }
          });
          
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
  }, [posts]);

  useEffect(() => {
    // Modify the existing useEffect that fetches posts
    const fetchPostsAndCounts = async () => {
      if (!classId) return;
      
      setPostsLoading(true);
      
      try {
        const token = localStorage.getItem('token');
        if (!token) return;
        
        // Fetch the posts
        const response = await axios.get(`http://localhost:8000/api/classes/${classId}/posts`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        
        setPosts(response.data);
        
        // Fetch comment counts immediately after posts load
        const counts = {};
        
        // Debug log to check if this function is running
        console.log("Fetching comment counts for posts:", response.data.length);
        
        // We'll fetch one by one to ensure reliability
        for (const post of response.data) {
          try {
            const commentResponse = await axios.get(
              `http://localhost:8000/api/classes/${classId}/posts/${post.id}/comments?limit=1`,
              { headers: { Authorization: `Bearer ${token}` } }
            );
            counts[post.id] = commentResponse.data.total;
            console.log(`Post ${post.id} has ${commentResponse.data.total} comments`);
          } catch (err) {
            console.error(`Failed to fetch comments for post ${post.id}:`, err);
            counts[post.id] = 0;
          }
        }
        
        // Log the counts before setting state
        console.log("Final comment counts:", counts);
        
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

  const createPost = async (e) => {
    e.preventDefault();
    try {
      const token = localStorage.getItem('token');
      
      // The content already contains the embedded files as HTML
      // TinyMCE will handle the placement of files exactly where the user put them
      
      const response = await axios.post(
          `http://localhost:8000/api/classes/${classId}/posts`,
          {
            title: postTitle,
          content: postContent.text, // This now contains all embedded files
          // We don't need separate media, files arrays as they're embedded in the content
          },
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );

      // Refresh posts after creation
      const postsResponse = await axios.get(`http://localhost:8000/api/classes/${classId}/posts`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      setPosts(postsResponse.data);
      
      // Reset form
      setShowNewPostForm(false);
      setPostTitle("");
      setPostContent({
        text: "",
        media: [],
        expandableLists: [],
        codeSnippets: [],
        files: []
      });
      setPollOptions(['', '']);
      setShowPollForm(false);
      
      toast.success('Post created successfully!');
    } catch (error) {
      console.error('Error creating post:', error);
      toast.error('Failed to create post. Please try again.');
    }
  };

  const handleImageUpload = async (e) => {
    const file = e.target.files[0];
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const token = localStorage.getItem('token');
        const response = await axios.post('http://localhost:8000/api/upload/image', formData, {
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'multipart/form-data'
          }
        });
        setPostContent(prev => ({
          ...prev,
          media: [...prev.media, {
            type: 'image',
            url: response.data.url,
            alt: 'Image'
          }]
        }));
      } catch (error) {
        console.error('Error uploading image:', error);
      }
    }
  };

  const handleVideoUpload = async (e) => {
    const file = e.target.files[0];
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const token = localStorage.getItem('token');
        const response = await axios.post('http://localhost:8000/api/upload/video', formData, {
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'multipart/form-data'
          }
        });
        setPostContent(prev => ({
          ...prev,
          media: [...prev.media, {
            type: 'video',
            url: response.data.url,
            alt: 'Video'
          }]
        }));
      } catch (error) {
        console.error('Error uploading video:', error);
      }
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      try {
        const token = localStorage.getItem('token');
        const response = await axios.post('http://localhost:8000/api/upload/file', formData, {
          headers: { 
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'multipart/form-data'
          }
        });
        setPostContent(prev => ({
          ...prev,
          files: [...prev.files, {
            name: file.name,
            url: response.data.url
          }]
        }));
      } catch (error) {
        console.error('Error uploading file:', error);
      }
    }
  };

  const insertDivider = () => {
    setPostContent(prev => ({
      ...prev,
      text: prev.text + '\n---\n'
    }));
  };

  const handleEmojiClick = (emojiData) => {
    setPostContent(prev => ({
      ...prev,
      text: prev.text + emojiData.emoji
    }));
    setShowEmojiPicker(false);
  };

  const searchGifs = async (term) => {
    try {
      const { data } = await gf.search(term, { 
        limit: 10,
        rating: 'g', // 'g' means content suitable for children
        type: 'gifs',
        lang: 'en'
      });
      setGifs(data);
    } catch (error) {
      console.error('Error searching GIFs:', error);
    }
  };

  const handleGifSelect = (gif) => {
    setPostContent(prev => ({
      ...prev,
      media: [...prev.media, {
        type: 'gif',
        url: gif.images.fixed_height.url,
        alt: 'GIF'
      }]
    }));
    setShowGifPicker(false);
    setGifs([]);
    setGifSearchTerm('');
  };

  const insertExpandableList = () => {
    setPostContent(prev => ({
      ...prev,
      expandableLists: [...prev.expandableLists, {
        id: Date.now(),
        title: "Write a title",
        content: "Add content to expand",
        isCollapsed: false
      }]
    }));
  };

  const updateExpandableList = (id, field, value) => {
    setPostContent(prev => ({
      ...prev,
      expandableLists: prev.expandableLists.map(list => 
        list.id === id ? { ...list, [field]: value } : list
      )
    }));
  };

  const handlePollSubmit = () => {
    const pollContent = `\n### Poll\n${pollOptions.map((opt, i) => `${i + 1}. ${opt}`).join('\n')}\n`;
    setPostContent(prev => ({
      ...prev,
      text: prev.text + pollContent
    }));
    setShowPollForm(false);
    setPollOptions(['', '']);
  };

  const handleCodeSubmit = () => {
    if (!codeContent.trim()) return;
    
    // Add code directly to the text content instead of keeping it separate
    setPostContent(prev => ({
      ...prev,
      text: prev.text + `\n[CODE:${codeLanguage}]${codeContent}\n`
    }));
    
    setShowCodeEditor(false);
    setCodeContent('');
    setCodeLanguage('javascript');
  };

  const handleRemoveMedia = (type, index) => {
    setPostContent(prev => ({
      ...prev,
      [type]: prev[type].filter((_, i) => i !== index)
    }));
  };

  // Add this helper function near the top of your file
  const renderContent = (content) => {
    // Split content by custom markers
    const parts = content.split(/(\[(?:CODE|GIF|POLL|FILE|IMAGE):.+?\])/g);

    return parts.map((part, index) => {
      // Check for special content markers
      if (part.startsWith('[CODE:')) {
        const language = part.match(/\[CODE:(\w+)\]/)?.[1] || 'javascript';
        const code = part.replace(/\[CODE:\w+\]/, '').trim();
        return (
          <div key={index} className="code-snippet my-4">
            <div className="code-header">
              <span className="text-sm font-mono">{language}</span>
            </div>
            <pre>
              <code className={`language-${language}`}>
                {code}
              </code>
            </pre>
          </div>
        );
      }
      
      // ... other content type handlers ...

      // Regular text content
      return (
        <p key={index} className="text-gray-600 dark:text-gray-300 whitespace-pre-wrap">
          {part}
        </p>
      );
    });
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

  const handleSignOut = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user_info');
    localStorage.removeItem('class_info');
    setUserInfo(null);
    navigate('/');
  };

  const handleEditPost = async (postId) => {
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      
      // Use the correct endpoint with classId
      const response = await axios.get(`http://localhost:8000/api/classes/${classId}/posts/${postId}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
      const post = response.data;
      
      // Set the form fields with the post data
      setPostTitle(post.title);
      setContent(post.content);
      
      // Show the post form
    setShowNewPostForm(true);
      setEditingPostId(postId);
      
      setLoading(false);
    } catch (error) {
      console.error('Error fetching post for editing:', error);
      toast.error('Failed to load post for editing');
      setLoading(false);
    }
  };

  const handleDeletePost = async (postId) => {
    if (!confirm('Are you sure you want to delete this post?')) return;
    
      try {
      setLoading(true);
        const token = localStorage.getItem('token');
        await axios.delete(`http://localhost:8000/api/classes/${classId}/posts/${postId}`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        
      // Remove the post from the state
      setPosts(posts.filter(post => post.id !== postId));
      toast.success('Post deleted successfully');
      
      setLoading(false);
    } catch (error) {
      console.error('Error deleting post:', error);
      toast.error('Failed to delete post');
      setLoading(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (!postTitle.trim()) {
      toast.error('Please enter a post title');
      return;
    }
    
    try {
      setLoading(true);
      const token = localStorage.getItem('token');
      
      const postData = {
        title: postTitle,
        content: content,
        class_id: classId
      };
      
      let response;
      
      if (editingPostId) {
        // Update existing post with the correct endpoint
        response = await axios.put(
          `http://localhost:8000/api/classes/${classId}/posts/${editingPostId}`, 
          postData, 
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );
        
        // Update the post in the state
        setPosts(posts.map(post => 
          post.id === editingPostId ? { ...post, ...response.data } : post
        ));
        
        toast.success('Post updated successfully');
      } else {
        // Create new post
        response = await axios.post(
          `http://localhost:8000/api/classes/${classId}/posts`, 
          postData, 
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );
        
        // Add the new post to the state
        setPosts([response.data, ...posts]);
        
        toast.success('Post created successfully');
      }
      
      // Reset form
      setPostTitle('');
      setContent('');
      setShowNewPostForm(false);
      setEditingPostId(null);
      
      setLoading(false);
    } catch (error) {
      console.error('Error saving post:', error);
      toast.error(editingPostId ? 'Failed to update post' : 'Failed to create post');
      setLoading(false);
    }
  };

  const handlePostAction = async (action, post) => {
    if (action === 'edit') {
      // Navigate to edit post or set edit mode
      handleEditPost(post.id);
    } else if (action === 'delete') {
      if (window.confirm('Are you sure you want to delete this post?')) {
        try {
          const token = localStorage.getItem('token');
          await axios.delete(`http://localhost:8000/api/classes/${classId}/posts/${post.id}`, {
            headers: { Authorization: `Bearer ${token}` }
          });
        // Refresh posts after deletion
        const postsResponse = await axios.get(`http://localhost:8000/api/classes/${classId}/posts`, {
          headers: { Authorization: `Bearer ${token}` }
        });
        setPosts(postsResponse.data);
          toast.success('Post deleted successfully');
      } catch (error) {
        console.error('Error deleting post:', error);
          toast.error('Failed to delete post');
        }
      }
    }
    // Close the menu after action
    setMenuOpen(null);
  };

  const handleLikePost = async (postId) => {
    // Prevent multiple clicks
    if (likesLoading[postId]) return;
    
    // Start loading
    setLikesLoading(prev => ({ ...prev, [postId]: true }));
    
    try {
      const token = localStorage.getItem('token');
      
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
      const response = await axios.post(`http://localhost:8000/api/classes/${classId}/posts/${postId}/like`, {}, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
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
      const response = await axios.get(`http://localhost:8000/api/classes/${classId}/posts/${postId}/likes`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      
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

  const loadCommentsForPost = async (postId) => {
    if (commentLoading[postId]) return;
    
    setCommentLoading(prev => ({ ...prev, [postId]: true }));
    
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(
        `http://localhost:8000/api/classes/${classId}/posts/${postId}/comments?limit=3`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
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
      const token = localStorage.getItem('token');
      const response = await axios.post(
        `http://localhost:8000/api/classes/${classId}/posts/${postId}/comments`,
        { content: commentText },
        { headers: { Authorization: `Bearer ${token}` } }
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
    <div className={`min-h-screen transition-all duration-500 ${darkMode ? 'bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200' : 'bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900'}`}>
      {/* Navbar */}
      <Navbar
        userInfo={userInfo}
        onSignOut={handleSignOut}
        darkMode={darkMode}
        logo="/logo.png"
      />

      {/* Side Panel */}
      <div className="fixed left-0 h-full w-64 bg-gray-50/70 dark:bg-gray-800/50 backdrop-blur-md border-r border-gray-200 dark:border-gray-700 p-6">
        {/* Search Bar */}
        <div className="mb-6">
          <div className="relative">
            <input
              type="text"
              placeholder="Search posts..."
              className={`w-full pl-10 pr-4 py-2 rounded-lg border ${
                darkMode 
                  ? 'bg-gray-700 border-gray-600 text-white' 
                  : 'bg-white border-gray-200'
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
          </div>
        </div>

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
      <div className="ml-64">
        {/* Posts Feed */}
        <div className="max-w-5xl mx-auto px-8 pt-32">
          {/* Blog Header - Moved down */}
          <div className="flex justify-between items-center mb-12">
            <div className="flex items-center space-x-6">
              <h1 className="text-2xl font-medium">
                {classDetails?.name || 'Loading class...'}
              </h1>
              <div className="flex items-center space-x-3">
                <span>Sort by:</span>
                <select className={`rounded-lg py-2 ${
                  darkMode 
                    ? 'bg-gray-800 border-gray-700' 
                    : 'bg-white border-gray-300'
                  } border`}
                >
                  <option>Recent Activity</option>
                </select>
              </div>
            </div>
            <div className="flex items-center space-x-6">
              <motion.button 
                onClick={() => setShowNewPostForm(true)}
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

          {/* Posts Grid */}
          <div className="space-y-8">
            {posts.map((post) => (
              <motion.div
                key={post.id}
                layout
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.3 }}
                className={`mb-6 p-6 rounded-xl shadow-sm ${
                  darkMode ? 'bg-gray-800' : 'bg-white'
                } relative`}
              >
                {/* Post Header and Details */}
                <div className="flex justify-between items-start mb-4">
                  <div className="flex items-center">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center ${
                      darkMode ? 'bg-gray-700' : 'bg-gray-200'
                    }`}>
                      {post.author?.[0] || '?'}
                      </div>
                    <div className="ml-3">
                      <h3 className={`font-medium ${darkMode ? 'text-white' : 'text-gray-900'}`}>
                        {post.author || 'Unknown Author'}
                        </h3>
                      </div>
                    </div>

                  {/* Add post actions menu here */}
                  <div className="relative">
                        <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setMenuOpen(menuOpen === post.id ? null : post.id);
                      }}
                      className="p-1 rounded-full hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                    >
                      <svg className="w-5 h-5 text-gray-500 dark:text-gray-400" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M10 6a2 2 0 110-4 2 2 0 010 4zM10 12a2 2 0 110-4 2 2 0 010 4zM10 18a2 2 0 110-4 2 2 0 010 4z" />
                          </svg>
                        </button>

                    {/* Dropdown menu */}
                    {menuOpen === post.id && (
                          <div 
                        className={`absolute right-0 mt-1 w-48 rounded-md shadow-lg z-10 ${
                          darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
                        }`}
                          >
                        <div className="py-1" role="menu" aria-orientation="vertical">
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                              handleEditPost(post.id);
                              setMenuOpen(null);
                                }}
                            className={`w-full text-left px-4 py-2 text-sm ${
                              darkMode ? 'text-gray-300 hover:bg-gray-700' : 'text-gray-700 hover:bg-gray-100'
                            }`}
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
                            className={`w-full text-left px-4 py-2 text-sm ${
                              darkMode ? 'text-red-400 hover:bg-gray-700' : 'text-red-600 hover:bg-gray-100'
                            }`}
                            role="menuitem"
                              >
                                Delete Post
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                  </div>

                {/* Post Title - without label */}
                <div 
                  className={`mb-4 px-4 py-3 rounded-lg border cursor-pointer ${darkMode ? 'bg-gray-750 border-gray-600' : 'bg-blue-50 border-blue-100'}`}
                  onClick={() => navigate(`/class/${classId}/post/${post.id}`)}
                >
                  <h4 className={`text-xl font-bold ${darkMode ? 'text-white' : 'text-gray-800'}`}>
                    {post.title}
                  </h4>
                </div>
              
                {/* Post Content */}
                <div 
                  className="html-content mb-4 cursor-pointer prose dark:prose-invert max-w-none"
                  onClick={() => navigate(`/class/${classId}/post/${post.id}`)}
                  dangerouslySetInnerHTML={{ 
                    __html: truncateHTML(processHTMLWithDOM(post.content), 200) 
                  }}
                />
                
                {/* Comments Section */}
                <AnimatePresence>
                  {postCommentsVisible[post.id] && (
                    <motion.div
                      initial={{ height: 0, opacity: 0 }}
                      animate={{ height: 'auto', opacity: 1 }}
                      exit={{ height: 0, opacity: 0 }}
                      transition={{ duration: 0.3 }}
                      className="mt-4 pt-4 border-t dark:border-gray-700 overflow-hidden"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {/* New Comment Form */}
                      <form onSubmit={(e) => handleSubmitComment(post.id, e)} className="mb-4">
                        <div className="flex items-start gap-2">
                          <div className="w-8 h-8 rounded-full bg-gray-300 dark:bg-gray-700 flex items-center justify-center flex-shrink-0 text-sm">
                            {userInfo?.first_name?.[0] || '?'}
                    </div>
                          <div className="flex-1">
                            <textarea
                              value={newCommentText[post.id] || ''}
                              onChange={(e) => setNewCommentText(prev => ({
                                ...prev,
                                [post.id]: e.target.value
                              }))}
                              placeholder="Add a comment..."
                              className="w-full p-2 text-sm bg-gray-50 dark:bg-gray-800 border dark:border-gray-700 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-500"
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
                              token={localStorage.getItem('token')}
                              onReply={(newComment) => {
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
                              onClick={() => navigate(`/class/${classId}/post/${post.id}`)}
                              className="text-center py-2 text-sm text-blue-500 hover:text-blue-700 dark:text-blue-400 cursor-pointer"
                            >
                              View all {commentCounts[post.id]} comments
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="py-4 text-center text-gray-500 dark:text-gray-400 text-sm">
                          No comments yet. Be the first to comment!
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
                
                {/* Post Actions/Stats */}
                <div className="flex items-center justify-between mt-4 pt-4 border-t dark:border-gray-700">
                  <div className="flex items-center space-x-6">
                    {/* Like button with animations */}
                    <button 
                      onClick={(e) => {
                        e.stopPropagation();
                        handleLikePost(post.id);
                      }}
                      className="flex items-center space-x-1 text-gray-500 hover:text-red-500 dark:text-gray-400 dark:hover:text-red-400 transition-colors relative"
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
                      className="flex items-center space-x-1 text-gray-500 hover:text-blue-500 dark:text-gray-400 dark:hover:text-blue-400 transition-colors"
                    >
                      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                      </svg>
                      {/* Ensure we're checking if commentCounts[post.id] exists */}
                      <span>Comment{commentCounts[post.id] ? ` (${commentCounts[post.id]})` : ''}</span>
                    </button>
                  </div>
                  
                  {/* Add the timestamp here */}
                  <span className="text-sm text-gray-500 dark:text-gray-400" data-timestamp={post.created_at}>
                    {formatRelativeTime(post.created_at)}
                  </span>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>

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
              initial={{ scale: 0.9, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.9, opacity: 0 }}
              className={`${
                darkMode ? 'bg-gray-800' : 'bg-white'
              } rounded-lg p-6 max-w-2xl w-full shadow-xl max-h-[90vh] overflow-y-auto`}
            >
              <div className="mb-4 flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-gray-300 flex items-center justify-center">
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
                </div>
                <span className="text-sm text-gray-600 dark:text-gray-300">
                  Posting as {localStorage.getItem('username')}
                </span>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                {/* Category Dropdown */}
                <div>
                  <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                    Category
                  </label>
                  <select
                    className={`w-full p-2 rounded-lg border ${
                      darkMode 
                        ? 'bg-gray-700 border-gray-600 text-white' 
                        : 'bg-white border-gray-300'
                    } focus:ring-2 focus:ring-blue-500 focus:border-transparent`}
                  >
                    <option value="">Select a category</option>
                    <option value="question">Question</option>
                    <option value="discussion">Discussion</option>
                    <option value="resource">Resource</option>
                    <option value="announcement">Announcement</option>
                  </select>
                </div>

                {/* Title Input - professional styling */}
                <div className={`mb-5 p-4 rounded-lg border ${darkMode ? 'bg-gray-750 border-gray-600' : 'bg-blue-50 border-blue-100'}`}>
                  <label htmlFor="post-title" className={`block text-base font-bold ${darkMode ? 'text-white' : 'text-gray-800'} mb-2`}>
                    Post Title (Required)
                  </label>
                <input
                  type="text"
                    id="post-title"
                    value={postTitle}
                    onChange={(e) => setPostTitle(e.target.value)}
                    className={`w-full p-3 rounded-lg border text-lg ${
                    darkMode 
                        ? 'bg-gray-800 border-gray-600 text-white' 
                        : 'bg-white border-blue-200 text-gray-800'
                    }`}
                    placeholder="Enter a descriptive title for your post"
                  required
                />
                  <div className="mt-2 text-xs text-gray-500">
                    This will be displayed at the top of your post
                  </div>
                </div>

                {/* Content Input */}
                <div className="relative">
                  <Editor
                    apiKey="edr7zffd9q7v6okan1ka9dbc23ugp710ycjhcfroxd9undjo"
                    init={TINYMCE_CONFIG}
                    value={content}
                    onEditorChange={(content) => {
                      setContent(content);
                    }}
                  />
                  
                  {/* Add the MediaPreview component here */}
                  <MediaPreview 
                    media={postContent.media}
                    files={postContent.files}
                    onRemove={handleRemoveMedia}
                  />
                  
                  {/* Code Snippets Display */}
                  {postContent.codeSnippets.map((snippet, index) => (
                    <div key={snippet.id} className="mt-4 rounded-lg overflow-hidden border dark:border-gray-600">
                      <div className={`flex items-center justify-between p-2 ${
                        darkMode ? 'bg-gray-700' : 'bg-gray-100'
                      }`}>
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-mono ${
                            darkMode ? 'text-gray-300' : 'text-gray-600'
                          }`}>
                            {snippet.language}
                          </span>
                        </div>
                        <button
                          onClick={() => {
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
                      <div className={`p-4 font-mono text-sm ${
                        darkMode ? 'bg-gray-800' : 'bg-gray-50'
                      }`}>
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
                      className={`p-4 cursor-pointer flex items-center gap-2 ${
                        darkMode ? 'bg-gray-700' : 'bg-gray-100'
                      }`}
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
                        className={`flex-1 bg-transparent border-none focus:ring-0 ${
                          darkMode ? 'text-white' : 'text-gray-900'
                        }`}
                        placeholder="Write a title"
                        onClick={e => e.stopPropagation()}
                      />
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
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
                          className={`w-full p-2 rounded border ${
                            darkMode 
                              ? 'bg-gray-700 border-gray-600 text-white' 
                              : 'bg-white border-gray-300'
                          }`}
                          placeholder="Add content to expand"
                          rows="3"
                        />
                      </div>
                    )}
                  </div>
                ))}

                {/* Action Buttons */}
                <div className="flex justify-end gap-4">
                  <motion.button
                    type="button"
                    onClick={() => setShowNewPostForm(false)}
                    className="px-6 py-2 rounded-lg bg-gray-200 hover:bg-gray-300 dark:bg-gray-700 dark:hover:bg-gray-600"
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    Cancel
                  </motion.button>
                  <motion.button
                    type="submit"
                    className={`px-6 py-2 rounded-lg text-white ${
                      darkMode ? 'bg-teal-600 hover:bg-teal-500' : 'bg-blue-600 hover:bg-blue-700'
                    }`}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    Publish
                  </motion.button>
                </div>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ClassFeed; 

