import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import Navbar from "./components/Navbar";
import Footer from "./components/Footer";
import FAQ from "./components/FAQ";
import TutorialVideoPlayer from "./components/TutorialVideoPlayer";
import { studentTutorialTranscript } from "./components/tutorialTranscript";
import { logoutBrowserSession } from "./utils/auth";
import { assetPath } from "./utils/urlUtils";
import "./LitBlogs.css";

const Help = () => {
  const [darkMode, setDarkMode] = useState(false);
  const [userInfo, setUserInfo] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    const storedDarkMode = JSON.parse(localStorage.getItem("darkMode"));
    if (storedDarkMode !== null) {
      setDarkMode(storedDarkMode);
    } else {
      setDarkMode(window.matchMedia("(prefers-color-scheme: dark)").matches);
    }
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", darkMode);
  }, [darkMode]);

  useEffect(() => {
    const storedUserInfo = sessionStorage.getItem("user_info");
    if (storedUserInfo) {
      setUserInfo(JSON.parse(storedUserInfo));
    }
  }, []);

  const handleSignOut = async () => {
    try {
      await logoutBrowserSession();
      setUserInfo(null);
      navigate("/");
    } catch {
      window.alert("Unable to sign out. Please try again.");
    }
  };

  return (
    <div className={`min-h-screen transition-all duration-500 ${darkMode ? "bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200" : "bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900"}`}>
      <Navbar
        userInfo={userInfo}
        onSignOut={handleSignOut}
        darkMode={darkMode}
        logo="/logo.png"
      />

      <section className="overflow-visible py-28 text-center">
        <motion.h2
          className="bg-gradient-text relative -top-2 mb-4 bg-clip-text pb-3 pt-2 text-5xl font-bold text-transparent md:text-9xl"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          How Can We Help You?
        </motion.h2>
        <motion.p
          className="mx-auto mb-2 max-w-2xl text-xl text-gray-600 dark:text-gray-400"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
        >
          Whether you&apos;re seeking writing tips, guidelines for submissions, or need assistance with the platform, we&apos;re here to support you!
        </motion.p>
      </section>

      <section className="bg-gray-100 py-24 dark:bg-gray-800">
        <div className="container mx-auto px-4">
          <motion.h3
            className="mb-8 text-center text-4xl font-bold text-gray-800 dark:text-white"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
          >
            Watch Our Tutorial
          </motion.h3>
          <div className="mx-auto w-full max-w-3xl">
            <TutorialVideoPlayer
              videoSrc={assetPath("tutorial/litblogs-tutorial.mp4")}
              posterSrc={assetPath("tutorial/litblogs-tutorial.jpg")}
              captionsSrc={assetPath("tutorial/litblogs-tutorial.en.vtt")}
              transcriptSrc={assetPath("tutorial/litblogs-tutorial.txt")}
              transcript={studentTutorialTranscript}
            />
          </div>
        </div>
      </section>

      <FAQ darkMode={darkMode} />
      <Footer darkMode={darkMode} />
    </div>
  );
};

export default Help;
