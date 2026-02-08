import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import Navbar from './components/Navbar';
import Footer from './components/Footer';
import './LitBlogs.css'; // Import your styles

const LitBlogs = () => {
  const navigate = useNavigate();
  const [userInfo, setUserInfo] = useState(null);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [darkMode, setDarkMode] = useState(false);
  const [email, setEmail] = useState("");
  const [newsletterMessage, setNewsletterMessage] = useState("");
  const slides = [
    "/dren/Classroom1.jpeg",
    "/dren/Classroom2.jpeg",
    "/dren/Classroom3.jpeg",
    "/dren/Classroom4.jpeg",
  ];

  // Handle next and previous slides
  const nextSlide = () => {
    setCurrentSlide((prev) => (prev < slides.length - 1 ? prev + 1 : 0));
  };

  const prevSlide = () => {
    setCurrentSlide((prev) => (prev > 0 ? prev - 1 : slides.length - 1));
  };

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

  // Handle newsletter submission
  const handleNewsletterSubmit = (e) => {
    e.preventDefault();
    if (email && email.includes("@")) {
      setNewsletterMessage("Thank you for subscribing!");
      setEmail("");
    } else {
      setNewsletterMessage("Please enter a valid email address.");
    }
  };

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
      logo="/dren/logo.png"
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
      <section className="py-28 text-center overflow-visible">
        <motion
          className="relative -top-2 text-5xl md:text-7xl font-bold mb-4 bg-gradient-text bg-clip-text text-transparent pt-2 pb-3"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          Lit Up Your Thoughts
        </motion>
        <motion.p
          className="text-gray-600 dark:text-gray-400 text-xl mb-8 max-w-2xl mx-auto mt-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, delay: 0.2 }}
        >
          Collaborate with creative minds. Publish your stories, engage with readers, and join a thriving community of writers.
        </motion.p>
        <Link to="/sign-in" className="inline-block">
          <motion.button
            className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-4 rounded-full text-xl font-medium flex items-center justify-center shadow-xl"
            whileHover={{
              scale: 1.05,
              transition: { duration: 0.1 } // Fast transition for hover
            }}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              scale: { type: "spring", stiffness: 500, damping: 50 }, // Set transition for scaling
              opacity: { duration: 0.8, delay: 0.4 },
              y: { duration: 0.8, delay: 0.4 }
            }}
            whileTap={{
              scale: 0.95,
              transition: { duration: 0.1 }
            }}
          >
            Start Writing Now
            <svg className="w-5 h-5 ml-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 8l4 4m0 0l-4 4m4-4H3" />
            </svg>
          </motion.button>
        </Link>
      </section>

      {/* Slider */}
      <div className="flex items-center justify-center">
        <motion.div
          className="slider-container relative w-[80%] md:w-[90%] max-w-[1200px] h-[600px] overflow-hidden rounded-lg shadow-lg border border-gray-200 dark:border-gray-700 transition-all mx-auto"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8 }}
        >
          <div className="slider">
            {slides.map((src, index) => (
              <motion.div
                key={index}
                className={`slide absolute w-full h-full bg-cover bg-center transition-all duration-1000 ease-in-out ${currentSlide === index ? 'opacity-100' : 'opacity-0'}`}
                style={{ backgroundImage: `url(${src})` }}
                initial={{ opacity: 0 }}
                animate={{ opacity: currentSlide === index ? 1 : 0 }}
                transition={{ duration: 0.8 }}
              ></motion.div>
            ))}
          </div>

          {/* Left and Right Navigation Buttons */}
          <button
            onClick={prevSlide}
            className="absolute left-4 top-1/2 transform -translate-y-1/2 bg-gray-700/80 p-2 text-white rounded-full hover:bg-gray-600 transition-all"
          >
            &#10094;
          </button>
          <button
            onClick={nextSlide}
            className="absolute right-4 top-1/2 transform -translate-y-1/2 bg-gray-700/80 p-2 text-white rounded-full hover:bg-gray-600 transition-all"
          >
            &#10095;
          </button>

          {/* Slide Indicators */}
          <div className="absolute bottom-4 left-1/2 transform -translate-x-1/2 flex gap-2">
            {slides.map((_, index) => (
              <div
                key={index}
                className={`indicator w-3 h-3 rounded-full cursor-pointer transition-all duration-300 ease-in-out ${currentSlide === index ? 'scale-110 opacity-100' : 'scale-75 opacity-50'} bg-white`}
                onClick={() => setCurrentSlide(index)}
              ></div>
            ))}
          </div>
        </motion.div>
      </div>

      {/* Feature Highlights */}
      <motion.section
        className="mt-20 px-6"
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        viewport={{ once: true }}
      >
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-12">
            <h2 className="text-4xl font-bold">Everything students and teachers need</h2>
            <p className="text-gray-600 dark:text-gray-400 mt-3 max-w-3xl mx-auto">
              Streamline publishing, feedback, and classroom collaboration with tools designed for schools.
            </p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              {
                title: "Assignments & submissions",
                text: "Create prompts, set due dates, and review student work in one place.",
              },
              {
                title: "Class feeds & discussions",
                text: "Keep conversations organized with threaded comments and class visibility.",
              },
              {
                title: "Analytics that matter",
                text: "Track engagement and activity to support every learner.",
              },
            ].map((feature) => (
              <div
                key={feature.title}
                className={`rounded-2xl p-6 shadow-lg border ${darkMode ? "bg-gray-900/60 border-gray-700" : "bg-white border-gray-200"}`}
              >
                <div className="flex items-center gap-3 mb-3">
                  <span className="text-2xl">✨</span>
                  <h3 className="text-xl font-semibold">{feature.title}</h3>
                </div>
                <p className="text-gray-600 dark:text-gray-400">{feature.text}</p>
              </div>
            ))}
          </div>
        </div>
      </motion.section>

      {/* Stats */}
      <motion.section
        className="mt-16 px-6"
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        viewport={{ once: true }}
      >
        <div className={`max-w-6xl mx-auto rounded-3xl p-10 ${darkMode ? "bg-gray-900/60" : "bg-white/80"} shadow-xl border ${darkMode ? "border-gray-700" : "border-gray-200"}`}>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 text-center">
            <div>
              <p className="text-4xl font-bold">100+</p>
              <p className="text-gray-600 dark:text-gray-400 mt-2">Active classes</p>
            </div>
            <div>
              <p className="text-4xl font-bold">4.8/5</p>
              <p className="text-gray-600 dark:text-gray-400 mt-2">Teacher satisfaction</p>
            </div>
            <div>
              <p className="text-4xl font-bold">10k+</p>
              <p className="text-gray-600 dark:text-gray-400 mt-2">Student posts</p>
            </div>
          </div>
        </div>
      </motion.section>

      {/* Testimonials */}
      <motion.section
        className="mt-16 px-6"
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        viewport={{ once: true }}
      >
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-10">
            <h2 className="text-4xl font-bold">Loved by classrooms</h2>
            <p className="text-gray-600 dark:text-gray-400 mt-3">Teachers and students share stories together.</p>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              {
                quote: "My students actually look forward to publishing. Feedback is quick and meaningful.",
                name: "English Teacher",
              },
              {
                quote: "I can track engagement without chasing spreadsheets. It saves me hours each week.",
                name: "ELA Department Lead",
              },
              {
                quote: "Assignments and posts are all in one place, so I know exactly what to work on.",
                name: "Student Writer",
              },
            ].map((testimonial) => (
              <div
                key={testimonial.quote}
                className={`rounded-2xl p-6 shadow-lg border ${darkMode ? "bg-gray-900/60 border-gray-700" : "bg-white border-gray-200"}`}
              >
                <p className="text-gray-700 dark:text-gray-300">“{testimonial.quote}”</p>
                <p className="mt-4 text-sm font-semibold text-blue-500">{testimonial.name}</p>
              </div>
            ))}
          </div>
        </div>
      </motion.section>

      {/* Call to Action */}
      <motion.section
        className="mt-16 px-6"
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6 }}
        viewport={{ once: true }}
      >
        <div className={`max-w-5xl mx-auto rounded-3xl p-10 text-center bottom-5 shadow-xl border ${darkMode ? "bg-gradient-to-r from-gray-900/70 to-slate-900/70 border-gray-700" : "bg-gradient-to-r from-white to-indigo-50 border-gray-200"}`}>
          <h2 className="text-4xl font-bold mb-4">Ready to launch your class community?</h2>
          <p className="text-gray-600 dark:text-gray-400 mb-8">
            Create a class, assign a prompt, and watch students publish with confidence.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center">
            <Link to="/sign-up">
              <button className="bg-blue-600 hover:bg-blue-700 text-white px-8 py-3 rounded-full font-semibold shadow-lg">
                Create an account
              </button>
            </Link>
            <Link to="/sign-in">
              <button className={`px-8 py-3 rounded-full font-semibold border ${darkMode ? "border-gray-600 text-gray-200 hover:bg-gray-800" : "border-gray-300 text-gray-700 hover:bg-gray-100"}`}>
                Sign in
              </button>
            </Link>
          </div>
        </div>
      </motion.section>

      <Footer darkMode={darkMode} />
    </div>
  );
};

export default LitBlogs;
