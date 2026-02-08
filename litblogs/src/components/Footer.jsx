import { Link } from "react-router-dom";

const Footer = ({ darkMode }) => {
  const isDark =
    typeof darkMode === "boolean"
      ? darkMode
      : typeof document !== "undefined" && document.documentElement.classList.contains("dark");

  return (
    <footer
      className={`mt-16 transition-all duration-300 ${
        isDark
          ? "bg-gray-950 text-gray-300 border-t border-gray-800"
          : "bg-white text-gray-700 border-t border-gray-200"
      }`}
    >
      <div className="container mx-auto px-6 py-12">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-10 text-center md:text-left">
          <div>
            <h3 className="text-lg font-semibold mb-4">LitBlog</h3>
            <p className={isDark ? "text-gray-400" : "text-gray-600"}>
              A modern platform for classroom publishing, feedback, and collaboration.
            </p>
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-4">Product</h3>
            <ul className={`space-y-2 ${isDark ? "text-gray-400" : "text-gray-600"}`}>
              <li>Class feeds</li>
              <li>Assignments</li>
              <li>Analytics</li>
            </ul>
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-4">Resources</h3>
            <ul className={`space-y-2 ${isDark ? "text-gray-400" : "text-gray-600"}`}>
              <li>
                <Link to="/help" className="hover:underline">
                  Help Center
                </Link>
              </li>
              <li>
                <Link to="/privacy-policy" className="hover:underline">
                  Privacy Policy
                </Link>
              </li>
              <li>
                <Link to="/terms" className="hover:underline">
                  Terms of Service
                </Link>
              </li>
            </ul>
          </div>
          <div>
            <h3 className="text-lg font-semibold mb-4">Contact</h3>
            <p className={isDark ? "text-gray-400" : "text-gray-600"}>
              litblogapi@gmail.com
            </p>
          </div>
        </div>
        <div className="mt-10 pt-6 border-t border-gray-200 dark:border-gray-800 text-center">
          <p className={`text-sm ${isDark ? "text-gray-500" : "text-gray-500"}`}>
            &copy; {new Date().getFullYear()} LitBlog. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
