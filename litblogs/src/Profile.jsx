"use client"

import { useState, useEffect } from "react"
import { Link, useNavigate, useParams } from "react-router-dom"
import { motion } from "framer-motion"
import axios from "axios"
import Navbar from "./components/Navbar"
import Loader from "./components/Loader"
import Footer from "./components/Footer"

// Animated avatar options
const AVATAR_OPTIONS = [
  {
    id: "robot",
    name: "Robot",
    animation: "bounce",
    emoji: "🤖",
    bgColor: "bg-blue-500",
  },
  {
    id: "alien",
    name: "Alien",
    animation: "pulse",
    emoji: "👽",
    bgColor: "bg-green-500",
  },
  {
    id: "ghost",
    name: "Ghost",
    animation: "wiggle",
    emoji: "👻",
    bgColor: "bg-purple-500",
  },
  {
    id: "ninja",
    name: "Ninja",
    animation: "spin",
    emoji: "🥷",
    bgColor: "bg-red-500",
  },
  {
    id: "astronaut",
    name: "Astronaut",
    animation: "float",
    emoji: "👨‍🚀",
    bgColor: "bg-indigo-500",
  },
  {
    id: "wizard",
    name: "Wizard",
    animation: "sparkle",
    emoji: "🧙",
    bgColor: "bg-amber-500",
  },
]

// Background options
const BACKGROUND_OPTIONS = [
  "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?ixlib=rb-4.0.3&auto=format&fit=crop&w=1200&q=80",
  "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?ixlib=rb-4.0.3&auto=format&fit=crop&w=1200&q=80",
  "https://images.unsplash.com/photo-1506744038136-46273834b3fb?ixlib=rb-4.0.3&auto=format&fit=crop&w=1200&q=80",
  "https://images.unsplash.com/photo-1470770841072-f978cf4d019e?ixlib=rb-4.0.3&auto=format&fit=crop&w=1200&q=80",
]

// Custom animation styles
const customAnimationStyles = `
  @keyframes wiggle {
    0%, 100% { transform: rotate(-3deg); }
    50% { transform: rotate(3deg); }
  }

  @keyframes float {
    0%, 100% { transform: translateY(0); }
    50% { transform: translateY(-10px); }
  }

  @keyframes sparkle {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.6; transform: scale(1.2); }
  }

  .animate-wiggle {
    animation: wiggle 1s ease-in-out infinite;
  }

  .animate-float {
    animation: float 3s ease-in-out infinite;
  }

  .animate-sparkle {
    animation: sparkle 2s ease-in-out infinite;
  }
`

const StudentProfile = () => {
  const [name, setName] = useState("")
  const [firstName, setFirstName] = useState("")
  const [lastName, setLastName] = useState("")
  const [bio, setBio] = useState("")
  const [image, setImage] = useState(null)
  const [coverImage, setCoverImage] = useState(null)
  const [isEditing, setIsEditing] = useState(false)
  const [userPosts, setUserPosts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [activeTab, setActiveTab] = useState("posts")
  const [showProfileOptions, setShowProfileOptions] = useState(false)
  const [showCoverOptions, setShowCoverOptions] = useState(false)
  const [selectedAvatar, setSelectedAvatar] = useState(AVATAR_OPTIONS[0])
  const [avatarColor, setAvatarColor] = useState("bg-blue-500")

  const navigate = useNavigate()
  const { userId } = useParams()
  const [userInfo, setUserInfo] = useState(null)
  const [viewerInfo, setViewerInfo] = useState(null)
  const [isOwnProfile, setIsOwnProfile] = useState(true)
  const [viewerClassIds, setViewerClassIds] = useState([])
  const [darkMode, setDarkMode] = useState(false)

  const getUserId = (user) => user?.id || user?.username || user?.email

  const getClassIds = (classInfo) => {
    if (Array.isArray(classInfo)) {
      return classInfo.map((entry) => entry?.class_id || entry?.id || entry).filter(Boolean)
    }

    if (classInfo && typeof classInfo === "object") {
      const possibleId = classInfo.class_id || classInfo.id
      return possibleId ? [possibleId] : []
    }

    return []
  }

  const normalizeRole = (role) => (role || "STUDENT").toString().toUpperCase()

  const getRoleTabs = (role, isOwn) => {
    if (!isOwn) {
      return [{ key: "posts", label: "Shared Posts" }]
    }

    switch (normalizeRole(role)) {
      case "TEACHER":
        return [
          { key: "classes", label: "Classes" },
          { key: "students", label: "Students" },
        ]
      case "ADMIN":
        return [
          { key: "users", label: "Users" },
          { key: "reports", label: "Reports" },
        ]
      default:
        return [
          { key: "posts", label: "Posts" },
          { key: "saved", label: "Saved" },
        ]
    }
  }

  // Toggle dark mode
  const toggleDarkMode = () => {
    setDarkMode((prevDarkMode) => {
      const newDarkMode = !prevDarkMode
      localStorage.setItem("darkMode", JSON.stringify(newDarkMode))
      return newDarkMode
    })
  }

  // Load dark mode preference from localStorage
  useEffect(() => {
    const storedDarkMode = JSON.parse(localStorage.getItem("darkMode"))
    if (storedDarkMode !== null) {
      setDarkMode(storedDarkMode)
    } else {
      const systemPrefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches
      setDarkMode(systemPrefersDark)
    }
  }, [])

  // Apply the dark mode class to the document when darkMode changes
  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark")
    } else {
      document.documentElement.classList.remove("dark")
    }
  }, [darkMode])

  useEffect(() => {
    if (!isOwnProfile) {
      setIsEditing(false)
      setActiveTab("posts")
    }
  }, [isOwnProfile])

  useEffect(() => {
    const tabs = getRoleTabs(userInfo?.role, isOwnProfile)
    if (tabs.length && !tabs.some((tab) => tab.key === activeTab)) {
      setActiveTab(tabs[0].key)
    }
  }, [userInfo?.role, isOwnProfile])

  // Add custom animation styles to document head
  useEffect(() => {
    const styleElement = document.createElement("style")
    styleElement.innerHTML = customAnimationStyles
    document.head.appendChild(styleElement)

    return () => {
      document.head.removeChild(styleElement)
    }
  }, [])

  const applyProfileData = (profileData) => {
    setUserInfo(profileData)
    const fullName = `${profileData?.first_name || ""} ${profileData?.last_name || ""}`.trim()
    const fallbackName = profileData?.name || profileData?.full_name || profileData?.display_name
    setName(fullName || fallbackName || profileData?.username || profileData?.email || "")
    setFirstName(profileData?.first_name || "")
    setLastName(profileData?.last_name || "")
    setBio(profileData?.bio || "")
    setImage(profileData?.profile_image || null)
    setCoverImage(profileData?.cover_image || null)

    if (profileData?.avatar_id) {
      const avatar = AVATAR_OPTIONS.find((a) => a.id === profileData.avatar_id) || AVATAR_OPTIONS[0]
      setSelectedAvatar(avatar)
    }
    if (profileData?.avatar_color) {
      setAvatarColor(profileData.avatar_color)
    }
  }

  const loadProfileData = async ({ isOwn, targetUserId }) => {
    setLoading(true)

    if (isOwn) {
      try {
        const token = localStorage.getItem("token")
        if (!token) {
          navigate("/sign-in")
          return
        }

        const response = await axios.get("/api/user/profile", {
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
          },
        })

        const profileData = response.data
        applyProfileData(profileData)
        setLoading(false)
        return profileData
      } catch (error) {
        console.error("Error fetching profile:", error)
        setError("Failed to load profile data")
        setLoading(false)
        return null
      }
    }

    try {
      const token = localStorage.getItem("token")
      const response = await axios.get(`/api/user/profile/${targetUserId}`, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      })

      const profileData = response.data
      applyProfileData(profileData)
      setLoading(false)
      return profileData
    } catch (error) {
      console.error("Error fetching profile:", error)
      setError("Failed to load profile data")
      setLoading(false)
      return null
    }
  }

  const fetchViewerContext = async () => {
    const token = localStorage.getItem("token")
    if (!token) {
      navigate("/sign-in")
      return { viewer: null, classIds: [] }
    }

    const profileResponse = await axios.get("/api/user/profile", {
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
    })

    const viewerProfile = profileResponse.data
    setViewerInfo(viewerProfile)

    try {
      const classesResponse = await axios.get("/api/student/classes", {
        headers: { Authorization: `Bearer ${token}` },
      })
      const classIds = getClassIds(classesResponse.data)
      setViewerClassIds(classIds)
      return { viewer: viewerProfile, classIds }
    } catch (error) {
      try {
        const classesResponse = await axios.get("/api/classes", {
          headers: { Authorization: `Bearer ${token}` },
        })
        const classIds = getClassIds(classesResponse.data)
        setViewerClassIds(classIds)
        return { viewer: viewerProfile, classIds }
      } catch (innerError) {
        setViewerClassIds([])
        return { viewer: viewerProfile, classIds: [] }
      }
    }
  }

  // Load viewer info and profile data
  useEffect(() => {
    const initProfile = async () => {
      const { viewer } = await fetchViewerContext()
      const viewerId = getUserId(viewer)
      const targetUserId = userId || viewerId
      const isOwn = !userId || (viewerId && userId === viewerId)
      setIsOwnProfile(isOwn)

      if (!targetUserId) {
        navigate("/sign-in")
        return
      }

      const profileData = await loadProfileData({ isOwn, targetUserId })
      const profileRole = normalizeRole(profileData?.role)
      if (profileRole === "STUDENT") {
        await fetchUserPosts({ isOwn, targetUserId })
      } else {
        setUserPosts([])
      }
    }

    initProfile()
  }, [navigate, userId])

  // Fetch user's posts
  const fetchUserPosts = async ({ isOwn, targetUserId }) => {
    try {
      const token = localStorage.getItem("token")
      if (!token) {
        navigate("/sign-in")
        return
      }

      const endpoint = isOwn ? "/api/user/posts" : `/api/user/${targetUserId}/posts`
      const response = await axios.get(endpoint, {
        headers: { Authorization: `Bearer ${token}` },
      })

      setUserPosts(response.data)
    } catch (error) {
      console.error("Error fetching user posts:", error)
      setError("Failed to load posts")
    }
  }

  // Handle profile updates
  const handleProfileUpdate = async () => {
    if (!isOwnProfile) {
      return
    }
    if (!isEditing) {
      setIsEditing(true)
      return
    }

    try {
      setSaving(true)
      const token = localStorage.getItem("token")

      // Update profile information
      const response = await axios.post(
        "/api/user/update-profile",
        {
          first_name: firstName,
          last_name: lastName,
          bio: bio,
          avatar_id: selectedAvatar.id,
          avatar_color: avatarColor,
        },
        {
          headers: { Authorization: `Bearer ${token}` },
        },
      )

      if (response?.data?.profile) {
        applyProfileData(response.data.profile)
        setViewerInfo(response.data.profile)
      } else {
        // Update the displayed name
        setName(`${firstName} ${lastName}`)
        setUserInfo((prev) => ({
          ...prev,
          first_name: firstName,
          last_name: lastName,
          bio: bio,
          avatar_id: selectedAvatar.id,
          avatar_color: avatarColor,
        }))
      }

      setIsEditing(false)
      setSaving(false)

    } catch (error) {
      console.error("Error updating profile:", error)
      setSaving(false)
      setError("Failed to update profile")
    }
  }

  // Handle image upload
  const handleImageUpload = async (event) => {
    const file = event.target.files[0]
    if (!file) return

    try {
      const formData = new FormData()
      formData.append("file", file)

      const token = localStorage.getItem("token")
      setUploadProgress(0)

      const response = await axios.post("/api/user/upload-profile-image", formData, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "multipart/form-data",
        },
        onUploadProgress: (progressEvent) => {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          setUploadProgress(progress)
        },
      })

      setImage(response.data.image_url)
      setUploadProgress(0)

      // Update userInfo state
      setUserInfo((prev) => ({
        ...prev,
        profile_image: response.data.image_url,
      }))
    } catch (error) {
      console.error("Error uploading image:", error)
      setUploadProgress(0)
      setError("Failed to upload image")
    }
  }

  // Handle cover image upload
  const handleCoverImageUpload = async (event) => {
    const file = event.target.files[0]
    if (!file) return

    try {
      const formData = new FormData()
      formData.append("file", file)

      const token = localStorage.getItem("token")
      setUploadProgress(0)

      const response = await axios.post("/api/user/upload-cover-image", formData, {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "multipart/form-data",
        },
        onUploadProgress: (progressEvent) => {
          const progress = Math.round((progressEvent.loaded * 100) / progressEvent.total)
          setUploadProgress(progress)
        },
      })

      setCoverImage(response.data.image_url)
      setUploadProgress(0)

      // Update userInfo state
      setUserInfo((prev) => ({
        ...prev,
        cover_image: response.data.image_url,
      }))
    } catch (error) {
      console.error("Error uploading cover image:", error)
      setUploadProgress(0)
      setError("Failed to upload cover image")
    }
  }

  const selectProfileImage = (imageUrl) => {
    setImage(imageUrl)
    setShowProfileOptions(false)

    setUserInfo((prev) => ({
      ...prev,
      profile_image: imageUrl,
    }))
  }

  const selectCoverImage = (imageUrl) => {
    setCoverImage(imageUrl)
    setShowCoverOptions(false)

    setUserInfo((prev) => ({
      ...prev,
      cover_image: imageUrl,
    }))
  }

  const selectAvatar = (avatar) => {
    setSelectedAvatar(avatar)
    setShowProfileOptions(false)

    setUserInfo((prev) => ({
      ...prev,
      avatar_id: avatar.id,
    }))
  }

  const selectAvatarColor = (color) => {
    setAvatarColor(color)

    setUserInfo((prev) => ({
      ...prev,
      avatar_color: color,
    }))
  }

  const handleSignOut = () => {
    localStorage.removeItem("token")
    localStorage.removeItem("user_info")
    localStorage.removeItem("class_info")
    setUserInfo(null)
    setViewerInfo(null)
    navigate("/")
  }

  if (loading) {
    return (
      <div
        className={`min-h-screen transition-all duration-500 ${darkMode ? "bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200" : "bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900"}`}
      >
        <Navbar userInfo={viewerInfo || userInfo} onSignOut={handleSignOut} darkMode={darkMode} logo="./logo.png" />
        <div className="flex justify-center items-center h-screen">
          <Loader />
        </div>
      </div>
    )
  }

  // Animation keyframes for avatar animations
  const getAvatarAnimation = () => {
    switch (selectedAvatar.animation) {
      case "bounce":
        return "animate-bounce"
      case "pulse":
        return "animate-pulse"
      case "spin":
        return "animate-spin"
      case "wiggle":
        return "animate-wiggle"
      case "float":
        return "animate-float"
      case "sparkle":
        return "animate-sparkle"
      default:
        return ""
    }
  }

  const profileRole = normalizeRole(userInfo?.role)
  const isStudentProfile = profileRole === "STUDENT"
  const isTeacherProfile = profileRole === "TEACHER"
  const isAdminProfile = profileRole === "ADMIN"

  const profileClassIds = getClassIds(userInfo?.class_ids || userInfo?.classes || null)
  const sharedClassIds = profileClassIds.filter((classId) => viewerClassIds.includes(classId))
  const visiblePosts = isStudentProfile
    ? isOwnProfile
      ? userPosts
      : userPosts.filter((post) => viewerClassIds.includes(post.class_id))
    : []
  const hiddenPostsCount = isStudentProfile
    ? Math.max(userPosts.length - visiblePosts.length, 0)
    : 0

  return (
    <div
      className={`min-h-screen transition-all duration-500 ${darkMode ? "bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200" : "bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900"}`}
    >
      {/* Navbar */}
      <Navbar userInfo={viewerInfo || userInfo} onSignOut={handleSignOut} darkMode={darkMode} logo="./logo.png" />

      {/* Toggle Dark Mode Button */}
      <motion.div
        className="fixed top-5 right-4 z-10 transition-transform transform hover:scale-110"
        whileHover={{ scale: 1.1 }}
      >
        <button
          onClick={toggleDarkMode}
          className={`${darkMode ? "bg-gray-700 hover:bg-gray-600" : "bg-white hover:bg-gray-100"} ${darkMode ? "text-white" : "text-gray-800"} p-3 rounded-full shadow-lg transition-all duration-200 transform hover:-translate-y-1`}
        >
          {darkMode ? "🌞" : "🌙"}
        </button>
      </motion.div>

      {/* Error/Success message if any */}
      {error && (
        <div
          className={`fixed top-20 left-1/2 transform -translate-x-1/2 z-50 ${
            error.includes("Successfully") ? "bg-green-500" : "bg-red-500"
          } text-white px-6 py-3 rounded-lg shadow-lg flex items-center`}
        >
          {error}
          <button 
            className="ml-3 text-white hover:bg-opacity-20 bg-white bg-opacity-10 rounded-full p-1"
            onClick={() => setError(null)}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              width="16"
              height="16"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
      )}

      <main className="container mx-auto px-4 py-32">
        {/* Profile Header Card */}
        <motion.div
          className={`rounded-2xl shadow-2xl overflow-hidden mb-10 ${darkMode ? "bg-gray-800" : "bg-white"}`}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
        >
          {/* Cover Image */}
          <div className="h-64 w-full relative overflow-hidden">
            <img
              src={
                coverImage ||
                BACKGROUND_OPTIONS[0] ||
                "/placeholder.svg"
              }
              alt="Cover"
              className="w-full h-full object-cover transition-transform duration-700 hover:scale-105"
            />
            {isEditing && isOwnProfile && (
              <div className="absolute bottom-4 right-4 flex gap-2">
                <button
                  onClick={() => setShowCoverOptions(!showCoverOptions)}
                  className="rounded-full bg-black/30 hover:bg-black/50 p-3 text-white transition-all duration-200 transform hover:scale-110"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                    <circle cx="8.5" cy="8.5" r="1.5"></circle>
                    <polyline points="21 15 16 10 5 21"></polyline>
                    </svg>
                </button>
                <label
                  htmlFor="coverImageUpload"
                  className="cursor-pointer rounded-full bg-black/30 hover:bg-black/50 p-3 text-white transition-all duration-200 transform hover:scale-110"
                >
                  <input
                    type="file"
                    id="coverImageUpload"
                    accept="image/*"
                    onChange={handleCoverImageUpload}
                    className="hidden"
                  />
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="20"
                    height="20"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"></path>
                    <circle cx="12" cy="13" r="3"></circle>
                  </svg>
              </label>
              </div>
            )}

            {/* Cover Image Options */}
            {showCoverOptions && (
              <div className="absolute bottom-16 right-4 bg-white dark:bg-gray-800 rounded-lg shadow-xl p-3 z-10">
                <div className="grid grid-cols-3 gap-2">
                  {BACKGROUND_OPTIONS.map((bgUrl, index) => (
                    <div
                      key={index}
                      className="w-20 h-12 rounded-md overflow-hidden cursor-pointer border-2 hover:border-blue-500 transition-all"
                      onClick={() => selectCoverImage(bgUrl)}
                    >
                      <img
                        src={bgUrl || "/placeholder.svg"}
                        alt={`Background ${index + 1}`}
                        className="w-full h-full object-cover"
              />
            </div>
                  ))}
                </div>
              </div>
            )}

            {/* Upload Progress Indicator */}
            {uploadProgress > 0 && uploadProgress < 100 && (
              <div className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-center py-2">
                Uploading... {uploadProgress}%
                <div className="w-full mt-1 bg-gray-300 rounded-full h-1.5">
                  <div className="bg-blue-500 h-1.5 rounded-full" style={{ width: `${uploadProgress}%` }}></div>
                </div>
                </div>
              )}
          </div>

          {/* Profile Info Section */}
          <div className="px-8 pb-8 relative">
            {/* Profile Pic and Info */}
            <div className="flex flex-col items-center text-center mb-6">
              {/* Profile Picture / Animated Avatar */}
              <div className="relative mb-6">
                <div
                  className={`h-32 w-32 rounded-full overflow-hidden border-4 ${darkMode ? "border-gray-700" : "border-white"} shadow-lg mx-auto -mt-16`}
                >
                  {image ? (
                    <img
                      src={typeof image === "string" ? image : image}
                      alt="Profile"
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div
                      className={`w-full h-full flex items-center justify-center text-4xl ${avatarColor} ${getAvatarAnimation()}`}
                    >
                      {selectedAvatar.emoji}
                    </div>
                  )}
                </div>

                {isEditing && isOwnProfile && (
                  <div className="absolute bottom-0 right-0 flex">
                    <button
                      onClick={() => setShowProfileOptions(!showProfileOptions)}
                      className={`w-10 h-10 rounded-full flex items-center justify-center ${darkMode ? "bg-gray-700" : "bg-white"} border ${darkMode ? "border-gray-600" : "border-gray-200"} shadow-md transition-all duration-200 transform hover:scale-110 mr-1`}
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect>
                        <circle cx="8.5" cy="8.5" r="1.5"></circle>
                        <polyline points="21 15 16 10 5 21"></polyline>
                  </svg>
                </button>
                    <label
                      className={`cursor-pointer w-10 h-10 rounded-full flex items-center justify-center ${darkMode ? "bg-gray-700" : "bg-white"} border ${darkMode ? "border-gray-600" : "border-gray-200"} shadow-md transition-all duration-200 transform hover:scale-110`}
                    >
                      <input type="file" accept="image/*" onChange={handleImageUpload} className="hidden" />
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="18"
                        height="18"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path>
                        <circle cx="12" cy="13" r="4"></circle>
                      </svg>
                    </label>
                  </div>
                )}

                {/* Profile Image/Avatar Options */}
                {showProfileOptions && (
                  <div className="absolute -right-24 bottom-0 bg-white dark:bg-gray-800 rounded-lg shadow-xl p-3 z-10">
                    <div className="mb-3">
                      <h4 className="text-sm font-semibold mb-2">Choose Avatar</h4>
                      <div className="grid grid-cols-3 gap-2">
                        {AVATAR_OPTIONS.map((avatar) => (
                          <div
                            key={avatar.id}
                            className={`w-16 h-16 rounded-full overflow-hidden cursor-pointer border-2 ${selectedAvatar.id === avatar.id ? "border-blue-500" : "border-transparent"} hover:border-blue-500 transition-all flex items-center justify-center ${avatar.bgColor}`}
                            onClick={() => selectAvatar(avatar)}
                          >
                            <span className="text-3xl">{avatar.emoji}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    <div>
                      <h4 className="text-sm font-semibold mb-2">Avatar Color</h4>
                      <div className="grid grid-cols-4 gap-2">
                        {[
                          "bg-blue-500",
                          "bg-green-500",
                          "bg-purple-500",
                          "bg-red-500",
                          "bg-yellow-500",
                          "bg-pink-500",
                          "bg-indigo-500",
                          "bg-teal-500",
                        ].map((color) => (
                          <div
                            key={color}
                            className={`w-8 h-8 rounded-full cursor-pointer border-2 ${avatarColor === color ? "border-white" : "border-transparent"} hover:border-white transition-all ${color}`}
                            onClick={() => selectAvatarColor(color)}
                          ></div>
                        ))}
              </div>
            </div>
          </div>
                )}

                {uploadProgress > 0 && uploadProgress < 100 && (
                  <div className="absolute inset-0 flex items-center justify-center bg-black bg-opacity-50 rounded-full">
                    <div className="text-white text-sm font-bold">{uploadProgress}%</div>
                  </div>
                )}
        </div>
        
              {/* User Info - now centered */}
              <div className="text-center">
                {isEditing ? (
                  <div className="mb-4">
                    <div className="flex gap-2 mb-2">
                      <input
                        type="text"
                        value={firstName}
                        onChange={(e) => setFirstName(e.target.value)}
                        className={`flex-1 p-2 rounded-lg border ${
                          darkMode ? "bg-gray-700 border-gray-600 text-white" : "bg-white border-gray-300 text-gray-800"
                        } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                        placeholder="First Name"
                      />
                      <input
                        type="text"
                        value={lastName}
                        onChange={(e) => setLastName(e.target.value)}
                        className={`flex-1 p-2 rounded-lg border ${
                          darkMode ? "bg-gray-700 border-gray-600 text-white" : "bg-white border-gray-300 text-gray-800"
                        } focus:outline-none focus:ring-2 focus:ring-blue-500`}
                        placeholder="Last Name"
                      />
            </div>
            </div>
                ) : (
                  <h2 className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>{name}</h2>
                )}
                <p className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                  @{userInfo?.username || "username"}
                </p>
                {!isOwnProfile && (
                  <p className={`text-xs mt-1 ${darkMode ? "text-gray-500" : "text-gray-400"}`}>
                    Viewing shared profile
                  </p>
                )}

                {/* Role Badge */}
                <div className="mt-2">
                  <span
                    className={`inline-block px-4 py-1.5 rounded-full text-sm font-medium ${
                      userInfo?.role === "TEACHER"
                        ? darkMode
                          ? "bg-purple-900 text-purple-200"
                          : "bg-purple-100 text-purple-800"
                        : userInfo?.role === "ADMIN"
                          ? darkMode
                            ? "bg-red-900 text-red-200"
                            : "bg-red-100 text-red-800"
                          : darkMode
                            ? "bg-blue-900 text-blue-200"
                            : "bg-blue-100 text-blue-800"
                    }`}
                  >
                    {userInfo?.role || "STUDENT"}
                  </span>
            </div>
          </div>
        </div>
        
        {/* Bio Section */}
            <div className="mb-8">
              <h3 className={`text-lg font-semibold mb-2 ${darkMode ? "text-white" : "text-gray-800"} text-center`}>
                About Me
              </h3>
              {isEditing ? (
                <textarea
                  value={bio}
                  onChange={(e) => setBio(e.target.value)}
                  className={`w-full p-4 rounded-lg border ${
                    darkMode ? "bg-gray-700 border-gray-600 text-white" : "bg-white border-gray-300 text-gray-800"
                  } focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none`}
                  placeholder="Tell us about yourself..."
                  rows={4}
                />
              ) : (
                <p className={`${darkMode ? "text-gray-300" : "text-gray-700"} text-center`}>{bio}</p>
              )}
            </div>

            {/* Stats Section */}
            <div className="mb-6 text-center">
              <div className="flex flex-wrap justify-center gap-4">
                {isStudentProfile && (
                  <>
                    <div
                      className={`p-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"} transition-transform duration-200 transform hover:scale-105 min-w-[120px]`}
                    >
                      <div className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>
                        {isOwnProfile ? userPosts.length : visiblePosts.length}
                      </div>
                      <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                        {isOwnProfile ? "Posts" : "Shared Posts"}
                      </div>
                    </div>

                    {!isOwnProfile && (
                      <>
                        <div
                          className={`p-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"} transition-transform duration-200 transform hover:scale-105 min-w-[120px]`}
                        >
                          <div className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>
                            {sharedClassIds.length}
                          </div>
                          <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                            Shared Classes
                          </div>
                        </div>
                        {hiddenPostsCount > 0 && (
                          <div
                            className={`p-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"} transition-transform duration-200 transform hover:scale-105 min-w-[120px]`}
                          >
                            <div className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>
                              {hiddenPostsCount}
                            </div>
                            <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                              Hidden Posts
                            </div>
                          </div>
                        )}
                      </>
                    )}
                  </>
                )}

                {isTeacherProfile && (
                  <>
                    <div
                      className={`p-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"} transition-transform duration-200 transform hover:scale-105 min-w-[120px]`}
                    >
                      <div className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>
                        {profileClassIds.length}
                      </div>
                      <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                        Classes
                      </div>
                    </div>
                    <div
                      className={`p-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"} transition-transform duration-200 transform hover:scale-105 min-w-[120px]`}
                    >
                      <div className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>
                        View
                      </div>
                      <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                        Students
                      </div>
                    </div>
                  </>
                )}

                {isAdminProfile && (
                  <>
                    <div
                      className={`p-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"} transition-transform duration-200 transform hover:scale-105 min-w-[120px]`}
                    >
                      <div className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>
                        Manage
                      </div>
                      <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                        Users
                      </div>
                    </div>
                    <div
                      className={`p-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"} transition-transform duration-200 transform hover:scale-105 min-w-[120px]`}
                    >
                      <div className={`text-2xl font-bold ${darkMode ? "text-white" : "text-gray-800"}`}>
                        View
                      </div>
                      <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                        Reports
                      </div>
                    </div>
                  </>
                )}
              </div>
            </div>

            {/* Action Buttons */}
            {isOwnProfile ? (
              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <motion.button
                  className={`px-6 py-3 rounded-full font-medium ${
                    darkMode
                      ? isEditing
                        ? "bg-green-600 hover:bg-green-700"
                        : "bg-blue-600 hover:bg-blue-700"
                      : isEditing
                        ? "bg-green-500 hover:bg-green-600"
                        : "bg-blue-500 hover:bg-blue-600"
                  } text-white flex items-center justify-center shadow-lg transition-all duration-200`}
                  onClick={isEditing ? handleProfileUpdate : () => setIsEditing(true)}
                  disabled={saving}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  {saving ? (
                    <span className="flex items-center">
                      <svg
                        className="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                      >
                        <circle
                          className="opacity-25"
                          cx="12"
                          cy="12"
                          r="10"
                          stroke="currentColor"
                          strokeWidth="4"
                        ></circle>
                        <path
                          className="opacity-75"
                          fill="currentColor"
                          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                        ></path>
                      </svg>
                      Saving...
                    </span>
                  ) : (
                    <>
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        className="mr-2"
                      >
                        {isEditing ? (
                          <path d="M5 13l4 4L19 7"></path>
                        ) : (
                          <path d="M17 3a2.85 2.85 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z"></path>
                        )}
                      </svg>
                      {isEditing ? "Save Changes" : "Edit Profile"}
                    </>
                  )}
                </motion.button>

                {isEditing && (
                  <motion.button
                    className={`px-6 py-3 rounded-full font-medium ${
                      darkMode ? "bg-red-600 hover:bg-red-700" : "bg-red-500 hover:bg-red-600"
                    } text-white flex items-center justify-center shadow-lg transition-all duration-200`}
                    onClick={() => setIsEditing(false)}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="mr-2"
                    >
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                    Cancel
                  </motion.button>
                )}
              </div>
            ) : (
              <div className="flex flex-col sm:flex-row gap-3 justify-center">
                <motion.button
                  className={`px-6 py-3 rounded-full font-medium ${
                    darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                  } text-white flex items-center justify-center shadow-lg transition-all duration-200`}
                  onClick={() => document.getElementById("posts-section")?.scrollIntoView({ behavior: "smooth" })}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  View Shared Posts
                </motion.button>
                <Link to="/student-hub">
                  <motion.button
                    className={`px-6 py-3 rounded-full font-medium ${
                      darkMode ? "bg-gray-700 hover:bg-gray-600" : "bg-white hover:bg-gray-100"
                    } ${darkMode ? "text-white" : "text-gray-800"} flex items-center justify-center shadow-lg transition-all duration-200`}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
                    Back to Hub
                  </motion.button>
                </Link>
              </div>
            )}
          </div>
        </motion.div>

        {/* Content Tabs */}
        <div className="mb-6">
          <div className={`flex border-b ${darkMode ? "border-gray-700" : "border-gray-200"}`}>
            {getRoleTabs(userInfo?.role, isOwnProfile).map((tab) => (
              <button
                key={tab.key}
                className={`py-3 px-6 font-medium transition-all duration-200 ${
                  activeTab === tab.key
                    ? darkMode
                      ? "text-white border-b-2 border-blue-500"
                      : "text-blue-600 border-b-2 border-blue-500"
                    : darkMode
                      ? "text-gray-400 hover:text-gray-300"
                      : "text-gray-500 hover:text-gray-700"
                }`}
                onClick={() => setActiveTab(tab.key)}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        
        {/* Recent Posts Section */}
        {activeTab === "posts" && isStudentProfile && (
          <motion.div
            id="posts-section"
            className={`rounded-2xl shadow-2xl overflow-hidden p-8 ${darkMode ? "bg-gray-800" : "bg-white"}`}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <h2 className={`text-2xl font-bold mb-6 ${darkMode ? "text-white" : "text-gray-800"}`}>
              {isOwnProfile ? "Your Posts" : "Shared Posts"}
            </h2>

            {visiblePosts.length === 0 ? (
              // Empty State
              <div className={`text-center py-12 px-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"}`}>
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="48"
                  height="48"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={`mx-auto mb-4 ${darkMode ? "text-gray-400" : "text-blue-400"}`}
                >
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                  <line x1="12" y1="18" x2="12" y2="12"></line>
                  <line x1="9" y1="15" x2="15" y2="15"></line>
                </svg>
                <h3 className={`text-xl font-semibold mb-2 ${darkMode ? "text-white" : "text-gray-800"}`}>
                  {isOwnProfile ? "No Posts Yet" : "No Shared Posts"}
                </h3>
                <p className={`mb-6 ${darkMode ? "text-gray-400" : "text-gray-600"}`}>
                  {isOwnProfile
                    ? "Share your first literary creation with the community!"
                    : "You can only see posts from classes you share with this student."}
                </p>
                {isOwnProfile ? (
                  <Link to="/student-hub">
                    <motion.button
                      className={`px-6 py-3 rounded-full font-medium ${
                        darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                      } text-white shadow-lg transition-all duration-200`}
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                    >
                      Create Your First Post
                    </motion.button>
                  </Link>
                ) : (
                  <Link to="/student-hub">
                    <motion.button
                      className={`px-6 py-3 rounded-full font-medium ${
                        darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                      } text-white shadow-lg transition-all duration-200`}
                      whileHover={{ scale: 1.05 }}
                      whileTap={{ scale: 0.95 }}
                    >
                      Browse Classes
                    </motion.button>
                  </Link>
                )}
              </div>
            ) : (
              // User posts list
              <div className="space-y-4">
                {visiblePosts.map((post) => (
                  <motion.div
                    key={post.id}
                    className={`p-5 rounded-xl border ${darkMode ? "bg-gray-700 border-gray-600" : "bg-white border-gray-200"} hover:shadow-lg transition-all duration-200`}
                    whileHover={{ y: -3, scale: 1.01 }}
                  >
                    <Link to={`/class/${post.class_id}/post/${post.id}`}>
                      <h3 className={`text-xl font-bold mb-2 ${darkMode ? "text-white" : "text-gray-800"}`}>
                        {post.title}
                      </h3>
                    </Link>
                    <div className="flex justify-between items-center">
                      <div className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-500"}`}>
                        {new Date(post.created_at).toLocaleDateString()} • {post.class_name || "Class"}
                      </div>
                      <div className="flex items-center space-x-4">
                        <span className="flex items-center">
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            className="h-4 w-4 mr-1"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
                            />
                          </svg>
                          {post.likes || 0}
                        </span>
                        <span className="flex items-center">
                          <svg
                            xmlns="http://www.w3.org/2000/svg"
                            className="h-4 w-4 mr-1"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
                            />
                          </svg>
                          {post.comments || 0}
                        </span>
                      </div>
                    </div>
                  </motion.div>
                ))}
              </div>
            )}
          </motion.div>
        )}

        {/* Saved Content Section */}
        {activeTab === "saved" && isStudentProfile && isOwnProfile && (
          <motion.div
            className={`rounded-2xl shadow-2xl overflow-hidden p-8 ${darkMode ? "bg-gray-800" : "bg-white"}`}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <h2 className={`text-2xl font-bold mb-6 ${darkMode ? "text-white" : "text-gray-800"}`}>Saved Items</h2>

            {/* Empty State for Saved Items */}
            <div className={`text-center py-12 px-4 rounded-xl ${darkMode ? "bg-gray-700/50" : "bg-blue-50"}`}>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="48"
                height="48"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                className={`mx-auto mb-4 ${darkMode ? "text-gray-400" : "text-blue-400"}`}
              >
                <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"></path>
              </svg>
              <h3 className={`text-xl font-semibold mb-2 ${darkMode ? "text-white" : "text-gray-800"}`}>
                No Saved Items
              </h3>
              <p className={`mb-6 ${darkMode ? "text-gray-400" : "text-gray-600"}`}>
                Save posts and resources to access them later.
              </p>
              <Link to="/student-hub">
                <motion.button
                  className={`px-6 py-3 rounded-full font-medium ${
                    darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                  } text-white shadow-lg transition-all duration-200`}
                  whileHover={{ scale: 1.05 }}
                  whileTap={{ scale: 0.95 }}
                >
                  Browse Content
                </motion.button>
              </Link>
            </div>
          </motion.div>
        )}

        {/* Teacher: Classes Section */}
        {activeTab === "classes" && isTeacherProfile && (
          <motion.div
            className={`rounded-2xl shadow-2xl overflow-hidden p-8 ${darkMode ? "bg-gray-800" : "bg-white"}`}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <h2 className={`text-2xl font-bold mb-4 ${darkMode ? "text-white" : "text-gray-800"}`}>Your Classes</h2>
            <p className={`${darkMode ? "text-gray-300" : "text-gray-600"} mb-6`}>
              You’re assigned to {profileClassIds.length} class{profileClassIds.length === 1 ? "" : "es"}. Manage
              rosters, access codes, and class settings from your dashboard.
            </p>
            <Link to="/teacher-dashboard">
              <motion.button
                className={`px-6 py-3 rounded-full font-medium ${
                  darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                } text-white shadow-lg transition-all duration-200`}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                Open Teacher Dashboard
              </motion.button>
            </Link>
          </motion.div>
        )}

        {/* Teacher: Students Section */}
        {activeTab === "students" && isTeacherProfile && (
          <motion.div
            className={`rounded-2xl shadow-2xl overflow-hidden p-8 ${darkMode ? "bg-gray-800" : "bg-white"}`}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <h2 className={`text-2xl font-bold mb-4 ${darkMode ? "text-white" : "text-gray-800"}`}>Students</h2>
            <p className={`${darkMode ? "text-gray-300" : "text-gray-600"} mb-6`}>
              Review student participation, posts, and class enrollment from your dashboard.
            </p>
            <Link to="/teacher-dashboard">
              <motion.button
                className={`px-6 py-3 rounded-full font-medium ${
                  darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                } text-white shadow-lg transition-all duration-200`}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                Manage Students
              </motion.button>
            </Link>
          </motion.div>
        )}

        {/* Admin: Users Section */}
        {activeTab === "users" && isAdminProfile && (
          <motion.div
            className={`rounded-2xl shadow-2xl overflow-hidden p-8 ${darkMode ? "bg-gray-800" : "bg-white"}`}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <h2 className={`text-2xl font-bold mb-4 ${darkMode ? "text-white" : "text-gray-800"}`}>Users</h2>
            <p className={`${darkMode ? "text-gray-300" : "text-gray-600"} mb-6`}>
              Manage user access, roles, and account details from the admin dashboard.
            </p>
            <Link to="/admin-dashboard">
              <motion.button
                className={`px-6 py-3 rounded-full font-medium ${
                  darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                } text-white shadow-lg transition-all duration-200`}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                Open Admin Dashboard
              </motion.button>
            </Link>
          </motion.div>
        )}

        {/* Admin: Reports Section */}
        {activeTab === "reports" && isAdminProfile && (
          <motion.div
            className={`rounded-2xl shadow-2xl overflow-hidden p-8 ${darkMode ? "bg-gray-800" : "bg-white"}`}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
          >
            <h2 className={`text-2xl font-bold mb-4 ${darkMode ? "text-white" : "text-gray-800"}`}>Reports</h2>
            <p className={`${darkMode ? "text-gray-300" : "text-gray-600"} mb-6`}>
              Review platform activity, class performance, and moderation reports.
            </p>
            <Link to="/admin-dashboard">
              <motion.button
                className={`px-6 py-3 rounded-full font-medium ${
                  darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
                } text-white shadow-lg transition-all duration-200`}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
              >
                View Reports
              </motion.button>
            </Link>
          </motion.div>
        )}
      </main>

      {/* Floating Action Button */}
      {isOwnProfile && isStudentProfile && (
        <motion.div className="fixed bottom-8 right-8" whileHover={{ scale: 1.1 }} whileTap={{ scale: 0.9 }}>
          <Link to="/student-hub">
            <button 
              className={`w-14 h-14 rounded-full shadow-xl flex items-center justify-center ${
                darkMode ? "bg-blue-600 hover:bg-blue-700" : "bg-blue-500 hover:bg-blue-600"
              } text-white transition-all duration-200 transform hover:-translate-y-1`}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="24"
                height="24"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <line x1="12" y1="5" x2="12" y2="19"></line>
                <line x1="5" y1="12" x2="19" y2="12"></line>
              </svg>
            </button>
          </Link>
        </motion.div>
      )}
      <Footer darkMode={darkMode} />
    </div>
  )
}

export default StudentProfile

