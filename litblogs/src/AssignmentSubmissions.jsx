import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import axios from 'axios';
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import Loader from './components/Loader';

const AssignmentSubmissions = () => {
  const { classId, assignmentId } = useParams();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [darkMode, setDarkMode] = useState(() => JSON.parse(localStorage.getItem('darkMode')) ?? false);
  const [userInfo, setUserInfo] = useState(null);
  const [assignment, setAssignment] = useState(null);
  const [submissions, setSubmissions] = useState([]);
  const [replyDrafts, setReplyDrafts] = useState({});
  const [replyLoading, setReplyLoading] = useState({});

  const loadData = async () => {
    try {
      setLoading(true);
      setError(null);

      const token = localStorage.getItem('token');
      if (!token) {
        navigate('/sign-in');
        return;
      }

      const storedUserInfo = localStorage.getItem('user_info');
      if (storedUserInfo) {
        setUserInfo(JSON.parse(storedUserInfo));
      }

      const [assignmentsResponse, submissionsResponse] = await Promise.all([
        axios.get(`http://localhost:8000/api/classes/${classId}/assignments`, {
          headers: { Authorization: `Bearer ${token}` }
        }),
        axios.get(`http://localhost:8000/api/classes/${classId}/assignments/${assignmentId}/submissions`, {
          headers: { Authorization: `Bearer ${token}` }
        })
      ]);

      const matchedAssignment = (assignmentsResponse.data || []).find(
        (item) => String(item.id) === String(assignmentId)
      );

      setAssignment(matchedAssignment || null);
      setSubmissions(submissionsResponse.data || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to load assignment submissions');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [classId, assignmentId]);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  const handleSignOut = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user_info');
    localStorage.removeItem('class_info');
    navigate('/');
  };

  const submitReply = async (submissionId) => {
    const content = (replyDrafts[submissionId] || '').trim();
    if (!content) return;

    const token = localStorage.getItem('token');
    if (!token) {
      navigate('/sign-in');
      return;
    }

    try {
      setReplyLoading((prev) => ({ ...prev, [submissionId]: true }));

      await axios.post(
        `http://localhost:8000/api/classes/${classId}/assignments/${assignmentId}/submissions/${submissionId}/replies`,
        { content },
        { headers: { Authorization: `Bearer ${token}` } }
      );

      setReplyDrafts((prev) => ({ ...prev, [submissionId]: '' }));
      await loadData();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to post reply');
    } finally {
      setReplyLoading((prev) => ({ ...prev, [submissionId]: false }));
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-r from-indigo-100 to-pink-100 dark:from-slate-800 dark:to-gray-950">
        <Loader />
      </div>
    );
  }

  return (
    <div className={`min-h-screen flex flex-col ${darkMode ? 'bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200' : 'bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900'}`}>
      <Navbar
        userInfo={userInfo}
        onSignOut={handleSignOut}
        darkMode={darkMode}
        logo="/dren/logo.png"
      />

      <main className="flex-1 max-w-5xl w-full mx-auto px-6 pt-28 pb-10">
        <div className="flex items-center justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold">{assignment?.title || 'Assignment Submissions'}</h1>
            {assignment?.description && (
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">{assignment.description}</p>
            )}
          </div>
          <button
            onClick={() => navigate(`/class-feed/${classId}`)}
            className={`px-4 py-2 rounded-lg ${darkMode ? 'bg-gray-700 text-gray-200' : 'bg-white text-gray-700 border border-gray-300'}`}
          >
            Back to Class
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-lg border border-red-300 bg-red-50 text-red-700 px-4 py-3">
            {error}
          </div>
        )}

        {submissions.length === 0 ? (
          <div className={`rounded-xl p-6 ${darkMode ? 'bg-gray-800' : 'bg-white'} shadow`}>No submissions yet.</div>
        ) : (
          <div className="space-y-4">
            {submissions.map((submission) => (
              <div
                key={submission.id}
                className={`rounded-xl p-5 shadow ${darkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'}`}
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="font-semibold">
                    {submission.student?.first_name} {submission.student?.last_name}
                  </div>
                  <div className="flex items-center gap-2">
                    {submission.ai_percentage !== null && submission.ai_percentage !== undefined ? (
                      <span className={`px-2 py-1 text-xs font-bold rounded-full ${
                        submission.ai_percentage > 50
                          ? 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                          : 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                      }`}>
                        {submission.ai_percentage}% AI
                      </span>
                    ) : (
                      <span className="px-2 py-1 text-xs font-medium rounded-full bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">
                        AI pending
                      </span>
                    )}
                    <div className="text-xs text-gray-500 dark:text-gray-400">
                      {new Date(submission.submitted_at).toLocaleString()}
                    </div>
                  </div>
                </div>

                <p className="text-sm whitespace-pre-wrap mb-3">{submission.content || 'No content provided.'}</p>

                <div className="space-y-2 mb-3">
                  {(submission.replies || []).map((reply) => (
                    <div
                      key={reply.id}
                      className={`rounded-lg p-3 text-sm ${darkMode ? 'bg-gray-900 border border-gray-700' : 'bg-gray-50 border border-gray-200'}`}
                    >
                      <div className="font-medium">
                        {reply.user?.first_name} {reply.user?.last_name}
                      </div>
                      <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
                        {new Date(reply.created_at).toLocaleString()}
                      </div>
                      <div className="whitespace-pre-wrap">{reply.content}</div>
                    </div>
                  ))}
                </div>

                <div className="flex flex-col gap-2">
                  <textarea
                    value={replyDrafts[submission.id] || ''}
                    onChange={(e) => setReplyDrafts((prev) => ({ ...prev, [submission.id]: e.target.value }))}
                    rows={2}
                    placeholder="Write a reply..."
                    className={`w-full rounded-lg p-3 border ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'}`}
                  />
                  <div className="flex justify-end">
                    <button
                      onClick={() => submitReply(submission.id)}
                      disabled={replyLoading[submission.id]}
                      className="px-4 py-2 rounded-lg text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-60"
                    >
                      {replyLoading[submission.id] ? 'Posting...' : 'Reply'}
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      <Footer darkMode={darkMode} />
    </div>
  );
};

export default AssignmentSubmissions;
