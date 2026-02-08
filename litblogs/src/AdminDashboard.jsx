import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import axios from 'axios';
import Navbar from './components/Navbar';
import Footer from './components/Footer';

const AdminDashboard = () => {
  const navigate = useNavigate();
  const [darkMode] = useState(() => {
    return JSON.parse(localStorage.getItem('darkMode')) ?? false;
  });
  const [users, setUsers] = useState([]);
  const [classes, setClasses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [userInfo, setUserInfo] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [userQuery, setUserQuery] = useState('');

  useEffect(() => {
    const token = localStorage.getItem('token');
    if (!token) {
      navigate('/sign-in');
      return;
    }

    const fetchData = async () => {
      try {
        const config = {
          headers: { Authorization: `Bearer ${token}` }
        };

        // Fetch all users and classes
        const [usersResponse, classesResponse] = await Promise.all([
          axios.get('http://localhost:8000/api/users', config),
          axios.get('http://localhost:8000/api/classes', config)
        ]);

        setUsers(usersResponse.data);
        setClasses(classesResponse.data);
        setLastUpdated(new Date());
        setLoading(false);
      } catch (error) {
        setError(error.response?.data?.detail || 'Failed to load dashboard data');
        setLoading(false);
      }
    };

    fetchData();
  }, [navigate]);

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

  const totalUsers = users.length;
  const totalClasses = classes.length;
  const totalAdmins = users.filter((user) => (user.role || '').toString().toUpperCase() === 'ADMIN').length;
  const totalTeachers = users.filter((user) => (user.role || '').toString().toUpperCase() === 'TEACHER').length;
  const totalStudents = users.filter((user) => (user.role || '').toString().toUpperCase() === 'STUDENT').length;
  const activeClasses = classes.filter((class_) => (class_.status || '').toString().toLowerCase() === 'active').length;
  const archivedClasses = classes.filter((class_) => (class_.status || '').toString().toLowerCase() === 'archived').length;

  const filteredUsers = users.filter((user) => {
    const query = userQuery.trim().toLowerCase();
    if (!query) return true;
    return (
      (user.username || '').toLowerCase().includes(query) ||
      (user.email || '').toLowerCase().includes(query) ||
      (user.role || '').toString().toLowerCase().includes(query)
    );
  });

  const recentUsers = [...users]
    .sort((a, b) => {
      const aTime = a.created_at ? new Date(a.created_at).getTime() : 0;
      const bTime = b.created_at ? new Date(b.created_at).getTime() : 0;
      return bTime - aTime;
    })
    .slice(0, 5);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-16 w-16 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="text-red-500">Error: {error}</div>
      </div>
    );
  }

  return (
    <div className={`min-h-screen transition-all duration-500 ${darkMode ? 'bg-gradient-to-r from-slate-800 to-gray-950 text-gray-200' : 'bg-gradient-to-r from-indigo-100 to-pink-100 text-gray-900'}`}>
      {/* Navbar */}
      <Navbar 
      userInfo={userInfo}
      onSignOut={handleSignOut}
      darkMode={darkMode}
      logo="./logo.png"
      />
      <div className="container mx-auto px-4 py-8">
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between mb-8">
          <div>
            <h1 className="text-3xl font-bold">Admin Dashboard</h1>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              Manage users, classes, and platform activity from one place.
            </p>
          </div>
          <div className="text-sm text-gray-500 dark:text-gray-400">
            Last updated: {lastUpdated ? lastUpdated.toLocaleString() : '—'}
          </div>
        </div>

        {/* Overview Cards */}
        <section className="mb-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {[
            { label: 'Total Users', value: totalUsers, accent: 'bg-blue-500/10 text-blue-600 dark:text-blue-300' },
            { label: 'Total Classes', value: totalClasses, accent: 'bg-indigo-500/10 text-indigo-600 dark:text-indigo-300' },
            { label: 'Active Classes', value: activeClasses, accent: 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-300' },
            { label: 'Admins', value: totalAdmins, accent: 'bg-rose-500/10 text-rose-600 dark:text-rose-300' },
          ].map((card) => (
            <div
              key={card.label}
              className={`rounded-2xl p-5 shadow-md ${darkMode ? 'bg-gray-800' : 'bg-white'}`}
            >
              <div className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${card.accent}`}>
                {card.label}
              </div>
              <div className="mt-3 text-3xl font-bold">{card.value}</div>
            </div>
          ))}
        </section>

        {/* Insights + Quick Actions */}
        <section className="mb-10 grid gap-6 lg:grid-cols-3">
          <div className={`rounded-2xl p-6 shadow-md ${darkMode ? 'bg-gray-800' : 'bg-white'} lg:col-span-2`}>
            <h2 className="text-xl font-semibold mb-4">Role Breakdown</h2>
            <div className="space-y-4">
              {[
                { label: 'Students', value: totalStudents, color: 'bg-blue-500' },
                { label: 'Teachers', value: totalTeachers, color: 'bg-purple-500' },
                { label: 'Admins', value: totalAdmins, color: 'bg-rose-500' },
              ].map((item) => (
                <div key={item.label}>
                  <div className="flex items-center justify-between text-sm mb-2">
                    <span>{item.label}</span>
                    <span className="text-gray-500 dark:text-gray-400">{item.value}</span>
                  </div>
                  <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-gray-700">
                    <div
                      className={`h-2 rounded-full ${item.color}`}
                      style={{ width: totalUsers ? `${Math.round((item.value / totalUsers) * 100)}%` : '0%' }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className={`rounded-2xl p-6 shadow-md ${darkMode ? 'bg-gray-800' : 'bg-white'}`}>
            <h2 className="text-xl font-semibold mb-4">Quick Actions</h2>
            <div className="space-y-3">
              <button
                className={`w-full rounded-xl px-4 py-3 text-left font-medium shadow-sm transition-all ${
                  darkMode ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-100 hover:bg-gray-200'
                }`}
                onClick={() => document.getElementById('admin-users-section')?.scrollIntoView({ behavior: 'smooth' })}
              >
                Manage Users
              </button>
              <button
                className={`w-full rounded-xl px-4 py-3 text-left font-medium shadow-sm transition-all ${
                  darkMode ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-100 hover:bg-gray-200'
                }`}
                onClick={() => document.getElementById('admin-classes-section')?.scrollIntoView({ behavior: 'smooth' })}
              >
                Review Classes
              </button>
              <button
                className={`w-full rounded-xl px-4 py-3 text-left font-medium shadow-sm transition-all ${
                  darkMode ? 'bg-gray-700 hover:bg-gray-600' : 'bg-gray-100 hover:bg-gray-200'
                }`}
                onClick={() => navigate('/admin-dashboard')}
              >
                View Reports
              </button>
            </div>
            <div className="mt-6 text-sm text-gray-500 dark:text-gray-400">
              Archived classes: {archivedClasses}
            </div>
          </div>
        </section>

        {/* Recent Users */}
        <section className="mb-10">
          <div className={`rounded-2xl p-6 shadow-md ${darkMode ? 'bg-gray-800' : 'bg-white'}`}>
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-semibold">Recent Signups</h2>
              <span className="text-sm text-gray-500 dark:text-gray-400">Latest 5 users</span>
            </div>
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {recentUsers.map((user) => (
                <div
                  key={user.id}
                  className={`rounded-xl border p-4 ${darkMode ? 'border-gray-700 bg-gray-900/40' : 'border-gray-200 bg-white'}`}
                >
                  <div className="font-semibold">{user.username}</div>
                  <div className="text-sm text-gray-500 dark:text-gray-400">{user.email}</div>
                  <div className="text-xs text-gray-400 mt-2">
                    Role: {(user.role || '').toString().toUpperCase()}
                  </div>
                </div>
              ))}
              {recentUsers.length === 0 && (
                <div className="text-sm text-gray-500 dark:text-gray-400">No recent signups yet.</div>
              )}
            </div>
          </div>
        </section>

        {/* Users Section */}
        <section id="admin-users-section" className="mb-8">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between mb-4">
            <h2 className="text-2xl font-semibold">Users</h2>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={userQuery}
                onChange={(event) => setUserQuery(event.target.value)}
                placeholder="Search users"
                className={`rounded-lg border px-3 py-2 text-sm ${
                  darkMode ? 'bg-gray-700 border-gray-600 text-gray-100' : 'bg-white border-gray-200 text-gray-800'
                }`}
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {filteredUsers.map((user) => (
              <motion.div
                key={user.id}
                whileHover={{ scale: 1.02 }}
                className={`p-4 rounded-lg shadow-md ${
                  darkMode ? 'bg-gray-800' : 'bg-white'
                }`}
              >
                <h3 className="font-semibold">{user.username}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  {user.email}
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Role: {user.role}
                </p>
              </motion.div>
            ))}
            {filteredUsers.length === 0 && (
              <div className="text-sm text-gray-500 dark:text-gray-400">No users match this search.</div>
            )}
          </div>
        </section>

        {/* Classes Section */}
        <section id="admin-classes-section">
          <h2 className="text-2xl font-semibold mb-4">Classes</h2>
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {classes.map((class_) => (
              <motion.div
                key={class_.id}
                whileHover={{ scale: 1.02 }}
                className={`p-4 rounded-lg shadow-md ${
                  darkMode ? 'bg-gray-800' : 'bg-white'
                }`}
              >
                <h3 className="font-semibold">{class_.name}</h3>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Code: {class_.access_code}
                </p>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  Students: {class_.student_count}
                </p>
              </motion.div>
            ))}
          </div>
        </section>
      </div>
      <Footer darkMode={darkMode} />
    </div>
  );
};

export default AdminDashboard; 