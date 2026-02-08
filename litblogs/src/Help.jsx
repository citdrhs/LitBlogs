import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { motion, AnimatePresence } from "framer-motion";
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import './LitBlogs.css'; // Import your styles
import FAQ from './components/FAQ';
const Help = () => {
  const [darkMode, setDarkMode] = useState(false);
  const [email, setEmail] = useState("");
  const [isPlaying, setIsPlaying] = useState(false);
  const [volume, setVolume] = useState(1);
  const [progress, setProgress] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showSpeedOptions, setShowSpeedOptions] = useState(false);
  const [isMuted, setIsMuted] = useState(false);
  const [previousVolume, setPreviousVolume] = useState(1);
  
  const videoRef = useRef(null);
  const playerRef = useRef(null);
  const speedOptionsRef = useRef(null);

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

  // Format time in MM:SS
  const formatTime = (timeInSeconds) => {
    const minutes = Math.floor(timeInSeconds / 60);
    const seconds = Math.floor(timeInSeconds % 60);
    return `${minutes}:${seconds < 10 ? '0' : ''}${seconds}`;
  };

  // Add these new functions
  const togglePlay = () => {
    if (videoRef.current) {
      if (isPlaying) {
        videoRef.current.pause();
      } else {
        videoRef.current.play();
      }
      setIsPlaying(!isPlaying);
    }
  };

  const toggleMute = () => {
    if (videoRef.current) {
      if (isMuted) {
        videoRef.current.volume = previousVolume;
        setVolume(previousVolume);
      } else {
        setPreviousVolume(volume);
        videoRef.current.volume = 0;
        setVolume(0);
      }
      setIsMuted(!isMuted);
    }
  };

  const handleTimeUpdate = () => {
    if (videoRef.current) {
      const progress = (videoRef.current.currentTime / videoRef.current.duration) * 100;
      setProgress(progress);
      setCurrentTime(videoRef.current.currentTime);
    }
  };

  const handleLoadedMetadata = () => {
    if (videoRef.current) {
      setDuration(videoRef.current.duration);
    }
  };

  const handleProgressClick = (e) => {
    if (videoRef.current) {
      const progressBar = e.currentTarget;
      const clickPosition = (e.pageX - progressBar.offsetLeft) / progressBar.offsetWidth;
      videoRef.current.currentTime = clickPosition * videoRef.current.duration;
    }
  };

  const handleVolumeChange = (e) => {
    const newVolume = parseFloat(e.target.value);
    setVolume(newVolume);
    setIsMuted(newVolume === 0);
    if (videoRef.current) {
      videoRef.current.volume = newVolume;
    }
  };

  const handleSpeedChange = (speed) => {
    if (videoRef.current) {
      videoRef.current.playbackRate = speed;
      setPlaybackSpeed(speed);
      setShowSpeedOptions(false);
    }
  };

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) {
      playerRef.current.requestFullscreen();
      setIsFullscreen(true);
    } else {
      document.exitFullscreen();
      setIsFullscreen(false);
    }
  };

  // Add keyboard controls
  useEffect(() => {
    const handleKeyPress = (e) => {
      switch (e.key.toLowerCase()) {
        case ' ':
        case 'k':
          e.preventDefault();
          togglePlay();
          break;
        case 'm':
          toggleMute();
          break;
        case 'f':
          toggleFullscreen();
          break;
        case 'arrowleft':
          if (videoRef.current) videoRef.current.currentTime -= 5;
          break;
        case 'arrowright':
          if (videoRef.current) videoRef.current.currentTime += 5;
          break;
        case 'arrowup':
          setVolume(prev => Math.min(1, prev + 0.1));
          break;
        case 'arrowdown':
          setVolume(prev => Math.max(0, prev - 0.1));
          break;
        default:
          break;
      }
    };

    document.addEventListener('keydown', handleKeyPress);
    return () => document.removeEventListener('keydown', handleKeyPress);
  }, []);

  const navigate = useNavigate();
  const [userInfo, setUserInfo] = useState(null);
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
      <section className="py-24 text-center overflow-visible">
        <motion.h2
          className="relative -top-2 text-5xl md:text-7xl font-bold mb-4 bg-gradient-text bg-clip-text text-transparent pt-2 pb-3"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          How Can We Help You?
        </motion.h2>
        <motion.p
          className="text-gray-600 dark:text-gray-400 text-xl mb-8 max-w-2xl mx-auto"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
        >
          Whether you're seeking writing tips, guidelines for submissions, or need assistance with the platform, we're here to support you!
        </motion.p>
        <motion.button
          onClick={() => {
            document.getElementById('target-section').scrollIntoView({
              behavior: 'smooth',
            });
          }}
          className="bg-blue-600 text-white px-8 py-4 rounded-full text-lg flex items-center mx-auto shadow-lg"
          whileHover={{
            scale: 1.05,
            backgroundColor: "#2563eb",
            transition: { duration: 0.2 } // Fast transition for hover
          }}
          whileTap={{
            scale: 0.95,
            transition: { duration: 0.1 } // Fast transition for tap
          }}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            scale: { type: "spring", stiffness: 500, damping: 30 }, // Set transition for scaling
            opacity: { duration: 0.8, delay: 0.4 },
            y: { duration: 0.8, delay: 0.4 }
          }}
        >
          Contact Support
          <svg className="w-5 h-5 ml-2 animate-bounce-horizontal" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
          </svg>
        </motion.button>
      </section>

      {/* Custom Video Player */}
      <section className="py-24 bg-gray-100 dark:bg-gray-800">
        <div className="container mx-auto px-4">
          <motion.h3
            className="text-4xl text-gray-800 dark:text-white font-bold mb-8 text-center"
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
          >
            Watch Our Tutorial
          </motion.h3>
          
          <div className="w-full max-w-3xl mx-auto">
            <div 
              className="bg-gray-300 dark:bg-gray-700 rounded-lg overflow-hidden"
              ref={playerRef}
            >
              <div className="relative aspect-video">
                <video
                  ref={videoRef}
                  className="w-full h-full object-cover"
                  poster="path/to/your/video-thumbnail.jpg"
                  onTimeUpdate={handleTimeUpdate}
                  onLoadedMetadata={handleLoadedMetadata}
                  onClick={togglePlay}
                >
                  <source src="path/to/your/video.mp4" type="video/mp4" />
                  Your browser does not support the video tag.
                </video>

                {!isPlaying && (
                  <div className="absolute inset-0 flex items-center justify-center">
                    <button
                      onClick={togglePlay}
                      className="bg-black/50 rounded-full p-6 hover:bg-black/70 transition-colors"
                    >
                      <svg className="w-12 h-12 text-white" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M8 5v14l11-7z" />
                      </svg>
                    </button>
                  </div>
                )}

                <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent px-4 py-3">
                  <div className="group relative">
                    <div 
                      className="w-full h-1 bg-gray-600/50 rounded-full mb-4 cursor-pointer group-hover:h-2 transition-all"
                      onClick={handleProgressClick}
                    >
                      <div 
                        className="h-full bg-blue-500 rounded-full relative"
                        style={{ width: `${progress}%` }}
                      >
                        <div className="absolute right-0 top-1/2 -translate-y-1/2 w-3 h-3 bg-blue-500 rounded-full scale-0 group-hover:scale-100 transition-transform" />
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between gap-4">
                    <div className="flex items-center gap-3">
                      <button
                        onClick={togglePlay}
                        className="text-white hover:text-blue-400 transition-colors"
                        title={isPlaying ? "Pause (k)" : "Play (k)"}
                      >
                        {isPlaying ? (
                          <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                          </svg>
                        ) : (
                          <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M8 5v14l11-7z" />
                          </svg>
                        )}
                      </button>

                      <div className="flex items-center group relative">
                        <button
                          onClick={toggleMute}
                          className="text-white hover:text-blue-400 transition-colors"
                          title="Toggle Mute (m)"
                        >
                          {volume === 0 ? (
                            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                              <path d="M3.63 3.63a.996.996 0 000 1.41L7.29 8.7 7 9H3v6h4l5 5v-6.59l4.18 4.18c-.65.49-1.38.88-2.18 1.11v2.06a8.986 8.986 0 003.76-1.78l1.49 1.49a.996.996 0 101.41-1.41L5.05 3.63a.996.996 0 00-1.42 0zM19 12c0 .82-.15 1.61-.41 2.34l1.53 1.53c.56-1.17.88-2.48.88-3.87 0-4.28-3-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zm-7-8l-1.88 1.88L12 7.76zm4.5 8c0-1.77-1.02-3.29-2.5-4.03v1.79l2.48 2.48c.01-.08.02-.16.02-.24z"/>
                            </svg>
                          ) : (
                            <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4-.91 7-4.49 7-8.77 0-4.28-3-7.86-7-8.77z"/>
                            </svg>
                          )}
                        </button>
                        <div className="overflow-hidden w-0 group-hover:w-24 transition-all duration-300">
                          <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.01"
                            value={volume}
                            onChange={handleVolumeChange}
                            className="ml-2 accent-blue-500"
                            title="Volume"
                          />
                        </div>
                      </div>

                      <div className="text-white text-sm">
                        <span>{formatTime(currentTime)}</span>
                        <span className="mx-1">/</span>
                        <span>{formatTime(duration)}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <div className="relative">
                        <button
                          onClick={() => setShowSpeedOptions(!showSpeedOptions)}
                          className="text-white hover:text-blue-400 transition-colors text-sm"
                          title="Playback Speed"
                        >
                          {playbackSpeed}x
                        </button>
                        {showSpeedOptions && (
                          <div className="absolute bottom-full mb-2 right-0 bg-black/90 rounded-md py-1 min-w-[100px]">
                            {[0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2].map((speed) => (
                              <button
                                key={speed}
                                onClick={() => handleSpeedChange(speed)}
                                className={`block w-full px-4 py-1 text-sm text-left hover:bg-white/10 ${
                                  playbackSpeed === speed ? 'text-blue-400' : 'text-white'
                                }`}
                              >
                                {speed}x
                              </button>
                            ))}
                          </div>
                        )}
                      </div>

                      <button
                        onClick={toggleFullscreen}
                        className="text-white hover:text-blue-400 transition-colors"
                        title="Toggle Fullscreen (f)"
                      >
                        {isFullscreen ? (
                          <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/>
                          </svg>
                        ) : (
                          <svg className="w-6 h-6" fill="currentColor" viewBox="0 0 24 24">
                            <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>
                          </svg>
                        )}
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>
      {/* FAQ */}
      <FAQ darkMode={darkMode} />
      {/* Contact Us */}
      <div className="mt-10 max-w-4xl mx-auto text-center px-4 sm:px-6" id="target-section">
        <h2 className="text-3xl font-bold mb-6 text-gray-800 dark:text-white">
          Contact us and we will be happy to help!
        </h2>

        <form className="space-y-6">
          <div>
            <input
              type="email"
              placeholder="Enter your email"
              onChange={(e) => setEmail(e.target.value)}
              className={`w-full px-6 py-3 rounded-full ${darkMode ? 'bg-gray-700 border-gray-600 text-white' : 'bg-white border-gray-200 text-gray-800'} border focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder-gray-400`}
              required
            />
          </div>

          <div>
            <button
              type="submit"
              className="w-full py-3 rounded-full bg-blue-600 text-white font-semibold text-lg hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 transition duration-200"
            >
              Submit
            </button>
          </div>
        </form>
      </div>
      <Footer darkMode={darkMode} />
    </div>
  );
};

export default Help;