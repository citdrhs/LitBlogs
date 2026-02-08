import React, { useState, useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Link } from 'react-router-dom';
import Button from './Sign-out';

const Navbar = ({ 
  userInfo, 
  onSignOut, 
  darkMode = false,
  logo = "/dren/logo.png",
  navLinks = [
    { to: "/", label: "Home" },
    { to: "/help", label: "Help" },

  ]
}) => {
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const dropdownRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
        setShowUserDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const getDashboardLink = () => {
    if (!userInfo) return null;
    
    const roleRoutes = {
      'STUDENT': { to: "/student-hub", label: "Student Hub" },
      'TEACHER': { to: "/teacher-dashboard", label: "Teacher Dashboard" },
      'ADMIN': { to: "/admin-dashboard", label: "Admin Dashboard" }
    };

    const route = roleRoutes[userInfo.role];
    if (!route) return null;

    return (
      <Link
        to={route.to}
        className={`text-gray-900 dark:text-white hover:${darkMode ? 'text-cyan-400' : 'text-blue-500'} transition-colors duration-300 text-sm md:text-base`}
      >
        {route.label}
      </Link>
    );
  };

  return (
    <nav className="flex justify-center z-50 fixed top-4 left-1/2 -translate-x-1/2 w-auto bg-white/80 dark:bg-gray-800/80 backdrop-blur-md py-2 px-6 rounded-xl shadow-lg border border-gray-200/50 dark:border-gray-700/50">
      <div className="flex items-center gap-5 whitespace-nowrap">
        {/* Logo */}
        <Link to="/">
          <motion.img
            src={logo}
            alt="Logo"
            className="h-8 mr-7 transition-transform duration-300 hover:scale-110 cursor-pointer"
            whileHover={{ scale: 1.1 }}
          />
        </Link>

        {/* Desktop Navigation */}
        <div className="hidden md:flex items-center gap-5 ml-0">
          {navLinks.map((link, index) => (
            <Link
              key={index}
              to={link.to}
              className={`text-gray-900 dark:text-white hover:${darkMode ? 'text-cyan-400' : 'text-blue-500'} transition-colors duration-300 text-sm md:text-base`}
            >
              {link.label}
            </Link>
          ))}
          {getDashboardLink()}
        </div>

        {/* Mobile Menu Button */}
        <div className="md:hidden relative" ref={dropdownRef}>
          <button
            onClick={() => setIsDropdownOpen(!isDropdownOpen)}
            className="text-gray-900 dark:text-white hover:text-blue-500 transition-colors duration-300 focus:outline-none"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              className={`h-6 w-6 transition-transform duration-300 ${isDropdownOpen ? "rotate-90" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>

          {/* Mobile Menu Dropdown */}
          <AnimatePresence>
            {isDropdownOpen && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="absolute right-0 mt-2 w-56 bg-white dark:bg-gray-800 rounded-md shadow-lg py-2"
              >
                {navLinks.map((link, index) => (
                  <Link
                    key={index}
                    to={link.to}
                    className="block px-4 py-2 text-gray-900 dark:text-white hover:bg-gray-100 dark:hover:bg-gray-700 truncate"
                  >
                    {link.label}
                  </Link>
                ))}
                {getDashboardLink()}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* User Menu */}
        {userInfo ? (
          <div className="relative" ref={dropdownRef}>
            <button
              onClick={() => setShowUserDropdown(!showUserDropdown)}
              className="w-10 h-10 rounded-full bg-blue-500 text-white flex items-center justify-center hover:bg-blue-600 transition-colors duration-300 overflow-hidden"
            >
              {userInfo.profile_image ? (
                <img src={userInfo.profile_image} alt="Profile" className="w-full h-full object-cover" />
              ) : (
                <span>
                  {userInfo.first_name?.[0]?.toUpperCase() || userInfo.firstName?.[0]?.toUpperCase() || userInfo.username?.[0]?.toUpperCase() || '?'}
                </span>
              )}
            </button>

            <AnimatePresence>
              {showUserDropdown && (
                <motion.div
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className="absolute right-0 mt-2 w-48 bg-white dark:bg-gray-800 rounded-lg shadow-xl py-2 border border-gray-200 dark:border-gray-700"
                >
                  <Link
                    to="/profile"
                    className="block px-4 py-2 text-gray-800 dark:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-700"
                  >
                    Profile
                  </Link>
                  <Button onSignOut={onSignOut} />
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        ) : (
          <Link to="/sign-in">
            <motion.svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 448 512"
              className={`h-6 w-6 p-1 border-2 rounded-full cursor-pointer transition-all duration-300 ${
                darkMode
                  ? 'fill-white border-white hover:bg-gray-700'
                  : 'fill-gray-900 border-gray-900 hover:bg-gray-200 dark:hover:bg-gray-700'
              }`}
              whileHover={{ scale: 1.1 }}
            >
              <path d="M224 256A128 128 0 1 0 224 0a128 128 0 1 0 0 256zM178.3 304C79.8 304 0 383.8 0 482.3 0 498.7 13.3 512 29.7 512h388.6c16.4 0 29.7-13.3 29.7-29.7 0-98.5-79.8-178.3-178.3-178.3z" />
            </motion.svg>
          </Link>
        )}
      </div>
    </nav>
  );
};

export default Navbar;