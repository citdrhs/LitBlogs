import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import LitBlogs from "./LitBlogs";
import Help from "./Help";
import SignIn from "./Sign-in";
import SignUp from "./Sign-up";
import TeacherDashboard from "./TeacherDashboard";
import ClassFeed from "./ClassFeed";
import AdminDashboard from "./AdminDashboard";
import PostView from "./PostView";
import StudentHub from "./StudentHub";
import Profile from "./Profile";
import Settings from "./Settings";
import AssignmentSubmissions from "./AssignmentSubmissions";
import ForgotPassword from "./ForgotPassword";
import ResetPassword from "./ResetPassword";
import StudentDetails from "./components/StudentDetails";
import ProtectedRoute from "./components/ProtectedRoute";
import PrivacyPolicy from './PrivacyPolicy';
import TermsOfService from './TermsOfService';
import { useState, useEffect } from 'react';
import { applyGlobalUserSettings, getLocalUserSettings } from './utils/userSettings';

function App() {
  const [darkMode, setDarkMode] = useState(() => {
    return getLocalUserSettings().darkMode;
  });

  // Toggle dark mode function
  const toggleDarkMode = () => {
    setDarkMode((prevDarkMode) => {
      const newDarkMode = !prevDarkMode;
      localStorage.setItem('darkMode', JSON.stringify(newDarkMode));
      return newDarkMode;
    });
  };

  // Apply dark mode class to document
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }

    applyGlobalUserSettings({ ...getLocalUserSettings(), darkMode });
  }, [darkMode]);

  useEffect(() => {
    applyGlobalUserSettings(getLocalUserSettings());
  }, []);

  return (
    <Routes>
      <Route path="/" element={<LitBlogs darkMode={darkMode} toggleDarkMode={toggleDarkMode} />} />
      <Route path="/help" element={<Help />} />
      <Route path="/sign-in" element={<SignIn />} />
      <Route path="/sign-up" element={<SignUp />} />
      <Route path="/teacher-dashboard" element={<ProtectedRoute><TeacherDashboard /></ProtectedRoute>} />
      <Route path="/class-feed" element={<ProtectedRoute><ClassFeed /></ProtectedRoute>} />
      <Route path="/class-feed/:classId" element={<ProtectedRoute><ClassFeed /></ProtectedRoute>} />
      <Route path="/class/:classId/assignment/:assignmentId/submissions" element={<ProtectedRoute><AssignmentSubmissions /></ProtectedRoute>} />
      <Route path="/admin-dashboard" element={<ProtectedRoute><AdminDashboard /></ProtectedRoute>} />
      <Route path="/class/:classId/post/:postId" element={<ProtectedRoute><PostView /></ProtectedRoute>} />
      <Route path="/class/:classId/student/:studentId" element={<ProtectedRoute><StudentDetails darkMode={darkMode} /></ProtectedRoute>} />
      <Route path="/student-hub" element={<ProtectedRoute><StudentHub /></ProtectedRoute>} />
      <Route path="/profile" element={<ProtectedRoute><Profile /></ProtectedRoute>} />
      <Route path="/profile/:userId" element={<ProtectedRoute><Profile /></ProtectedRoute>} />
      <Route path="/settings" element={<ProtectedRoute><Settings onDarkModeChange={setDarkMode} /></ProtectedRoute>} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/privacy-policy" element={<PrivacyPolicy />} />
      <Route path="/terms" element={<TermsOfService />} />
    </Routes>
  );
}

export default App;
