import { useState, useEffect, useRef } from "react";
import { Link, useNavigate, useLocation } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import axios from 'axios';
import Loader from './components/Loader';

const ResetPassword = () => {
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [darkMode, setDarkMode] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [isSuccess, setIsSuccess] = useState(false);
  const [token, setToken] = useState("");
  const dropdownRef = useRef(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    // Extract token from URL query parameters
    const queryParams = new URLSearchParams(location.search);
    const resetToken = queryParams.get('token');
    
    if (!resetToken) {
      setMessage("Invalid or missing reset token. Please request a new password reset.");
      return;
    }
    
    setToken(resetToken);
  }, [location]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const toggleDropdown = () => {
    setIsDropdownOpen((prev) => !prev);
  };

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

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Validate passwords match
    if (password !== confirmPassword) {
      setMessage("Passwords don't match");
      return;
    }
    
    // Validate password strength
    if (password.length < 8) {
      setMessage("Password must be at least 8 characters long");
      return;
    }
    
    setIsLoading(true);
    setMessage("");
    
    try {
      const response = await axios.post('http://localhost:8000/api/auth/reset-password', {
        token,
        new_password: password
      });
      
      setIsSuccess(true);
      setMessage("Your password has been reset successfully!");
      
      // Redirect to sign-in page after 3 seconds
      setTimeout(() => {
        navigate('/sign-in');
      }, 3000);
      
    } catch (error) {
      console.error('Password reset error:', error);
      setIsSuccess(false);
      
      if (error.response?.status === 400) {
        setMessage("Invalid or expired token. Please request a new password reset.");
      } else if (error.response?.data?.detail) {
        setMessage(error.response.data.detail);
      } else {
        setMessage("An error occurred. Please try again later.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className={`min-h-screen flex items-center justify-center transition-all duration-500 ${darkMode ? 'bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200' : 'bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900'}`}>
      {/* Navbar */}
      <motion.nav 
        className="navbar z-50 fixed top-2 left-470 transform -translate-x-1/2 w-auto bg-white/80 dark:bg-gray-800/80 backdrop-blur-md py-2 px-6 rounded-xl shadow-lg border border-gray-200/50 dark:border-gray-700/50"
        initial={{ opacity: 0, y: -30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: "easeOut" }}
      >
        <div className="flex items-center gap-6 whitespace-nowrap">
          {/* Logo */}
          <Link to="/">
            <motion.img
              src="/dren/logo.png"
              alt="Logo"
              className="h-8 transition-transform duration-300 hover:scale-110 cursor-pointer"
              whileHover={{ scale: 1.1 }}
            />
          </Link>

          {/* Links (Visible on Larger Screens) */}
          <div className="hidden md:flex items-center gap-6">
            <Link
              to="/"
              className={`text-gray-900 dark:text-white hover:${darkMode ? 'text-cyan-400' : 'text-blue-500'} transition-colors duration-300 text-sm md:text-base`}
            >
              Home
            </Link>
          </div>

          {/* Dropdown Menu (Visible on Smaller Screens) */}
          <div className="md:hidden relative" ref={dropdownRef}>
            <button
              onClick={toggleDropdown}
              className="text-gray-900 dark:text-white hover:text-blue-500 transition-colors duration-300 focus:outline-none"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className={`h-6 w-6 transition-transform duration-300 ${isDropdownOpen ? "rotate-90" : ""}`}
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4 6h16M4 12h16M4 18h16"
                />
              </svg>
            </button>

            {/* Dropdown Content */}
            <AnimatePresence>
              {isDropdownOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className="absolute right-0 mt-2 w-56 bg-white dark:bg-gray-800 rounded-md shadow-lg py-2"
                >
                  <Link
                    to="/"
                    className="block px-4 py-2 text-gray-900 dark:text-white hover:bg-gray-100 dark:hover:bg-gray-700 truncate"
                  >
                    Home
                  </Link>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </div>
      </motion.nav>
      
      <motion.div
        className="max-w-md w-full mt-16 mb-16 p-8 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 top-5"
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      >
        {/* Reset Password Form */}
        <motion.h2
          className="text-3xl font-semibold text-center mb-6 dark:bg-gray-800"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          Set New Password
        </motion.h2>

        {!token && !isSuccess ? (
          <motion.div
            className="text-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6 }}
          >
            <p className="text-red-500 mb-6">{message}</p>
            <Link
              to="/forgot-password"
              className={`text-sm text-blue-500 hover:text-blue-700 transition duration-300 ${darkMode ? 'hover:text-blue-400' : 'hover:text-blue-600'}`}
            >
              Request New Password Reset
            </Link>
          </motion.div>
        ) : isSuccess ? (
          <motion.div
            className="text-center"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.6 }}
          >
            <div className="mb-6">
              <svg 
                className="w-16 h-16 mx-auto text-green-500" 
                fill="none" 
                stroke="currentColor" 
                viewBox="0 0 24 24" 
                xmlns="http://www.w3.org/2000/svg"
              >
                <path 
                  strokeLinecap="round" 
                  strokeLinejoin="round" 
                  strokeWidth="2" 
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                ></path>
              </svg>
            </div>
            <p className="text-gray-600 dark:text-gray-300 mb-6">
              {message}
            </p>
            <p className="text-gray-500 dark:text-gray-400 text-sm">
              Redirecting to sign in page...
            </p>
          </motion.div>
        ) : (
          <form onSubmit={handleSubmit}>
            <motion.div
              className="mb-4"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.3 }}
            >
              <label htmlFor="password" className="block text-sm font-medium mb-2">New Password</label>
              <input
                id="password"
                type="password"
                className={`w-full p-4 border rounded-lg ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'} focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-300 transform focus:scale-105`}
                placeholder="Enter your new password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={8}
              />
            </motion.div>

            <motion.div
              className="mb-6"
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.4 }}
            >
              <label htmlFor="confirmPassword" className="block text-sm font-medium mb-2">Confirm Password</label>
              <input
                id="confirmPassword"
                type="password"
                className={`w-full p-4 border rounded-lg ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'} focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-300 transform focus:scale-105`}
                placeholder="Confirm your new password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
              />
            </motion.div>

            {message && (
              <motion.p
                className={`text-${isSuccess ? 'green' : 'red'}-500 text-sm text-center mb-4`}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ duration: 0.4 }}
              >
                {message}
              </motion.p>
            )}

            <motion.button
              type="submit"
              className={`w-full p-4 text-white rounded-lg text-lg focus:outline-none ${darkMode ? 'bg-teal-700 hover:bg-teal-600' : 'bg-blue-600 hover:bg-blue-700'} transition-colors duration-300`}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.95 }}
            >
              Reset Password
            </motion.button>
          </form>
        )}

        {!isSuccess && (
          <div className="mt-6 text-center">
            <Link
              to="/sign-in"
              className={`text-sm text-blue-500 hover:text-blue-700 transition duration-300 ${darkMode ? 'hover:text-blue-400' : 'hover:text-blue-600'}`}
            >
              Back to Sign In
            </Link>
          </div>
        )}
      </motion.div>
      
      <motion.div
        className="absolute top-6 right-6 z-10"
        whileHover={{ scale: 1.1 }}
      >
        <button
          onClick={toggleDarkMode}
          className="bg-gray-800 text-white p-2 rounded-full shadow-lg"
        >
          {darkMode ? "🌞" : "🌙"}
        </button>
      </motion.div>

      {/* Loading Overlay */}
      <AnimatePresence>
        {isLoading && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          >
            <Loader />
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default ResetPassword;