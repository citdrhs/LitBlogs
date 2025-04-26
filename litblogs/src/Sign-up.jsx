import { useState, useEffect, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import './LitBlogs.css'; // Import any custom styles here
import axios from 'axios';
import Loader from './components/Loader';
import { GoogleOAuthProvider, GoogleLogin, useGoogleLogin } from '@react-oauth/google';
import { useMsal } from "@azure/msal-react";
import { loginRequest } from "./config/msalConfig";
import { FaMicrosoft } from 'react-icons/fa';

const SignUp = () => {
  const navigate = useNavigate();
  const { instance } = useMsal();
  // State variables for form inputs
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [darkMode, setDarkMode] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const dropdownRef = useRef(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [role, setRole] = useState('');
  const [accessCode, setAccessCode] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [showSuccessModal, setShowSuccessModal] = useState(false);
  const [successData, setSuccessData] = useState(null);

  // Add this state for password strength
  const [passwordStrength, setPasswordStrength] = useState({
    score: 0,
    label: "Poor",
    color: "red-500",
    percent: 0
  });

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
  // Dark mode logic (same as previous)
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

  
  // Add this function to your Sign-up.jsx file
  const validatePassword = (password) => {
    // Check minimum length
    if (password.length < 8) {
      return "Password must be at least 8 characters long";
    }
    
    // Check for uppercase letter
    if (!/[A-Z]/.test(password)) {
      return "Password must contain at least one uppercase letter";
    }
    
    // Check for lowercase letter
    if (!/[a-z]/.test(password)) {
      return "Password must contain at least one lowercase letter";
    }
    
    // Check for number
    if (!/[0-9]/.test(password)) {
      return "Password must contain at least one number";
    }
    
    // Check for special character
    if (!/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)) {
      return "Password must contain at least one special character";
    }
    
    return null; // Password is valid
  };

  // Add this function and call it when the password changes
  const checkPasswordStrength = (password) => {
    let score = 0;
    
    // Basic requirements
    if (password.length >= 8) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/[a-z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)) score++;
    
    // Extra points for stronger passwords
    if (password.length >= 12) score++; // Bonus for longer passwords
    if (/(?=.*[0-9].*[0-9])/.test(password)) score++; // Bonus for multiple numbers
    if (/(?=.*[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?].*[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?])/.test(password)) score++; // Bonus for multiple special chars
    
    // Determine strength label and color
    let label, color;
    switch (true) {
      case (score < 5): // Doesn't meet minimum requirements
        label = "Poor";
        color = "red-500";
        break;
      case (score === 5): // Meets minimum requirements
        label = "Good";
        color = "green-400";
        break;
      case (score === 6):
        label = "Strong";
        color = "green-500";
        break;
      case (score >= 7):
        label = "Excellent";
        color = "green-700";
        break;
      default:
        label = "Poor";
        color = "red-500";
    }
    
    setPasswordStrength({ score, label, color, percent: Math.min(100, (score / 8) * 100) });
  };

  // Form submission handler
  const handleSubmit = async (e) => {
    e.preventDefault();
    
    try {
      // Check if role is selected
      if (!role) {
        setErrorMessage("Please select a role");
        return;
      }

      // Validate access code for teachers and admins
      if ((role === 'TEACHER' || role === 'ADMIN') && !accessCode) {
        setErrorMessage(`Please enter the ${role.toLowerCase()} access code`);
        return;
      }

      // Check if passwords match
      if (password !== confirmPassword) {
        setErrorMessage("Passwords do not match");
        return;
      }

      // Validate password strength
      const passwordError = validatePassword(password);
      if (passwordError) {
        setErrorMessage(passwordError);
        return;
      }

      setIsLoading(true);
      setErrorMessage("");

      // Create username from email
      const username = email.split('@')[0] + Math.floor(Math.random() * 1000);

      // Send registration data to backend with correct field names
      const response = await axios.post('http://localhost:8000/api/auth/register', {
        username: username,
        email: email,
        password: password,
        first_name: firstName,  // Changed from firstName to first_name
        last_name: lastName,    // Changed from lastName to last_name
        role: role,
        access_code: accessCode // Changed from accessCode to access_code
      });

      // Handle successful registration
      localStorage.setItem('token', response.data.token);
      const userInfo = {
        role: response.data.role,
        userId: response.data.id,
        username: response.data.username,
        firstName: response.data.first_name,
      };
      localStorage.setItem('user_info', JSON.stringify(userInfo));

      // Show success modal
      setSuccessData({
        role: response.data.role,
        classInfo: response.data.class_info
      });
      setShowSuccessModal(true);

    } catch (error) {
      console.error('Registration error:', error);
      // Handle error message properly
      const errorMessage = error.response?.data?.detail || 'Registration failed. Please try again.';
      setErrorMessage(typeof errorMessage === 'object' ? errorMessage.msg : errorMessage);
    } finally {
      setIsLoading(false);
    }
  };

  // Google Sign Up Handlers
  const handleGoogleSignUpSuccess = async (credentialResponse) => {
    try {
      // Check if role is selected
      if (!role) {
        setErrorMessage("Please select a role before signing up with Google");
        return;
      }

      // Check if access code is provided for Teacher/Admin roles
      if ((role === 'TEACHER' || role === 'ADMIN') && !accessCode) {
        setErrorMessage(`Please enter an access code for ${role.toLowerCase()} role`);
        return;
      }

      setIsLoading(true);
      setErrorMessage("");
      
      // Get the ID token from the Google response
      const { credential } = credentialResponse;
      
      // Send the token to your backend for verification
      const response = await fetch('http://localhost:8000/api/auth/google-signup', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ 
          token: credential,
          role: role,
          accessCode: accessCode || undefined
        }),
        credentials: 'include'
      });
      
      const data = await response.json();
      
      if (!response.ok) {
        throw new Error(data.detail || 'Failed to sign up with Google');
      }
      
      // Store user info in localStorage
      localStorage.setItem('token', data.token);
      
      // Store user info
      const userInfo = {
        role: data.role,
        userId: data.id,
        username: data.username,
        firstName: data.first_name,
      };
      localStorage.setItem('user_info', JSON.stringify(userInfo));
      
      // For students, store class info
      if (data.role === 'STUDENT' && data.class_info) {
        const classInfo = {
          id: data.class_info.id,
          name: data.class_info.name,
          code: data.class_info.access_code
        };
        localStorage.setItem('class_info', JSON.stringify(classInfo));
      }
      
      // Show success modal with user role information
      setSuccessData({
        role: data.role,
        classInfo: data.class_info
      });
      setShowSuccessModal(true);
      
    } catch (error) {
      console.error('Google sign up failed:', error);
      setErrorMessage(error.message || 'Google sign up failed. Please try again.');
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleSignUpFailure = (error) => {
    console.error('Google sign up error:', error);
    setErrorMessage('Google sign up failed. Please try again.');
  };

  const googleSignUp = useGoogleLogin({
    onSuccess: async (tokenResponse) => {
      try {
        // Check if role is selected
        if (!role) {
          setErrorMessage("Please select a role before signing up with Google");
          return;
        }

        // Check if access code is provided for Teacher/Admin roles
        if ((role === 'TEACHER' || role === 'ADMIN') && !accessCode) {
          setErrorMessage(`Please enter an access code for ${role.toLowerCase()} role`);
          return;
        }
        
        setIsLoading(true);
        setErrorMessage("");
        
        // Get user information from Google using the access token
        const userInfoResponse = await fetch('https://www.googleapis.com/oauth2/v3/userinfo', {
          headers: {
            Authorization: `Bearer ${tokenResponse.access_token}`,
          },
        });
        
        const googleUserInfo = await userInfoResponse.json();
        
        // Send the user info to your backend
        const response = await fetch('http://localhost:8000/api/auth/google-signup', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ 
            googleData: {
              email: googleUserInfo.email,
              firstName: googleUserInfo.given_name,
              lastName: googleUserInfo.family_name,
              googleId: googleUserInfo.sub,
              picture: googleUserInfo.picture
            },
            role: role,
            accessCode: accessCode || undefined
          }),
          credentials: 'include'
        });
        
        const data = await response.json();
        
        if (!response.ok) {
          throw new Error(data.detail || 'Failed to sign up with Google');
        }
        
        // Store user info in localStorage
        localStorage.setItem('token', data.token);
        
        // Store user info
        const userInfo = {
          role: data.role,
          userId: data.id,
          username: data.username,
          firstName: data.first_name,
        };
        localStorage.setItem('user_info', JSON.stringify(userInfo));
        
        // For students, store class info
        if (data.role === 'STUDENT' && data.class_info) {
          const classInfo = {
            id: data.class_info.id,
            name: data.class_info.name,
            code: data.class_info.access_code
          };
          localStorage.setItem('class_info', JSON.stringify(classInfo));
        }
        
        // Show success modal with user role information
        setSuccessData({
          role: data.role,
          classInfo: data.class_info
        });
        setShowSuccessModal(true);
        
      } catch (error) {
        console.error('Google sign up failed:', error);
        setErrorMessage(error.message || 'Google sign up failed. Please try again.');
      } finally {
        setIsLoading(false);
      }
    },
    onError: handleGoogleSignUpFailure,
    scopes: 'email profile'
  });

  const handleMicrosoftSignUp = async () => {
    try {
      // Check if role is selected
      if (!role) {
        setErrorMessage("Please select a role");
        return;
      }

      // Validate access code for teachers and admins
      if ((role === 'TEACHER' || role === 'ADMIN') && !accessCode) {
        setErrorMessage(`Please enter the ${role.toLowerCase()} access code`);
        return;
      }

      setIsLoading(true);
      const response = await instance.loginPopup(loginRequest);
      
      // Send token to backend with role and access code
      const backendResponse = await axios.post('http://localhost:8000/api/auth/microsoft-signup', {
        msUserData: {
          email: response.account.username,
          firstName: response.account.name?.split(' ')[0] || '',
          lastName: response.account.name?.split(' ')[1] || '',
          microsoftId: response.account.localAccountId
        },
        role: role,
        accessCode: accessCode
      });
      
      // Handle successful signup
      localStorage.setItem('token', backendResponse.data.token);
      const userInfo = {
        role: backendResponse.data.role,
        userId: backendResponse.data.id,
        username: backendResponse.data.username,
        firstName: backendResponse.data.first_name,
      };
      localStorage.setItem('user_info', JSON.stringify(userInfo));

      // Show success modal with role info
      setSuccessData({
        role: backendResponse.data.role
      });
      setShowSuccessModal(true);
      
    } catch (error) {
      console.error('Microsoft signup error:', error);
      if (error.response?.status === 403) {
        setErrorMessage("Invalid access code");
      } else if (error.response?.status === 400) {
        setErrorMessage("User already exists. Please sign in instead.");
      } else {
        setErrorMessage(error.response?.data?.detail || error.message || 'Microsoft signup failed');
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
        className="max-w-md w-full p-8 mb-16 bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 mt-16"
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8, ease: "easeOut" }}
      >
        {/* Sign Up Form */}
        <motion.h2
          className="text-4xl font-semibold text-center mb-6 dark:bg-gray-800"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          Sign Up
        </motion.h2>

        <form onSubmit={handleSubmit}>
          {/* First Name Input */}
          <motion.div
            className="mb-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <label htmlFor="firstName" className="block text-sm font-medium mb-2">First Name</label>
            <input
              id="firstName"
              type="text"
              className={`w-full p-4 border rounded-lg ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'} focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-300 transform focus:scale-105`}
              placeholder="Enter your first name"
              value={firstName}
              onChange={(e) => setFirstName(e.target.value)}
              required
            />
          </motion.div>

          {/* Last Name Input */}
          <motion.div
            className="mb-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <label htmlFor="lastName" className="block text-sm font-medium mb-2">Last Name</label>
            <input
              id="lastName"
              type="text"
              className={`w-full p-4 border rounded-lg ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'} focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-300 transform focus:scale-105`}
              placeholder="Enter your last name"
              value={lastName}
              onChange={(e) => setLastName(e.target.value)}
              required
            />
          </motion.div>

          {/* Email Input */}
          <motion.div
            className="mb-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <label htmlFor="email" className="block text-sm font-medium mb-2">Email Address</label>
            <input
              id="email"
              type="email"
              className={`w-full p-4 border rounded-lg ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'} focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-300 transform focus:scale-105`}
              placeholder="Enter your email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </motion.div>

          {/* Password Input */}
          <motion.div
            className="mb-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6 }}
          >
            <label htmlFor="password" className="block text-sm font-medium mb-2">Password</label>
            <input
              id="password"
              type="password"
              className={`w-full p-4 border rounded-lg ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'} focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-300 transform focus:scale-105`}
              placeholder="Enter your password"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                checkPasswordStrength(e.target.value);
              }}
              required
            />
            <p className="mt-2 text-xs text-gray-500 dark:text-gray-400">
              Password must be at least 8 characters long and include uppercase, lowercase, number, and special character.
            </p>
          </motion.div>

          {/* Add this right after the password input field */}
          {password && (
            <div className="mt-2 mb-2">
              <div className="flex justify-between items-center mb-1">
                <span className={`text-xs font-medium text-${passwordStrength.color}`}>
                  Strength: {passwordStrength.label}
                </span>
              </div>
              <div className="w-full h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                <div 
                  className={`h-full bg-${passwordStrength.color} transition-all duration-300 ease-in-out`} 
                  style={{ width: `${passwordStrength.percent}%` }}
                ></div>
              </div>
              {passwordStrength.score >= 7 && (
                <p className="text-xs mt-1 text-green-700 dark:text-green-400">
                  Excellent! This password provides very strong security.
                </p>
              )}
            </div>
          )}

          {/* Confirm Password Input */}
          <motion.div
            className="mb-6"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2 }}
          >
            <label htmlFor="confirmPassword" className="block text-sm font-medium mb-2">Confirm Password</label>
            <input
              id="confirmPassword"
              type="password"
              className={`w-full p-4 border rounded-lg ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'} focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all duration-300 transform focus:scale-105`}
              placeholder="Confirm your password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
            />
          </motion.div>

          <motion.div className="mb-4">
            <label htmlFor="role" className="block text-sm font-medium mb-2">Role</label>
            <select
              id="role"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className={`w-full p-4 border rounded-lg ${
                darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-300 text-gray-900'
              }`}
              required
            >
              <option value="">Select Role</option>
              <option value="STUDENT">Student</option>
              <option value="TEACHER">Teacher</option>
              <option value="ADMIN">Admin</option>
            </select>
          </motion.div>

          {(role === 'TEACHER' || role === 'ADMIN') && (
            <div>
              <label className="block text-sm font-medium mb-2">Access Code</label>
              <input
                type="text"
                value={accessCode}
                onChange={(e) => setAccessCode(e.target.value)}
                className={`w-full p-3 rounded-lg border ${
                  darkMode 
                    ? 'bg-gray-700 border-gray-600 text-white' 
                    : 'bg-white border-gray-300'
                }`}
                placeholder={`Enter ${role.toLowerCase()} access code`}
                required
              />
            </div>
          )}

          {errorMessage && (
            <motion.p
              className="text-red-500 text-sm text-center mb-4"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4 }}
            >
              {errorMessage}
            </motion.p>
          )}

          {/* Regular sign up button */}
          <motion.button
            type="submit"
            className={`w-full p-4 text-white rounded-lg text-lg focus:outline-none ${darkMode ? 'bg-teal-700 hover:bg-teal-600' : 'bg-blue-600 hover:bg-blue-700'} transition-colors duration-300`}
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.95 }}
          >
            Sign Up
          </motion.button>
        </form>

        {/* Divider */}
        <div className="mt-6 mb-6 flex items-center">
          <div className="flex-1 border-t border-gray-300 dark:border-gray-600"></div>
          <span className="mx-4 text-sm text-gray-500 dark:text-gray-400">or continue with</span>
          <div className="flex-1 border-t border-gray-300 dark:border-gray-600"></div>
        </div>

        {/* Social signup buttons */}
        <div className="text-center">
          <GoogleLogin
            onSuccess={handleGoogleSignUpSuccess}
            onError={handleGoogleSignUpFailure}
            text="signup_with"
          />
          <button
            onClick={handleMicrosoftSignUp}
            className="mt-4 flex items-center gap-2 w-full p-2 text-gray-700 bg-white hover:bg-gray-50 border border-gray-300 rounded-sm transition-all duration-300"
            style={{ height: '40px' }}
          >
            <div className="flex-1 flex items-center">
              <FaMicrosoft className="text-[#00a4ef] text-xl ml-1" />
            </div>
            <div className="flex-[2] text-center pr-20 text-sm">
              <span>Sign up with Microsoft</span>
            </div>
          </button>
        </div>

        <div className="mt-6 text-center">
          <p className="text-sm">
            Already have an account?{" "}
            <Link
              to="/sign-in"
              className={`text-blue-500 hover:text-blue-700 transition duration-300 ${darkMode ? 'hover:text-blue-400' : 'hover:text-blue-600'}`}
            >
              Sign In
            </Link>
          </p>
        </div>
      </motion.div>
      {/* Dark Mode Toggle Button */}
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

      {/* Success Modal */}
      <AnimatePresence>
        {showSuccessModal && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50"
          >
            <motion.div
              initial={{ scale: 0.8, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.8, opacity: 0 }}
              className={`${
                darkMode ? 'bg-gray-800 text-white' : 'bg-white text-gray-900'
              } p-8 rounded-lg shadow-xl max-w-md w-full mx-4`}
            >
              <h2 className="text-2xl font-bold mb-4">Registration Successful!</h2>
              <p className="mb-6">
                {successData?.role === 'STUDENT'
                  ? "You've been successfully registered as a student. Click below to go to your class hub!"
                  : successData?.role === 'TEACHER'
                  ? "You've been successfully registered as a teacher. Click below to access your dashboard!"
                  : "You've been successfully registered as an admin. Click below to access your dashboard!"}
              </p>
              {successData?.role === 'STUDENT' ? (
                <Link 
                  to="/student-hub"
                  className={`block w-full p-4 text-center text-white rounded-lg ${
                    darkMode ? 'bg-teal-600 hover:bg-teal-500' : 'bg-blue-600 hover:bg-blue-700'
                  } transition-colors duration-300`}
                >
                  Go to Student Hub
                </Link>
              ) : successData?.role === 'TEACHER' ? (
                <Link 
                  to="/teacher-dashboard"
                  className={`block w-full p-4 text-center text-white rounded-lg ${
                    darkMode ? 'bg-teal-600 hover:bg-teal-500' : 'bg-blue-600 hover:bg-blue-700'
                  } transition-colors duration-300`}
                >
                  Go to Teacher Dashboard
                </Link>
              ) : (
                <Link 
                  to="/admin-dashboard"
                  className={`block w-full p-4 text-center text-white rounded-lg ${
                    darkMode ? 'bg-teal-600 hover:bg-teal-500' : 'bg-blue-600 hover:bg-blue-700'
                  } transition-colors duration-300`}
                >
                  Go to Admin Dashboard
                </Link>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default SignUp;
