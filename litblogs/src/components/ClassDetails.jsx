import { useState, useEffect } from 'react';
import { motion } from 'framer-motion';
import axios from 'axios';
import Navbar from './Navbar';
import { useNavigate } from 'react-router-dom';
import Loader from './Loader';
import ReactHtmlParser from 'react-html-parser';

// Format relative time (e.g., "2 hours ago")
const formatRelativeTime = (dateString) => {
  if (!dateString) return '';
  
  const date = new Date(dateString);
  const now = new Date();
  const diffInSeconds = Math.floor((now - date) / 1000);
  
  // Define time intervals in seconds
  const intervals = {
    year: 31536000,
    month: 2592000,
    week: 604800,
    day: 86400,
    hour: 3600,
    minute: 60
  };
  
  // Check each interval
  for (const [unit, seconds] of Object.entries(intervals)) {
    const interval = Math.floor(diffInSeconds / seconds);
    
    if (interval >= 1) {
      return interval === 1 
        ? `1 ${unit} ago` 
        : `${interval} ${unit}s ago`;
    }
  }
  
  return 'Just now';
};

const formatDateSafe = (dateValue) => {
  if (!dateValue) return '—';
  const parsed = new Date(dateValue);
  if (Number.isNaN(parsed.getTime())) return '—';
  return parsed.toLocaleDateString();
};

const EMPTY_ASSIGNMENT_FORM = {
  title: '',
  description: '',
  due_date: '',
  visibility: 'class',
  allow_late: true,
};

const formatAssignmentDateInput = (dateValue) => {
  if (!dateValue) return '';
  const parsed = new Date(dateValue);
  if (Number.isNaN(parsed.getTime())) return '';
  const timezoneOffset = parsed.getTimezoneOffset() * 60000;
  return new Date(parsed.getTime() - timezoneOffset).toISOString().slice(0, 16);
};

const ClassDetails = ({ classData, darkMode, onBack, initialTab = 'Overview' }) => {
  const [userInfo, setUserInfo] = useState(null);
  const [activeTab, setActiveTab] = useState(initialTab);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [classDetails, setClassDetails] = useState(classData);
  const [students, setStudents] = useState([]);
  const [posts, setPosts] = useState([]);
  const [studentCount, setStudentCount] = useState(0);
  const [postCount, setPostCount] = useState(0);
  const [assignments, setAssignments] = useState([]);
  const [analytics, setAnalytics] = useState(null);
  const [showAssignmentForm, setShowAssignmentForm] = useState(false);
  const [assignmentForm, setAssignmentForm] = useState(EMPTY_ASSIGNMENT_FORM);
  const [assignmentSubmissions, setAssignmentSubmissions] = useState({});
  const [savingAssignment, setSavingAssignment] = useState(false);
  const [expandedAssignmentId, setExpandedAssignmentId] = useState(null);
  const [editingAssignmentId, setEditingAssignmentId] = useState(null);
  const navigate = useNavigate();

  const tabs = ['Overview', 'Students', 'Blogs', 'Assignments', 'Analytics'];
  const panelCardClasses = darkMode
    ? 'bg-gray-700 border-gray-500'
    : 'bg-white border-gray-200';
  const classCodeBadgeClasses = darkMode
    ? 'bg-blue-500/25 text-blue-100 border border-blue-300/40'
    : 'bg-blue-500/20 text-blue-700 border border-blue-200';

  useEffect(() => {
    const storedUserInfo = localStorage.getItem('user_info');
    if (storedUserInfo) {
      setUserInfo(JSON.parse(storedUserInfo));
    }
  }, []);

  useEffect(() => {
    setActiveTab(initialTab || 'Overview');
  }, [classData.id, initialTab]);

  const refreshAssignments = async (token) => {
    const assignmentsResponse = await axios.get(
      `/classes/${classData.id}/assignments`,
      { headers: { Authorization: `Bearer ${token}` } }
    );
    setAssignments(assignmentsResponse.data || []);
  };

  const resetAssignmentForm = () => {
    setAssignmentForm(EMPTY_ASSIGNMENT_FORM);
    setEditingAssignmentId(null);
    setShowAssignmentForm(false);
  };

  const openCreateAssignmentForm = () => {
    setAssignmentForm(EMPTY_ASSIGNMENT_FORM);
    setEditingAssignmentId(null);
    setShowAssignmentForm(true);
  };

  const openEditAssignmentForm = (assignment) => {
    setAssignmentForm({
      title: assignment.title || '',
      description: assignment.description || '',
      due_date: formatAssignmentDateInput(assignment.due_date),
      visibility: assignment.visibility || 'class',
      allow_late: assignment.allow_late ?? true,
    });
    setEditingAssignmentId(assignment.id);
    setShowAssignmentForm(true);
  };

  useEffect(() => {
    const fetchClassDetails = async () => {
      try {
        const token = localStorage.getItem('token');
        const response = await axios.get(
          `/classes/${classData.id}/details`,
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );
        setClassDetails(response.data);
        setStudentCount(response.data.enrollment_count || 0);
        setLoading(false);
        
        // Fetch students enrolled in the class
        const enrollmentResponse = await axios.get(
          `/classes/${classData.id}/students`,
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );
        setStudents(enrollmentResponse.data);
        setStudentCount(enrollmentResponse.data.length);
        
        // Fetch posts for this class
        const postsResponse = await axios.get(
          `/classes/${classData.id}/posts`,
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );
        setPosts(postsResponse.data);
        setPostCount(postsResponse.data.length);

        const [assignmentsResponse, analyticsResponse] = await Promise.all([
          axios.get(`/classes/${classData.id}/assignments`, {
            headers: { Authorization: `Bearer ${token}` }
          }),
          axios.get(`/classes/${classData.id}/analytics`, {
            headers: { Authorization: `Bearer ${token}` }
          })
        ]);
        setAssignments(assignmentsResponse.data || []);
        setAnalytics(analyticsResponse.data || null);
        
      } catch (error) {
        setError(error.response?.data?.detail || 'Failed to load class details');
        setLoading(false);
      }
    };

    fetchClassDetails();
  }, [classData.id]);
  
  // Function to truncate HTML content for preview
  const truncateHTML = (htmlContent, maxLength = 100) => {
    if (!htmlContent) return '';
    
    // Create a div to hold the HTML content
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = htmlContent;
    
    // Get text content
    const textContent = tempDiv.textContent || tempDiv.innerText || '';
    
    // Truncate text content
    if (textContent.length <= maxLength) {
      return htmlContent;
    }
    
    return textContent.substring(0, maxLength) + '...';
  };

  const handleSaveAssignment = async () => {
    try {
      setSavingAssignment(true);
      const token = localStorage.getItem('token');
      const payload = {
        title: assignmentForm.title,
        description: assignmentForm.description,
        due_date: assignmentForm.due_date,
        visibility: assignmentForm.visibility,
        allow_late: assignmentForm.allow_late,
      };

      if (editingAssignmentId) {
        await axios.put(
          `/classes/${classData.id}/assignments/${editingAssignmentId}`,
          payload,
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );
      } else {
        await axios.post(
          `/classes/${classData.id}/assignments`,
          payload,
          {
            headers: { Authorization: `Bearer ${token}` }
          }
        );
      }

      await refreshAssignments(token);
      resetAssignmentForm();
    } catch (error) {
      setError(error.response?.data?.detail || 'Failed to save assignment');
    } finally {
      setSavingAssignment(false);
    }
  };


  const loadAssignmentSubmissions = async (assignmentId) => {
    try {
      const token = localStorage.getItem('token');
      const response = await axios.get(
        `/classes/${classData.id}/assignments/${assignmentId}/submissions`,
        { headers: { Authorization: `Bearer ${token}` } }
      );
      setAssignmentSubmissions((prev) => ({
        ...prev,
        [assignmentId]: response.data
      }));
    } catch (error) {
      setError(error.response?.data?.detail || 'Failed to load submissions');
    }
  };

  const openPostReview = (postId) => {
    navigate(`/class/${classData.id}/post/${postId}`, {
      state: {
        postViewerContext: {
          backLabel: 'Back to Blog List',
          classDetailsTab: 'Blogs',
          selectedClass: classData,
          postSequence: posts.map(({ id, title }) => ({ id, title })),
        },
      },
    });
  };

  return (
    <div className={`p-6 rounded-lg border ${darkMode ? 'bg-gray-800 border-gray-600' : 'bg-white border-gray-200'}`}>
      <button 
        onClick={onBack}
        className="mb-4 flex items-center text-blue-500 hover:text-blue-700"
      >
        <svg className="w-5 h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Classes
      </button>

      {/* Class Title and Code */}
      <div className="flex justify-between items-center">
        <h2 className="text-3xl font-bold">{classData.name}</h2>
        <span className={`px-4 py-2 rounded-full ${classCodeBadgeClasses}`}>
          Code: {classDetails.access_code}
        </span>
      </div>

      {/* Tabs */}
      <div className="flex gap-4 border-b border-gray-200 dark:border-gray-700/80">
        {tabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 -mb-px ${
              activeTab === tab
                ? 'border-b-2 border-blue-500 text-blue-500'
                : 'text-gray-500 hover:text-gray-700 dark:text-gray-300 dark:hover:text-gray-100'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <div className="mt-6">
        {loading ? (
          <div className="min-h-[400px] flex items-center justify-center">
            <Loader />
          </div>
        ) : error ? (
          <div className="text-center py-8 text-red-500">
            <p>{error}</p>
          </div>
        ) : (
          <>
            {activeTab === 'Overview' && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="grid grid-cols-1 md:grid-cols-2 gap-6"
              >
                {/* Class Description */}
                <div className={`p-6 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-200'}`}>
                  <h3 className="text-xl font-semibold mb-4">Description</h3>
                  <p className="text-gray-600 dark:text-gray-300">{classDetails.description}</p>
                </div>

                {/* Quick Stats */}
                <div className={`p-6 rounded-lg border ${darkMode ? 'bg-gray-700 border-gray-600' : 'bg-white border-gray-200'}`}>
                    <h3 className="text-xl font-semibold mb-4">Quick Stats</h3>
                    <div className="grid grid-cols-2 gap-4">
                        <div>
                            <p className="text-sm text-gray-400">Total Students</p>
                            <p className="text-2xl font-bold">{studentCount}</p>
                        </div>
                        <div>
                            <p className="text-sm text-gray-400">Total Posts</p>
                            <p className="text-2xl font-bold">{postCount}</p>
                        </div>
                        <div>
                            <p className="text-sm text-gray-400">Active Today</p>
                          <p className="text-2xl font-bold">{analytics?.active_today || 0}</p>
                        </div>
                        <div>
                            <p className="text-sm text-gray-400">Avg. Engagement</p>
                          <p className="text-2xl font-bold">{analytics?.average_engagement || 0}%</p>
                        </div>
                    </div>
                </div>

              </motion.div>
            )}

            {activeTab === 'Students' && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
              >
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-gray-200 dark:divide-gray-700">
                    <thead className="bg-gray-50 dark:bg-gray-700">
                      <tr>
                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Name
                        </th>
                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Email
                        </th>
                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Joined
                        </th>
                        <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wider">
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="bg-white dark:bg-gray-800 divide-y divide-gray-200 dark:divide-gray-700">
                      {students.map((student) => (
                        <tr key={student.id} className="hover:bg-gray-50 dark:hover:bg-gray-800">
                          <td className="px-6 py-4 whitespace-nowrap">
                            <div className="flex items-center">
                              <div className="flex-shrink-0 h-10 w-10 rounded-full bg-blue-500 flex items-center justify-center text-white">
                                {student.first_name?.[0] || student.username?.[0] || '?'}
                              </div>
                              <div className="ml-4">
                                <div className="text-sm font-medium dark:text-white">
                                  {student.first_name} {student.last_name}
                                </div>
                                <div className="text-sm text-gray-500 dark:text-gray-400">
                                  @{student.username}
                                </div>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm dark:text-gray-300">
                            {student.email}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-400">
                            {formatDateSafe(student.created_at)}
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap text-sm">
                            <button 
                              onClick={() => navigate(`/class/${classData.id}/student/${student.id}`)}
                              className="text-indigo-600 hover:text-indigo-900 dark:text-indigo-400 dark:hover:text-indigo-300"
                            >
                              View Details
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </motion.div>
            )}

            {activeTab === 'Blogs' && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="grid gap-4 text-gray-900"
              >
                <h3 className="dark:text-gray-50 text-gray-900 text-xl font-semibold mb-4">Posts ({postCount})</h3>
                
                {posts.length > 0 ? (
                  posts.map((post) => {
                    const authorName = typeof post.author === 'string'
                      ? post.author
                      : post.author
                        ? `${post.author.first_name || ''} ${post.author.last_name || ''}`.trim()
                        : 'Unknown Author';
                    const authorInitial = authorName && authorName !== 'Unknown Author' ? authorName[0] : '?';

                    return (
                    <motion.div
                      key={post.id}
                      className="bg-white border border-gray-200 rounded-lg shadow-lg overflow-hidden cursor-pointer hover:shadow-xl transition-shadow duration-300"
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      whileHover={{ scale: 1.01 }}
                      onClick={() => openPostReview(post.id)}
                    >
                      <div className="p-6">
                        {/* Author Info */}
                        <div className="flex justify-between items-start">
                          <div className="flex items-center">
                            <div className="w-12 h-12 rounded-full bg-gray-300 flex items-center justify-center">
                              {authorInitial}
                            </div>
                            <div>
                              <h3 className="font-medium text-lg text-gray-900">
                                {authorName}
                              </h3>
                            </div>
                          </div>
                          
                          {/* Move the timestamp here */}
                          <span className="text-xs text-gray-500" data-timestamp={post.created_at}>
                            {formatRelativeTime(post.created_at)}
                          </span>
                        </div>

                        {/* Post Title and Preview */}
                        <div className="mb-2">
                          <h2 className="text-xl font-semibold text-gray-900">{post.title}</h2>
                        </div>
                        <div className="text-gray-600 line-clamp-3">
                          {ReactHtmlParser(truncateHTML(post.content, 150))}
                        </div>

                        {/* Post Stats */}
                        <div className="mt-4 flex items-center space-x-4 text-gray-500">
                          <div className="flex items-center space-x-1">
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z" />
                            </svg>
                            <span>{post.likes || 0}</span>
                          </div>
                          <div className="flex items-center space-x-1">
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                            </svg>
                            <span>{post.comments || 0}</span>
                          </div>
                        </div>
                      </div>
                    </motion.div>
                    );
                  })
                ) : (
                  <div className="text-center text-gray-500 py-8">
                    No posts yet
                  </div>
                )}
              </motion.div>
            )}

            {activeTab === 'Assignments' && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="space-y-6"
              >
                <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                  <div>
                    <h3 className="text-xl font-semibold">Assignments</h3>
                    <p className="text-sm text-gray-500 dark:text-gray-400">
                      Track submissions, due dates, and late work.
                    </p>
                  </div>
                  <button
                    onClick={openCreateAssignmentForm}
                    className="px-4 py-2 rounded-lg text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500"
                  >
                    Create Assignment
                  </button>
                </div>

                {showAssignmentForm && (
                  <div className={`p-6 rounded-lg border ${panelCardClasses} shadow-lg`}>
                    <h4 className="text-lg font-semibold mb-4">
                      {editingAssignmentId ? 'Edit Assignment' : 'New Assignment'}
                    </h4>
                    <div className="grid gap-4">
                      <input
                        type="text"
                        value={assignmentForm.title}
                        onChange={(e) => setAssignmentForm({ ...assignmentForm, title: e.target.value })}
                        placeholder="Assignment title"
                        className={`w-full p-3 rounded-lg border ${
                          darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300'
                        }`}
                      />
                      <textarea
                        value={assignmentForm.description}
                        onChange={(e) => setAssignmentForm({ ...assignmentForm, description: e.target.value })}
                        placeholder="Assignment description"
                        rows="4"
                        className={`w-full p-3 rounded-lg border ${
                          darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300'
                        }`}
                      />
                      <input
                        type="datetime-local"
                        value={assignmentForm.due_date}
                        onChange={(e) => setAssignmentForm({ ...assignmentForm, due_date: e.target.value })}
                        className={`w-full p-3 rounded-lg border ${
                          darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300'
                        }`}
                      />
                      <label className="flex items-center justify-between rounded-lg border border-gray-200 dark:border-gray-700 px-4 py-3">
                        <div>
                          <div className="text-sm font-medium text-gray-700 dark:text-gray-200">Allow late submissions</div>
                          <div className="text-xs text-gray-500 dark:text-gray-400">
                            Students can still turn work in after the due date.
                          </div>
                        </div>
                        <input
                          type="checkbox"
                          checked={assignmentForm.allow_late}
                          onChange={(e) => setAssignmentForm({ ...assignmentForm, allow_late: e.target.checked })}
                          className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                        />
                      </label>
                      <div className="flex flex-col gap-2">
                        <label className="text-sm font-medium text-gray-600 dark:text-gray-300">
                          Submission Visibility
                        </label>
                        <div className="flex flex-wrap gap-3">
                          <button
                            type="button"
                            onClick={() => setAssignmentForm({ ...assignmentForm, visibility: 'class' })}
                            className={`px-4 py-2 rounded-lg text-sm font-medium ${
                              assignmentForm.visibility === 'class'
                                ? 'bg-blue-500 text-white'
                                : darkMode
                                  ? 'bg-gray-700 text-gray-200'
                                  : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            Visible to Class
                          </button>
                          <button
                            type="button"
                            onClick={() => setAssignmentForm({ ...assignmentForm, visibility: 'private' })}
                            className={`px-4 py-2 rounded-lg text-sm font-medium ${
                              assignmentForm.visibility === 'private'
                                ? 'bg-purple-500 text-white'
                                : darkMode
                                  ? 'bg-gray-700 text-gray-200'
                                  : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            Teachers/Admin Only
                          </button>
                        </div>
                      </div>
                    </div>
                    <div className="mt-4 flex justify-end gap-3">
                      <button
                        onClick={resetAssignmentForm}
                        className={`px-4 py-2 rounded-lg ${
                          darkMode ? 'bg-gray-700 text-gray-200' : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleSaveAssignment}
                        disabled={savingAssignment}
                        className="px-4 py-2 rounded-lg text-white bg-blue-600 hover:bg-blue-500"
                      >
                        {savingAssignment ? 'Saving...' : editingAssignmentId ? 'Update Assignment' : 'Save Assignment'}
                      </button>
                    </div>
                  </div>
                )}

                <div className="grid gap-4">
                  {assignments.map((assignment) => (
                    <div
                      key={assignment.id}
                      className={`p-6 rounded-lg border ${panelCardClasses} shadow-lg`}
                    >
                      <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                        <div>
                          <h4 className="text-lg font-semibold">{assignment.title}</h4>
                          <p className="text-sm text-gray-500 dark:text-gray-400">
                            Due: {new Date(assignment.due_date).toLocaleString()}
                          </p>
                        </div>
                        <div className="flex flex-wrap gap-2">
                          <button
                            onClick={() => openEditAssignmentForm(assignment)}
                            className={`px-4 py-2 rounded-lg text-sm font-medium ${
                              darkMode ? 'bg-blue-900/40 text-blue-200' : 'bg-blue-50 text-blue-700'
                            }`}
                          >
                            Edit Assignment
                          </button>
                          <button
                            onClick={() => {
                              const nextId = expandedAssignmentId === assignment.id ? null : assignment.id;
                              setExpandedAssignmentId(nextId);
                              if (nextId && !assignmentSubmissions[assignment.id]) {
                                loadAssignmentSubmissions(assignment.id);
                              }
                            }}
                            className={`px-4 py-2 rounded-lg text-sm font-medium ${
                              darkMode ? 'bg-gray-700 text-gray-200' : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            {expandedAssignmentId === assignment.id ? 'Hide Submissions' : 'View Submissions'}
                          </button>
                        </div>
                      </div>
                      <div className="mt-2">
                        <div className="flex flex-wrap gap-2">
                          <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                            assignment.visibility === 'class'
                              ? 'bg-blue-500/10 text-blue-500'
                              : 'bg-purple-500/10 text-purple-500'
                          }`}>
                            {assignment.visibility === 'class' ? 'Public Submissions' : 'Teacher/Admin Only'}
                          </span>
                          <span className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${
                            assignment.allow_late
                              ? 'bg-emerald-500/10 text-emerald-500'
                              : 'bg-rose-500/10 text-rose-500'
                          }`}>
                            {assignment.allow_late ? 'Late Allowed' : 'Late Locked'}
                          </span>
                        </div>
                      </div>
                      <p className="mt-3 text-gray-600 dark:text-gray-300">{assignment.description || 'No description provided.'}</p>
                      <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
                        <div className="rounded-lg bg-emerald-500/10 p-3">
                          <div className="text-emerald-600 dark:text-emerald-300 font-semibold">On Time</div>
                          <div className="text-xl font-bold">{assignment.stats?.on_time ?? 0}</div>
                        </div>
                        <div className="rounded-lg bg-yellow-500/10 p-3">
                          <div className="text-yellow-600 dark:text-yellow-300 font-semibold">Late</div>
                          <div className="text-xl font-bold">{assignment.stats?.late ?? 0}</div>
                        </div>
                        <div className="rounded-lg bg-blue-500/10 p-3">
                          <div className="text-blue-600 dark:text-blue-300 font-semibold">Submitted</div>
                          <div className="text-xl font-bold">{assignment.stats?.submitted ?? 0}</div>
                        </div>
                        <div className="rounded-lg bg-rose-500/10 p-3">
                          <div className="text-rose-600 dark:text-rose-300 font-semibold">Missing</div>
                          <div className="text-xl font-bold">{assignment.stats?.missing ?? 0}</div>
                        </div>
                      </div>

                      {expandedAssignmentId === assignment.id && (
                        <div className="mt-6">
                          <h5 className="text-sm font-semibold mb-3">Submissions</h5>
                          {(assignmentSubmissions[assignment.id] || []).length === 0 ? (
                            <div className="text-sm text-gray-500 dark:text-gray-400">No submissions yet.</div>
                          ) : (
                            <div className="space-y-3">
                              {(assignmentSubmissions[assignment.id] || []).map((submission) => (
                                <div
                                  key={submission.id}
                                  className={`rounded-lg border p-3 ${darkMode ? 'border-gray-500 bg-gray-700' : 'border-gray-200 bg-white'}`}
                                >
                                  <div className="flex items-center justify-between text-sm">
                                    <span className="font-medium">
                                      {submission.student?.first_name} {submission.student?.last_name}
                                    </span>
                                    <span className={submission.is_late ? 'text-rose-500' : 'text-emerald-500'}>
                                      {submission.is_late ? 'Late' : 'On Time'}
                                    </span>
                                  </div>
                                  <div className="text-xs text-gray-500 dark:text-gray-400">
                                    Submitted: {new Date(submission.submitted_at).toLocaleString()}
                                  </div>
                                  <div className="mt-2 text-sm text-gray-600 dark:text-gray-300">
                                    {submission.content || 'No content provided.'}
                                  </div>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}

                  {assignments.length === 0 && (
                    <div className="text-center text-gray-500 dark:text-gray-400 py-8">
                      No assignments yet. Create one to start tracking submissions.
                    </div>
                  )}
                </div>
              </motion.div>
            )}

            {activeTab === 'Analytics' && (
              <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                className="grid grid-cols-1 md:grid-cols-2 gap-6"
              >
                <div className={`p-6 rounded-lg border ${panelCardClasses}`}>
                  <h3 className="text-xl font-semibold mb-4">Assignment Submissions</h3>
                  <div className="space-y-4">
                    {[
                      { label: 'On Time', value: analytics?.on_time_total || 0, color: 'bg-emerald-500' },
                      { label: 'Late', value: analytics?.late_total || 0, color: 'bg-yellow-500' },
                      { label: 'Missing', value: analytics?.missing_total || 0, color: 'bg-rose-500' },
                    ].map((item) => (
                      <div key={item.label}>
                        <div className="flex items-center justify-between text-sm mb-2">
                          <span>{item.label}</span>
                          <span className="text-gray-500 dark:text-gray-400">{item.value}</span>
                        </div>
                        <div className="h-2 rounded-full bg-gray-200 dark:bg-gray-700">
                          <div
                            className={`h-2 rounded-full ${item.color}`}
                            style={{
                              width: analytics?.submissions_total
                                ? `${Math.round((item.value / analytics.submissions_total) * 100)}%`
                                : '0%'
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                <div className={`p-6 rounded-lg border ${panelCardClasses}`}>
                  <h3 className="text-xl font-semibold mb-4">Class Activity</h3>
                  <div className="space-y-3 text-sm text-gray-500 dark:text-gray-400">
                    <div className="flex items-center justify-between">
                      <span>Total Students</span>
                      <span className="font-semibold text-gray-900 dark:text-gray-100">{analytics?.total_students || 0}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Total Posts</span>
                      <span className="font-semibold text-gray-900 dark:text-gray-100">{analytics?.total_posts || 0}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Posts in last 7 days</span>
                      <span className="font-semibold text-gray-900 dark:text-gray-100">{analytics?.posts_last_week || 0}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span>Assignments</span>
                      <span className="font-semibold text-gray-900 dark:text-gray-100">{analytics?.assignments_total || 0}</span>
                    </div>
                  </div>
                </div>

                <div className={`p-6 rounded-lg border ${panelCardClasses} md:col-span-2`}>
                  <h3 className="text-xl font-semibold mb-4">Posts Over Last 7 Days</h3>
                  <div className="flex items-end gap-3 h-40">
                    {(analytics?.posts_last_7_days || []).map((point) => (
                      <div key={point.date} className="flex flex-col items-center gap-2 flex-1">
                        <div
                          className="w-full rounded-md bg-blue-500/70"
                          style={{ height: `${Math.max(point.count * 12, 8)}px` }}
                          title={`${point.count} posts`}
                        />
                        <span className="text-xs text-gray-500 dark:text-gray-400">
                          {new Date(point.date).toLocaleDateString(undefined, { weekday: 'short' })}
                        </span>
                      </div>
                    ))}
                    {(!analytics || (analytics?.posts_last_7_days || []).length === 0) && (
                      <div className="text-sm text-gray-500 dark:text-gray-400">No activity yet.</div>
                    )}
                  </div>
                </div>
              </motion.div>
            )}
          </>
        )}
      </div>

    </div>
  );
};

export default ClassDetails; 
