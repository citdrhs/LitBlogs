import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import './LitBlogs.css';

const TermsOfService = () => {
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
          Terms of Service
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
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>1. Agreement to Terms</h2>
              <p className="mb-3">By accessing or using the LitBlog platform, website, and services, you agree to be bound by these Terms of Service. If you disagree with any part of these terms, you may not access the service.</p>
            </section>
            
            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>2. Description of Service</h2>
              <p className="mb-3">LitBlog provides an educational platform for students, teachers, and administrators to create, share, and interact with written content in a classroom environment. Features include but are not limited to blog creation, commenting, classroom management, and educational content sharing.</p>
              <p className="mb-3">We reserve the right to modify, suspend, or discontinue the service at any time, with or without notice.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>3. User Accounts</h2>
              <p className="mb-3">To use certain features of the Service, you must register for an account. You agree to:</p>
              <ul className="list-disc pl-6 mb-4 space-y-1">
                <li>Provide accurate and complete information when creating your account</li>
                <li>Maintain the security of your account and password</li>
                <li>Accept responsibility for all activities that occur under your account</li>
                <li>Notify us immediately of any unauthorized use of your account</li>
              </ul>
              <p className="mb-3">We reserve the right to terminate accounts, remove or edit content in our sole discretion.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>4. User Responsibilities</h2>
              <h3 className="text-xl font-semibold mb-2">4.1 Appropriate Content</h3>
              <p className="mb-3">You are solely responsible for any content you post, upload, or otherwise transmit through the service. Content must not be:</p>
              <ul className="list-disc pl-6 mb-4 space-y-1">
                <li>Unlawful, harmful, threatening, abusive, harassing, defamatory, or invasive of another's privacy</li>
                <li>Infringing upon intellectual property rights of others</li>
                <li>Containing software viruses or any other code designed to interfere with the service</li>
                <li>False, misleading, or deceptive</li>
                <li>Promoting discrimination, bigotry, racism, hatred, or physical harm</li>
              </ul>
              
              <h3 className="text-xl font-semibold mb-2 mt-4">4.2 Educational Use</h3>
              <p className="mb-3">Users agree to use the service primarily for educational purposes. Teachers and administrators agree to oversee student use appropriately.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>5. Intellectual Property</h2>
              <p className="mb-3">The Service and its original content (excluding content provided by users) are and will remain the exclusive property of LitBlog and its licensors.</p>
              <p className="mb-3">By submitting content to the service, you grant us a worldwide, non-exclusive, royalty-free license to use, reproduce, modify, adapt, publish, distribute, and display such content in connection with the service and our business operations.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>6. Privacy</h2>
              <p className="mb-3">Your use of the Service is also governed by our Privacy Policy, which is incorporated by reference into these Terms of Service. Please review our <Link to="/privacy-policy" className={`${darkMode ? 'text-blue-400 hover:text-blue-300' : 'text-blue-600 hover:text-blue-700'} hover:underline`}>Privacy Policy</Link>.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>7. Educational Institution Relationships</h2>
              <p className="mb-3">Educational institutions using LitBlog are responsible for:</p>
              <ul className="list-disc pl-6 mb-4 space-y-1">
                <li>Obtaining appropriate consent from parents/guardians for student use</li>
                <li>Ensuring compliance with applicable educational privacy laws</li>
                <li>Managing and overseeing student access and content appropriately</li>
              </ul>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>8. Limitation of Liability</h2>
              <p className="mb-3">To the maximum extent permitted by applicable law, in no event shall LitBlog be liable for any indirect, punitive, incidental, special, consequential damages, or any damages whatsoever including, without limitation, damages for loss of use, data, or profits arising out of or in any way connected with the use or performance of the service.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>9. Disclaimer</h2>
              <p className="mb-3">The service is provided on an "AS IS" and "AS AVAILABLE" basis. We make no warranties, expressed or implied, regarding the operation or availability of the service.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>10. Governing Law</h2>
              <p className="mb-3">These Terms shall be governed by and construed in accordance with the laws of the jurisdiction in which the company is registered, without regard to its conflict of law provisions.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>11. Changes to Terms</h2>
              <p className="mb-3">We reserve the right to modify these Terms at any time. We will notify users of any changes by posting the new Terms on this page and updating the "Last Updated" date.</p>
              <p className="mb-3">Your continued use of the Service after any changes constitutes your acceptance of the new Terms.</p>
            </section>

            <section>
              <h2 className={`text-2xl font-bold mb-4 ${darkMode ? 'text-blue-400' : 'text-blue-600'}`}>12. Contact Us</h2>
              <p className="mb-3">If you have any questions about these Terms, please contact us at:</p>
              <p className="font-medium">litblogapi@gmail.com</p>
            </section>
          </div>
        </motion.div>
      </div>

      <Footer darkMode={darkMode} />
    </div>
  );
};

export default TermsOfService;