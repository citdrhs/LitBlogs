import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { motion } from "framer-motion"
import axios from "axios"
import Navbar from "./components/Navbar"
import Footer from "./components/Footer"
import "./LitBlogs.css"
import {
  applyGlobalUserSettings,
  normalizeUserSettings,
  saveLocalUserSettings,
} from "./utils/userSettings"
import { clearStoredAuth, logoutBrowserSession } from "./utils/auth"

const SETTINGS_KEY = "litblogs_settings"

const getSystemDarkMode = () => {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches
}

const getDefaultSettings = () => {
  let darkMode = getSystemDarkMode()

  if (typeof window !== "undefined") {
    const storedDarkMode = localStorage.getItem("darkMode")
    if (storedDarkMode !== null) {
      try {
        darkMode = JSON.parse(storedDarkMode)
      } catch {
        darkMode = getSystemDarkMode()
      }
    }
  }

  return {
    darkMode,
    reducedMotion: false,
    emailNotifications: true,
    assignmentReminders: true,
    autoPlayVideos: false,
    compactFeed: false,
    rememberDrafts: true,
    showProfileToClassmates: true,
    editorFontSize: "medium",
  }
}

const loadStoredSettings = () => {
  const defaults = getDefaultSettings()

  if (typeof window === "undefined") {
    return defaults
  }

  const rawSettings = localStorage.getItem(SETTINGS_KEY)
  if (!rawSettings) {
    return defaults
  }

  try {
    const parsed = JSON.parse(rawSettings)
    return normalizeUserSettings({
      ...defaults,
      ...parsed,
    })
  } catch {
    return normalizeUserSettings(defaults)
  }
}

const urlBase64ToUint8Array = (base64String) => {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/")
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)

  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i)
  }

  return outputArray
}

const ToggleRow = ({ label, description, enabled, onToggle, darkMode }) => {
  return (
    <div className="flex items-start justify-between gap-4 py-4 border-b border-gray-200/70 dark:border-gray-700/70 last:border-b-0">
      <div>
        <p className="text-base font-semibold">{label}</p>
        <p className={`text-sm ${darkMode ? "text-gray-400" : "text-gray-600"}`}>{description}</p>
      </div>
      <button
        type="button"
        onClick={onToggle}
        aria-pressed={enabled}
        className={`relative inline-flex h-7 w-14 items-center rounded-full transition-colors ${
          enabled ? "bg-blue-600" : darkMode ? "bg-gray-600" : "bg-gray-300"
        }`}
      >
        <span
          className={`inline-block h-5 w-5 transform rounded-full bg-white transition-transform ${
            enabled ? "translate-x-8" : "translate-x-1"
          }`}
        />
      </button>
    </div>
  )
}

const Settings = ({ onDarkModeChange }) => {
  const navigate = useNavigate()
  const [userInfo, setUserInfo] = useState(null)
  const [settings, setSettings] = useState(loadStoredSettings)
  const [deleteConfirmation, setDeleteConfirmation] = useState("")
  const [isDeleting, setIsDeleting] = useState(false)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [statusMessage, setStatusMessage] = useState("")
  const [errorMessage, setErrorMessage] = useState("")
  const [pushSupported, setPushSupported] = useState(false)
  const [pushSubscribed, setPushSubscribed] = useState(false)
  const [pushBusy, setPushBusy] = useState(false)
  const userRole = (userInfo?.role || "").toString().toUpperCase()
  const isStudentUser = userRole === "STUDENT"

  const pageClasses = useMemo(
    () =>
      `min-h-screen transition-all duration-500 ${
        settings.darkMode
          ? "bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200"
          : "bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900"
      }`,
    [settings.darkMode]
  )

  useEffect(() => {
    const storedUserInfo = sessionStorage.getItem("user_info")
    if (storedUserInfo) {
      try {
        setUserInfo(JSON.parse(storedUserInfo))
      } catch {
        setUserInfo(null)
      }
    }
  }, [navigate])

  useEffect(() => {
    saveLocalUserSettings(settings, userInfo?.role)
    applyGlobalUserSettings(settings)
  }, [settings])

  useEffect(() => {
    localStorage.setItem("darkMode", JSON.stringify(settings.darkMode))
    if (settings.darkMode) {
      document.documentElement.classList.add("dark")
    } else {
      document.documentElement.classList.remove("dark")
    }

    if (typeof onDarkModeChange === "function") {
      onDarkModeChange(settings.darkMode)
    }
  }, [settings.darkMode, onDarkModeChange])

  const setSetting = (key, value) => {
    const nextSettings = normalizeUserSettings({ ...settings, [key]: value }, userInfo?.role)
    setSettings(nextSettings)
    persistSettings(nextSettings)
    setErrorMessage("")
    setStatusMessage("Preferences saved.")
  }

  const toggleSetting = (key) => {
    const nextSettings = normalizeUserSettings({ ...settings, [key]: !settings[key] }, userInfo?.role)
    setSettings(nextSettings)
    persistSettings(nextSettings)
    setErrorMessage("")
    setStatusMessage("Preferences saved.")
  }

  const handleResetDefaults = () => {
    const nextSettings = normalizeUserSettings(getDefaultSettings(), userInfo?.role)
    setSettings(nextSettings)
    persistSettings(nextSettings)
    setErrorMessage("")
    setStatusMessage("Settings reset to default values.")
  }

  const persistSettings = async (nextSettings) => {
    try {
      setIsSavingSettings(true)
      const response = await axios.put("/user/settings", nextSettings)
      const normalized = normalizeUserSettings(response.data, userInfo?.role)
      setSettings((prev) => ({ ...prev, ...normalized }))
    } catch (error) {
      console.error("Failed to save settings:", error)
      setErrorMessage(error?.response?.data?.detail || "Failed to save settings to your account.")
    } finally {
      setIsSavingSettings(false)
    }
  }

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const response = await axios.get("/user/settings")
        const normalized = normalizeUserSettings(response.data, userInfo?.role)
        setSettings(normalized)
      } catch (error) {
        console.error("Failed to fetch user settings:", error)
      }
    }

    fetchSettings()
  }, [userInfo?.role])

  useEffect(() => {
    setPushSupported(
      typeof window !== "undefined" &&
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window
    )
  }, [])

  useEffect(() => {
    const fetchPushStatus = async () => {
      if (!pushSupported) {
        return
      }

      try {
        const response = await axios.get("/push/subscription")
        setPushSubscribed(Boolean(response?.data?.subscribed))
      } catch {
        setPushSubscribed(false)
      }
    }

    fetchPushStatus()
  }, [pushSupported])

  const disableBrowserPush = async (silent = false) => {
    if (!pushSupported) {
      return
    }

    setPushBusy(true)
    try {
      const swUrl = `${import.meta.env.BASE_URL}push-sw.js`
      const registration = await navigator.serviceWorker.register(swUrl, {
        scope: import.meta.env.BASE_URL,
      })
      const subscription = await registration.pushManager.getSubscription()

      if (subscription) {
        await axios.delete("/push/unsubscribe", {
          data: {
            subscription: subscription.toJSON(),
          },
        })
        await subscription.unsubscribe()
      }

      setPushSubscribed(false)
      if (!silent) {
        setStatusMessage("Browser push notifications are now off.")
        setErrorMessage("")
      }
    } catch (error) {
      if (!silent) {
        setErrorMessage(error?.response?.data?.detail || "Failed to disable browser push notifications.")
      }
    } finally {
      setPushBusy(false)
    }
  }

  const enableBrowserPush = async () => {
    if (!pushSupported) {
      setErrorMessage("This browser does not support push notifications.")
      return
    }

    if (!settings.emailNotifications || !settings.assignmentReminders) {
      setErrorMessage("Turn on Email notifications and Assignment reminders first.")
      return
    }

    setPushBusy(true)
    try {
      const keyResponse = await axios.get("/push/public-key")

      if (!keyResponse?.data?.enabled || !keyResponse?.data?.publicKey) {
        setErrorMessage("Push notifications are not configured on the server.")
        setPushBusy(false)
        return
      }

      const permission = await Notification.requestPermission()
      if (permission !== "granted") {
        setErrorMessage("Notification permission was denied.")
        setPushBusy(false)
        return
      }

      const swUrl = `${import.meta.env.BASE_URL}push-sw.js`
      const registration = await navigator.serviceWorker.register(swUrl, {
        scope: import.meta.env.BASE_URL,
      })

      let subscription = await registration.pushManager.getSubscription()
      if (!subscription) {
        subscription = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(keyResponse.data.publicKey),
        })
      }

      await axios.post(
        "/push/subscribe",
        {
          subscription: subscription.toJSON(),
        }
      )

      setPushSubscribed(true)
      setErrorMessage("")
      setStatusMessage("Browser push notifications are enabled.")
    } catch (error) {
      const detail = error?.response?.data?.detail
      const detailText = Array.isArray(detail)
        ? detail.map((item) => item?.msg || JSON.stringify(item)).join("; ")
        : (typeof detail === "string" ? detail : "")
      const fallback = error?.message || "Failed to enable browser push notifications."
      setErrorMessage(detailText || fallback)
      console.error("Push enable failed:", {
        message: error?.message,
        status: error?.response?.status,
        data: error?.response?.data,
      })
    } finally {
      setPushBusy(false)
    }
  }

  useEffect(() => {
    if (!pushSupported || !pushSubscribed) {
      return
    }

    if (!settings.emailNotifications || !settings.assignmentReminders) {
      disableBrowserPush(true)
    }
  }, [settings.emailNotifications, settings.assignmentReminders, pushSupported, pushSubscribed])

  const handleClearClassCache = () => {
    sessionStorage.removeItem("class_info")
    setErrorMessage("")
    setStatusMessage("Cleared cached class data for this device.")
  }

  const handleExportSettings = () => {
    const data = new Blob([JSON.stringify(settings, null, 2)], { type: "application/json" })
    const downloadUrl = URL.createObjectURL(data)
    const anchor = document.createElement("a")
    anchor.href = downloadUrl
    anchor.download = "litblogs-settings.json"
    anchor.click()
    URL.revokeObjectURL(downloadUrl)
    setErrorMessage("")
    setStatusMessage("Exported your settings as JSON.")
  }

  const handleSignOut = async () => {
    try {
      await logoutBrowserSession()
      setUserInfo(null)
      navigate("/")
    } catch {
      window.alert("Unable to sign out. Please try again.")
    }
  }

  const handleDeleteAccount = async () => {
    setErrorMessage("")
    setStatusMessage("")

    if (deleteConfirmation.trim().toUpperCase() !== "DELETE") {
      setErrorMessage("Type DELETE to confirm account deletion.")
      return
    }

    setIsDeleting(true)

    try {
      await axios.delete("/user/account", {
        params: { confirm: "DELETE" },
      })

      clearStoredAuth()
      localStorage.removeItem(SETTINGS_KEY)

      setStatusMessage("Account deleted successfully. Redirecting...")
      setTimeout(() => navigate("/"), 1200)
    } catch (error) {
      setErrorMessage(error?.response?.data?.detail || "Failed to delete account. Please try again.")
    } finally {
      setIsDeleting(false)
    }
  }

  return (
    <div className={pageClasses}>
      <Navbar userInfo={userInfo} onSignOut={handleSignOut} darkMode={settings.darkMode} logo="logo.png" />

      <div className="pt-24 pb-10 px-4 md:px-8">
        <div className="max-w-4xl mx-auto space-y-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
            className={`rounded-2xl p-6 md:p-8 border shadow-lg ${
              settings.darkMode ? "bg-gray-900/70 border-gray-700" : "bg-white/90 border-gray-200"
            }`}
          >
            <h1 className="text-3xl md:text-4xl font-bold">Settings</h1>
            <p className={`mt-2 ${settings.darkMode ? "text-gray-400" : "text-gray-600"}`}>
              Manage your technical preferences, privacy controls, and account actions.
            </p>
            <p className={`mt-3 text-sm ${settings.darkMode ? "text-gray-500" : "text-gray-500"}`}>
              Changes are saved automatically on this device.
            </p>
            {isSavingSettings && (
              <p className={`mt-2 text-xs ${settings.darkMode ? "text-blue-300" : "text-blue-700"}`}>
                Syncing your settings to your account...
              </p>
            )}
          </motion.div>

          {(statusMessage || errorMessage) && (
            <div
              className={`rounded-xl px-4 py-3 border text-sm ${
                errorMessage
                  ? "bg-red-50 text-red-700 border-red-200 dark:bg-red-900/40 dark:text-red-200 dark:border-red-700"
                  : "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-200 dark:border-emerald-700"
              }`}
            >
              {errorMessage || statusMessage}
            </div>
          )}

          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.05 }}
            className={`rounded-2xl p-6 md:p-8 border shadow-lg ${
              settings.darkMode ? "bg-gray-900/70 border-gray-700" : "bg-white/90 border-gray-200"
            }`}
          >
            <h2 className="text-2xl font-semibold">Appearance</h2>
            <ToggleRow
              label="Dark mode"
              description="Switch between light and dark themes."
              enabled={settings.darkMode}
              onToggle={() => toggleSetting("darkMode")}
              darkMode={settings.darkMode}
            />
            <ToggleRow
              label="Reduced motion"
              description="Use fewer animations where supported."
              enabled={settings.reducedMotion}
              onToggle={() => toggleSetting("reducedMotion")}
              darkMode={settings.darkMode}
            />
          </motion.section>

          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.1 }}
            className={`rounded-2xl p-6 md:p-8 border shadow-lg ${
              settings.darkMode ? "bg-gray-900/70 border-gray-700" : "bg-white/90 border-gray-200"
            }`}
          >
            <h2 className="text-2xl font-semibold">Notifications</h2>
            <ToggleRow
              label="Email notifications"
              description="Receive account and classroom updates by email."
              enabled={settings.emailNotifications}
              onToggle={() => toggleSetting("emailNotifications")}
              darkMode={settings.darkMode}
            />
            <ToggleRow
              label="Assignment reminders"
              description="Get reminders before assignment due dates."
              enabled={settings.assignmentReminders}
              onToggle={() => toggleSetting("assignmentReminders")}
              darkMode={settings.darkMode}
            />
            <div className="pt-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <div>
                <p className="text-base font-semibold">Browser push notifications</p>
                <p className={`text-sm ${settings.darkMode ? "text-gray-400" : "text-gray-600"}`}>
                  Receive reminder notifications even when LitBlogs is not open.
                </p>
                {!pushSupported && (
                  <p className={`text-xs mt-1 ${settings.darkMode ? "text-amber-300" : "text-amber-700"}`}>
                    This browser does not support push notifications.
                  </p>
                )}
              </div>
              <div className="flex items-center gap-2">
                {pushSubscribed ? (
                  <button
                    type="button"
                    onClick={() => disableBrowserPush(false)}
                    disabled={pushBusy}
                    className={`px-4 py-2 rounded-lg border font-semibold transition ${
                      settings.darkMode
                        ? "border-red-400 text-red-200 hover:bg-red-900/40"
                        : "border-red-400 text-red-700 hover:bg-red-50"
                    } ${pushBusy ? "opacity-60 cursor-not-allowed" : ""}`}
                  >
                    {pushBusy ? "Working..." : "Disable"}
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={enableBrowserPush}
                    disabled={pushBusy || !pushSupported}
                    className={`px-4 py-2 rounded-lg border font-semibold transition ${
                      settings.darkMode
                        ? "border-blue-400 text-blue-200 hover:bg-blue-900/40"
                        : "border-blue-500 text-blue-700 hover:bg-blue-50"
                    } ${(pushBusy || !pushSupported) ? "opacity-60 cursor-not-allowed" : ""}`}
                  >
                    {pushBusy ? "Working..." : "Enable"}
                  </button>
                )}
              </div>
            </div>
          </motion.section>

          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.15 }}
            className={`rounded-2xl p-6 md:p-8 border shadow-lg ${
              settings.darkMode ? "bg-gray-900/70 border-gray-700" : "bg-white/90 border-gray-200"
            }`}
          >
            <h2 className="text-2xl font-semibold">Content & Editing</h2>
            <ToggleRow
              label="Auto-play videos"
              description="Auto-play inline videos in feed views when available."
              enabled={settings.autoPlayVideos}
              onToggle={() => toggleSetting("autoPlayVideos")}
              darkMode={settings.darkMode}
            />
            <ToggleRow
              label="Compact feed"
              description="Use denser spacing for feed cards to show more content."
              enabled={settings.compactFeed}
              onToggle={() => toggleSetting("compactFeed")}
              darkMode={settings.darkMode}
            />
            <ToggleRow
              label="Remember unsent drafts"
              description="Keep draft content in local storage for recovery."
              enabled={settings.rememberDrafts}
              onToggle={() => toggleSetting("rememberDrafts")}
              darkMode={settings.darkMode}
            />

            <div className="pt-4 flex flex-col md:flex-row md:items-center md:justify-between gap-3">
              <div>
                <p className="text-base font-semibold">Editor font size</p>
                <p className={`text-sm ${settings.darkMode ? "text-gray-400" : "text-gray-600"}`}>
                  Set your preferred default text size in editing surfaces.
                </p>
              </div>
              <select
                value={settings.editorFontSize}
                onChange={(event) => setSetting("editorFontSize", event.target.value)}
                className={`rounded-lg px-3 py-2 border focus:outline-none focus:ring-2 focus:ring-blue-500 ${
                  settings.darkMode
                    ? "bg-gray-800 border-gray-600 text-gray-200"
                    : "bg-white border-gray-300 text-gray-900"
                }`}
              >
                <option value="small">Small</option>
                <option value="medium">Medium</option>
                <option value="large">Large</option>
              </select>
            </div>
          </motion.section>

          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className={`rounded-2xl p-6 md:p-8 border shadow-lg ${
              settings.darkMode ? "bg-gray-900/70 border-gray-700" : "bg-white/90 border-gray-200"
            }`}
          >
            <h2 className="text-2xl font-semibold">Privacy & Data</h2>
            {isStudentUser ? (
              <ToggleRow
                label="Profile visible to classmates"
                description="Allow classmates in shared classes to view your profile details."
                enabled={settings.showProfileToClassmates}
                onToggle={() => toggleSetting("showProfileToClassmates")}
                darkMode={settings.darkMode}
              />
            ) : (
              <p className={`mt-2 text-sm ${settings.darkMode ? "text-gray-400" : "text-gray-600"}`}>
                Teacher and admin profiles are shown with essential information only in shared contexts.
              </p>
            )}

            <div className="pt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={handleClearClassCache}
                className={`px-4 py-2 rounded-lg border transition ${
                  settings.darkMode
                    ? "border-gray-600 bg-gray-800 hover:bg-gray-700"
                    : "border-gray-300 bg-white hover:bg-gray-100"
                }`}
              >
                Clear cached class data
              </button>
              <button
                type="button"
                onClick={handleExportSettings}
                className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white transition"
              >
                Export settings
              </button>
              <button
                type="button"
                onClick={handleResetDefaults}
                className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-600 text-white transition"
              >
                Reset defaults
              </button>
            </div>
          </motion.section>

          <motion.section
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, delay: 0.25 }}
            className={`rounded-2xl p-6 md:p-8 border shadow-lg ${
              settings.darkMode
                ? "bg-red-950/40 border-red-800"
                : "bg-red-50/90 border-red-200"
            }`}
          >
            <h2 className="text-2xl font-semibold text-red-600 dark:text-red-300">Danger Zone</h2>
            <p className={`mt-2 text-sm ${settings.darkMode ? "text-red-200" : "text-red-700"}`}>
              Deleting your account permanently removes your profile and related data. This action cannot be undone.
            </p>

            <div className="mt-4 flex flex-col gap-3 md:max-w-md">
              <label className="text-sm font-medium" htmlFor="delete-confirm-input">
                Type <span className="font-bold">DELETE</span> to confirm
              </label>
              <input
                id="delete-confirm-input"
                type="text"
                value={deleteConfirmation}
                onChange={(event) => setDeleteConfirmation(event.target.value)}
                placeholder="DELETE"
                className={`rounded-lg px-3 py-2 border focus:outline-none focus:ring-2 focus:ring-red-500 ${
                  settings.darkMode
                    ? "bg-gray-900 border-red-700 text-gray-100"
                    : "bg-white border-red-300 text-gray-900"
                }`}
              />

              <button
                type="button"
                onClick={handleDeleteAccount}
                disabled={isDeleting}
                className="px-4 py-2 rounded-lg bg-red-600 hover:bg-red-700 text-white font-semibold transition disabled:opacity-60"
              >
                {isDeleting ? "Deleting account..." : "Delete my account"}
              </button>
            </div>
          </motion.section>
        </div>
      </div>

      <Footer darkMode={settings.darkMode} />
    </div>
  )
}

export default Settings
