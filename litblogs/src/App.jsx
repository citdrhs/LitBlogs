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
import ForgotPassword from "./ForgotPassword";
import ResetPassword from "./ResetPassword";
import StudentDetails from "./components/StudentDetails";
import PrivacyPolicy from './PrivacyPolicy';
import TermsOfService from './TermsOfService';
import { useState, useEffect } from 'react';

function App() {
  const [darkMode, setDarkMode] = useState(() => {
    return JSON.parse(localStorage.getItem('darkMode')) ?? false;
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
  }, [darkMode]);

  return (
    <Routes>
      <Route path="/" element={<LitBlogs darkMode={darkMode} toggleDarkMode={toggleDarkMode} />} />
      <Route path="/help" element={<Help />} />
      <Route path="/sign-in" element={<SignIn />} />
      <Route path="/sign-up" element={<SignUp />} />
      <Route path="/teacher-dashboard" element={<TeacherDashboard />} />
      <Route path="/class-feed" element={<ClassFeed />} />
      <Route path="/class-feed/:classId" element={<ClassFeed />} />
      <Route path="/admin-dashboard" element={<AdminDashboard />} />
      <Route path="/class/:classId/post/:postId" element={<PostView />} />
      <Route path="/class/:classId/student/:studentId" element={<StudentDetails darkMode={darkMode} />} />
      <Route path="/student-hub" element={<StudentHub />} />
      <Route path="/profile" element={<Profile />} />
      <Route path="/profile/:userId" element={<Profile />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/privacy-policy" element={<PrivacyPolicy />} />
      <Route path="/terms" element={<TermsOfService />} />
    </Routes>
  );
}

export default App;