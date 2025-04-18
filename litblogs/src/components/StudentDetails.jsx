import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import axios from 'axios';
import Loader from './Loader';
import ReactHtmlParser from 'react-html-parser';
import { formatRelativeTime } from '../utils/timeUtils';
import { toast } from 'react-hot-toast';

const StudentDetails = ({ darkMode }) => {
  const { classId, studentId } = useParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [student, setStudent] = useState(null);
  const [posts, setPosts] = useState([]);
  const [classInfo, setClassInfo] = useState(null);
  const [activeTab, setActiveTab] = useState('overview');
  const [teacherNotes, setTeacherNotes] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);
  const [recentActivity, setRecentActivity] = useState([]);

  useEffect(() => {
    const fetchStudentDetails = async () => {
      try {
        setLoading(true);
        const token = localStorage.getItem('token');
        
        // Fetch student details
        const studentResponse = await axios.get(
          `http://localhost:8000/api/classes/${classId}/students/${studentId}`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        setStudent(studentResponse.data);
        setTeacherNotes(studentResponse.data.teacher_notes || '');
        
        // Fetch class details
        const classResponse = await axios.get(
          `http://localhost:8000/api/classes/${classId}/details`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        setClassInfo(classResponse.data);
        
        // Fetch student's posts in this class
        const postsResponse = await axios.get(
          `http://localhost:8000/api/classes/${classId}/students/${studentId}/posts`,
          { headers: { Authorization: `Bearer ${token}` } }
        );
        setPosts(postsResponse.data);
        
        // Generate dynamic recent activity based on posts
        const activities = [];
        
        // Add post activities
        postsResponse.data.slice(0, 3).forEach(post => {
          activities.push({
            type: 'post',
            description: `Created a new post: '${post.title}'`,
            timestamp: post.created_at
          });
        });
        
        // Add class enrollment activity
        activities.push({
          type: 'enrollment',
          description: `Joined class: ${classResponse.data.name}`,
          timestamp: studentResponse.data.enrollment_date
        });
        
        // Sort by most recent first
        activities.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        setRecentActivity(activities);
        
        setLoading(false);
      } catch (error) {
        console.error('Error fetching student details:', error);
        setError(error.response?.data?.detail || 'Failed to load student details');
        setLoading(false);
      }
    };
    
    fetchStudentDetails();
  }, [classId, studentId]);
  
  const saveTeacherNotes = async () => {
    try {
      setSavingNotes(true);
      const token = localStorage.getItem('token');
      
      await axios.put(
        `http://localhost:8000/api/classes/${classId}/students/${studentId}/notes`,
        { notes: teacherNotes },
        { headers: { Authorization: `Bearer ${token}` } }
      );
      
      toast.success('Notes saved successfully');
      setSavingNotes(false);
    } catch (error) {
      console.error('Error saving notes:', error);
      toast.error('Failed to save notes');
      setSavingNotes(false);
    }
  };
  
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

  if (loading) {
    return (
      <div className="min-h-[400px] flex items-center justify-center">
        <Loader />
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center py-8 text-red-500">
        <p>{error}</p>
      </div>
    );
  }

  return (
    <div className={`p-6 rounded-lg ${darkMode ? 'bg-gradient-to-br from-gray-900 to-gray-800' : 'bg-gradient-to-br from-white to-gray-100'}`}>
      {/* Back button */}
      <button 
        onClick={() => navigate('/teacher-dashboard')}
        className="mb-6 flex items-center text-blue-500 hover:text-blue-700"
      >
        <svg className="w-5 h-5 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Dashboard
      </button>
      
      {/* Student header */}
      <div className="flex items-start justify-between mb-8">
        <div className="flex items-center">
          <div className="h-16 w-16 rounded-full bg-gradient-to-r from-blue-500 to-indigo-500 flex items-center justify-center text-white text-2xl">
            {student?.first_name?.[0] || student?.username?.[0] || '?'}
          </div>
          <div className="ml-4">
            <h1 className="text-2xl font-bold dark:text-white">
              {student?.first_name} {student?.last_name}
            </h1>
            <p className="text-gray-600 dark:text-gray-300">@{student?.username}</p>
            <p className="text-gray-500 dark:text-gray-400 text-sm mt-1">{student?.email}</p>
          </div>
        </div>
        <div className="flex flex-col items-end">
          <div className="px-4 py-2 rounded-full bg-blue-500/20 text-blue-500">
            Enrolled: {new Date(student?.enrollment_date).toLocaleDateString()}
          </div>
          <div className="mt-2 px-4 py-2 rounded-full bg-green-500/20 text-green-500">
            Engagement: {student?.engagement_score}
          </div>
        </div>
      </div>
      
      {/* Tabs */}
      <div className="flex gap-4 border-b border-gray-200 dark:border-gray-700 mb-6">
        <button
          onClick={() => setActiveTab('overview')}
          className={`px-4 py-2 -mb-px ${
            activeTab === 'overview'
              ? 'border-b-2 border-blue-500 text-blue-500'
              : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Overview
        </button>
        <button
          onClick={() => setActiveTab('posts')}
          className={`px-4 py-2 -mb-px ${
            activeTab === 'posts'
              ? 'border-b-2 border-blue-500 text-blue-500'
              : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Posts
        </button>
        <button
          onClick={() => setActiveTab('activity')}
          className={`px-4 py-2 -mb-px ${
            activeTab === 'activity'
              ? 'border-b-2 border-blue-500 text-blue-500'
              : 'text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'
          }`}
        >
          Activity
        </button>
      </div>
      
      {/* Tab Content */}
      <div>
        {activeTab === 'overview' && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-8">
              <div className={`p-6 rounded-lg ${
                darkMode ? 'bg-gray-800/50' : 'bg-white/50'
              } shadow-sm backdrop-blur-sm`}>
                <h3 className="text-xl font-semibold mb-4 dark:text-white">Student Stats</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Posts</p>
                    <p className="text-2xl font-bold dark:text-white">{student?.posts_count || 0}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Comments</p>
                    <p className="text-2xl font-bold dark:text-white">{student?.comments_count || 0}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Likes Given</p>
                    <p className="text-2xl font-bold dark:text-white">{student?.likes_count || 0}</p>
                  </div>
                  <div>
                    <p className="text-sm text-gray-500 dark:text-gray-400">Class Rank</p>
                    <p className="text-2xl font-bold dark:text-white">#1</p>
                  </div>
                </div>
              </div>
              
              <div className={`p-6 rounded-lg ${
                darkMode ? 'bg-gray-800/50' : 'bg-white/50'
              } shadow-sm backdrop-blur-sm`}>
                <h3 className="text-xl font-semibold mb-4 dark:text-white">Recent Activity</h3>
                {recentActivity.length > 0 ? (
                  <div className="space-y-4">
                    {recentActivity.slice(0, 3).map((activity, index) => (
                      <div key={index} className="flex items-start">
                        <div className={`mt-1 h-3 w-3 rounded-full ${
                          activity.type === 'post' ? 'bg-green-500' : 
                          activity.type === 'comment' ? 'bg-blue-500' : 
                          activity.type === 'like' ? 'bg-red-500' : 'bg-yellow-500'
                        }`}></div>
                        <div className="ml-3">
                          <p className="text-gray-600 dark:text-gray-300">{activity.description}</p>
                          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
                            {formatRelativeTime(activity.timestamp)}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="text-gray-500 dark:text-gray-400">No recent activity</p>
                )}
              </div>
            </div>
            
            <div className={`p-6 rounded-lg ${
              darkMode ? 'bg-gray-800/50' : 'bg-white/50'
            } shadow-sm backdrop-blur-sm`}>
              <h3 className="text-xl font-semibold mb-4 dark:text-white">Teacher Notes</h3>
              <textarea
                value={teacherNotes}
                onChange={(e) => setTeacherNotes(e.target.value)}
                className={`w-full p-3 rounded-lg border ${
                  darkMode 
                    ? 'bg-gray-700 border-gray-600 text-white' 
                    : 'bg-white border-gray-300'
                } focus:ring-2 focus:ring-blue-500 focus:border-transparent`}
                rows="4"
                placeholder="Add notes about this student..."
              />
              <div className="flex justify-end mt-2">
                <button 
                  onClick={saveTeacherNotes}
                  disabled={savingNotes}
                  className={`px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 ${
                    savingNotes ? 'opacity-50 cursor-not-allowed' : ''
                  }`}
                >
                  {savingNotes ? 'Saving...' : 'Save Notes'}
                </button>
              </div>
            </div>
          </motion.div>
        )}
        
        {activeTab === 'posts' && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <h3 className="text-xl font-semibold mb-4 dark:text-white">Student Posts</h3>
            
            {posts.length > 0 ? (
              <div className="space-y-6">
                {posts.map(post => (
                  <motion.div
                    key={post.id}
                    className={`p-6 rounded-lg ${
                      darkMode ? 'bg-gray-800/50' : 'bg-white/50'
                    } shadow-sm backdrop-blur-sm`}
                    whileHover={{ scale: 1.01 }}
                  >
                    <h4 className="text-lg font-semibold mb-2 dark:text-white">{post.title}</h4>
                    <div className="text-gray-600 dark:text-gray-300 mb-4">
                      {ReactHtmlParser(truncateHTML(post.content, 200))}
                    </div>
                    <div className="flex justify-between items-center">
                      <div className="flex items-center space-x-4 text-gray-500 dark:text-gray-400">
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
                      <span className="text-sm text-gray-500 dark:text-gray-400">
                        {formatRelativeTime(post.created_at)}
                      </span>
                    </div>
                    <div className="mt-4">
                      <button 
                        onClick={() => navigate(`/class/${classId}/post/${post.id}`)}
                        className="text-blue-500 hover:text-blue-700"
                      >
                        View Full Post →
                      </button>
                    </div>
                  </motion.div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                This student hasn't created any posts yet.
              </div>
            )}
          </motion.div>
        )}
        
        {activeTab === 'activity' && (
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
          >
            <h3 className="text-xl font-semibold mb-4 dark:text-white">Activity Timeline</h3>
            
            {student?.activity_timeline?.length > 0 ? (
              <div className="relative border-l-2 border-gray-200 dark:border-gray-700 ml-4 pl-6 space-y-6">
                {student.activity_timeline.map((activity, index) => (
                  <div key={index} className="relative">
                    <div className="absolute -left-10 mt-1.5 h-4 w-4 rounded-full bg-blue-500"></div>
                    <div className={`p-4 rounded-lg ${
                      darkMode ? 'bg-gray-800/50' : 'bg-white/50'
                    } backdrop-blur-sm`}>
                      <p className="font-medium dark:text-white">{activity.title}</p>
                      <p className="text-gray-600 dark:text-gray-300 mt-1">{activity.description}</p>
                      <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                        {formatRelativeTime(activity.timestamp)}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-8 text-gray-500 dark:text-gray-400">
                No activity data available for this student.
              </div>
            )}
          </motion.div>
        )}
      </div>
    </div>
  );
};

export default StudentDetails; 