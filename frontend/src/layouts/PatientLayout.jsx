
import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import './PatientLayout.css'


const links = [
  { path: '/dashboard', label: 'Dashboard', icon: '🏠' },
  { path: '/doctors', label: 'Find Doctors', icon: '🩺' },
  { path: '/appointments', label: 'My Appointments', icon: '📅' },
  { path: '/support', label: 'Support Tickets', icon: '💬' },
  { path: '/medical-records', label: 'Medical Records', icon: '📁' },
  { path: '/ai-assistant', label: 'AI Assistant', icon: '🤖' },
  { path: '/profile', label: 'My Profile', icon: '👤' },
]


export default function PatientLayout() {
  const navigate = useNavigate()
  const [loggingOut, setLoggingOut] = useState(false)
  const [error, setError] = useState('')

  async function handleLogout() {
    if (loggingOut) return

    setLoggingOut(true)
    setError('')

    try {
      const response = await fetch('/auth/logout', {
        method: 'POST',
        credentials: 'include',
      })

      if (!response.ok) {
        throw new Error('Logout failed. Please try again.')
      }

      navigate('/login', { replace: true })
    } catch (err) {
      setError(err.message)
    } finally {
      setLoggingOut(false)
    }
  }

  return (
    <div className="patient-layout">
      <aside className="patient-sidebar">
        <div className="patient-brand">
          <span aria-hidden="true">🏥</span>
          <strong>Hospital Portal</strong>
        </div>

        <nav aria-label="Patient navigation">
          {links.map((link) => (
            <NavLink
              key={link.path}
              to={link.path}
              className={({ isActive }) =>
                `patient-nav-link ${isActive ? 'active' : ''}`
              }
            >
              <span aria-hidden="true">{link.icon}</span>
              {link.label}
            </NavLink>
          ))}
        </nav>

        <button
          type="button"
          className="patient-logout"
          onClick={handleLogout}
          disabled={loggingOut}
        >
          {loggingOut ? 'Logging out...' : '🚪 Logout'}
        </button>

        {error && (
          <p className="patient-logout-error" role="alert">
            {error}
          </p>
        )}
      </aside>

      <div className="patient-main">
        <header className="patient-topbar">
          <strong>Patient Portal</strong>
          <span>Hospital Support Platform</span>
        </header>

        <div className="patient-content">
          <Outlet />
        </div>
      </div>
    </div>
  )
}
