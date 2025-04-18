import { BrowserRouter as Router, Routes, Route } from "react-router-dom";
import LitBlogs from "./LitBlogs";
import Tambellini from "./Tambellini";
import Musk from "./Musk";
import Help from "./Help";
import SignIn from "./Sign-in";
import SignUp from "./Sign-up";
import TeacherDashboard from "./TeacherDashboard";
import ClassFeed from "./ClassFeed";
import RoleSelection from "./RoleSelection";
import AdminDashboard from "./AdminDashboard";
import PostView from "./PostView";
import StudentHub from "./StudentHub";
import Profile from "./Profile";
import StudentDetails from "./components/StudentDetails";
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
      <Route path="/tambellini" element={<Tambellini />} />
      <Route path="/musk" element={<Musk />} />
      <Route path="/help" element={<Help />} />
      <Route path="/sign-in" element={<SignIn />} />
      <Route path="/sign-up" element={<SignUp />} />
      <Route path="/role-selection" element={<RoleSelection />} />
      <Route path="/teacher-dashboard" element={<TeacherDashboard />} />
      <Route path="/class-feed" element={<ClassFeed />} />
      <Route path="/class-feed/:classId" element={<ClassFeed />} />
      <Route path="/admin-dashboard" element={<AdminDashboard />} />
      <Route path="/class/:classId/post/:postId" element={<PostView />} />
      <Route path="/class/:classId/student/:studentId" element={<StudentDetails darkMode={darkMode} />} />
      <Route path="/student-hub" element={<StudentHub />} />
      <Route path="/Profile" element={<Profile/>}/>
    </Routes>
  );
}

export default App;