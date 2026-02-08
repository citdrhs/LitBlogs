import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import './LitBlogs.css';

const PrivacyPolicy = () => {
  const [darkMode, setDarkMode] = useState(false);
  const navigate = useNavigate();
  const [userInfo, setUserInfo] = useState(null);

  // Toggle dark mode
  const toggleDarkMode = () => {
    setDarkMode((prevDarkMode) => {
      const newDarkMode = !prevDarkMode;
      localStorage.setItem('darkMode', JSON.stringify(newDarkMode));
      return newDarkMode;
    });
  };

  // Load dark mode preference from localStorage
  useEffect(() => {
    const storedDarkMode = JSON.parse(localStorage.getItem('darkMode'));
    if (storedDarkMode !== null) {
      setDarkMode(storedDarkMode);
    } else {
      const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      setDarkMode(systemPrefersDark);
    }
  }, []);

  // Apply the dark mode class to the document when darkMode state changes
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [darkMode]);

  useEffect(() => {
    const storedUserInfo = localStorage.getItem('user_info');
    if (storedUserInfo) {
      setUserInfo(JSON.parse(storedUserInfo));
    }
  }, []);

  const handleSignOut = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user_info');
    localStorage.removeItem('class_info');
    setUserInfo(null);
    navigate('/');
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

      {/* Toggle Dark Mode Button */}
      <motion.div
        className="absolute top-5 right-4 z-10 transition-transform transform hover:scale-110"
        whileHover={{ scale: 1.1 }}
      >
        <button
          onClick={toggleDarkMode}
          className="bg-gray-800 text-white p-2 rounded-full shadow-lg"
        >
          {darkMode ? "🌞" : "🌙"}
        </button>
      </motion.div>

      {/* Content */}
      <div className="container mx-auto px-4 py-16 md:px-8 max-w-4xl">
        <motion.h1
          className="text-4xl md:text-5xl font-bold mb-8 text-center bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          Privacy Policy
        </motion.h1>

        <motion.div
          className={`${darkMode ? 'bg-gray-800/70' : 'bg-white/90'} backdrop-blur-sm rounded-2xl shadow-xl p-6 md:p-8 mb-10`}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
        >
          <p className="text-sm text-gray-500 dark:text-gray-400 mb-6">Last Updated: May 9, 2025</p>
          
          <div className="space-y-8">
            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Introduction</h2>
              <p className="mb-3">Welcome to LitBlog. We are committed to protecting your personal information and your right to privacy. This Privacy Policy explains how we collect, use, disclose, and safeguard your information when you visit our website and use our services.</p>
              <p>Please read this privacy policy carefully. If you do not agree with the terms of this privacy policy, please do not access the site.</p>
            </section>
            
            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Information We Collect</h2>
              <h3 className="text-xl font-semibold mb-2">Personal Information</h3>
              <p className="mb-3">When you register an account, we may ask for information including your name, email address, and role (student, teacher, or administrator). For teachers and administrators, additional verification may be required through access codes.</p>
              
              <h3 className="text-xl font-semibold mb-2 mt-4">Usage Information</h3>
              <p>We collect information about how you interact with our website, including:</p>
              <ul className="list-disc pl-6 mt-2 mb-3 space-y-1">
                <li>Content you create, post, and interact with</li>
                <li>Features and pages you access</li>
                <li>Device information and IP addresses</li>
                <li>Browser type and settings</li>
              </ul>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>How We Use Your Information</h2>
              <p className="mb-2">We use the information we collect to:</p>
              <ul className="list-disc pl-6 mb-4 space-y-1">
                <li>Provide, maintain, and improve our services</li>
                <li>Create and manage your account</li>
                <li>Process transactions and send related information</li>
                <li>Send administrative information, updates, and security alerts</li>
                <li>Respond to your comments and questions</li>
                <li>Analyze usage patterns to enhance user experience</li>
                <li>Protect against unauthorized access and misuse of our platform</li>
              </ul>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Sharing Your Information</h2>
              <p className="mb-3">We may share your information in the following situations:</p>
              <ul className="list-disc pl-6 mb-4 space-y-1">
                <li><strong>With Service Providers:</strong> We may share your information with third-party vendors who perform services on our behalf.</li>
                <li><strong>For Educational Purposes:</strong> Teachers may have access to student content submitted through our platform for educational purposes.</li>
                <li><strong>With Your Consent:</strong> We may share your information for any other purpose disclosed to you with your consent.</li>
                <li><strong>Legal Compliance:</strong> We may disclose your information where required by law.</li>
              </ul>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Data Security</h2>
              <p className="mb-3">We implement appropriate security measures to protect your personal information. However, no method of transmission over the Internet or electronic storage is 100% secure, so we cannot guarantee absolute security.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>User Rights</h2>
              <p className="mb-3">You have the right to:</p>
              <ul className="list-disc pl-6 mb-4 space-y-1">
                <li>Access, correct, or delete your personal information</li>
                <li>Object to the processing of your personal data</li>
                <li>Request that we restrict processing of your personal information</li>
                <li>Request portability of your personal information</li>
                <li>Opt-out of marketing communications</li>
              </ul>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Cookies and Tracking Technologies</h2>
              <p className="mb-3">We use cookies and similar tracking technologies to collect and track information about your interactions with our website. You can set your browser to refuse all or some browser cookies, but this may affect site functionality.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Children's Privacy</h2>
              <p className="mb-3">Our services are designed for educational institutions and may be used by students of different ages. We are committed to complying with laws protecting children's privacy. Teachers and educational institutions should obtain appropriate parental consents when necessary.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Changes to This Privacy Policy</h2>
              <p className="mb-3">We may update this privacy policy from time to time. The updated version will be indicated by an updated "Last Updated" date and the updated version will be effective as soon as it is accessible.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>Contact Us</h2>
              <p className="mb-3">If you have questions or concerns about this Privacy Policy, please contact us at:</p>
              <p className="font-medium">litblogapi@gmail.com</p>
            </section>
          </div>
        </motion.div>
      </div>

      <Footer darkMode={darkMode} />
    </div>
  );
};

export default PrivacyPolicy;