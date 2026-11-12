
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import './Dashboard.css'

const quickActions = [
  {
    icon: '🩺',
    title: 'Find Doctors',
    description: 'Search specialists and book appointments.',
    path: '/doctors',
    button: 'Find Doctors',
  },
  {
    icon: '📅',
    title: 'My Appointments',
    description: 'View, cancel, or reschedule appointments.',
    path: '/appointments',
    button: 'Manage Appointments',
  },
  {
    icon: '💬',
    title: 'Support Tickets',
    description: 'Submit questions and track support requests.',
    path: '/support',
    button: 'Open Support',
  },
  {
    icon: '👤',
    title: 'My Profile',
    description: 'View your patient account information.',
    path: '/profile',
    button: 'View Profile',
  },
]

export default function Dashboard() {
  const [profile, setProfile] = useState(null)
  const [appointments, setAppointments] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadDashboard() {
      try {
        const options = {
          credentials: 'include',
          signal: controller.signal,
        }

        const [profileResponse, appointmentResponse] =
          await Promise.all([
            fetch('/my/profile', options),
            fetch('/my/appointments', options),
          ])

        if (!profileResponse.ok || !appointmentResponse.ok) {
          throw new Error('Unable to load your dashboard.')
        }

        const profileData = await profileResponse.json()
        const appointmentData = await appointmentResponse.json()

        if (!Array.isArray(appointmentData)) {
          throw new Error('Unexpected appointment response.')
        }

        if (!controller.signal.aborted) {
          setProfile(profileData)
          setAppointments(appointmentData)
        }
      } catch (err) {
        if (err.name !== 'AbortError') {
          setError(err.message)
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    loadDashboard()

    return () => controller.abort()
  }, [])

  const booked = appointments.filter(
    (appointment) => appointment.status === 'booked'
  )

  if (loading) {
    return (
      <main className="dashboard">
        <p>Loading your dashboard...</p>
      </main>
    )
  }

  if (error) {
    return (
      <main className="dashboard">
        <p role="alert">{error}</p>
      </main>
    )
  }

  return (
    <main className="dashboard">
      <header className="dashboard-header">
        <div>
          <h1>Welcome, {profile?.full_name || 'Patient'}</h1>
          <p>Your personal hospital dashboard</p>
        </div>
      </header>

      <section className="dashboard-stats">
        <article className="stat-card">
          <h2>{appointments.length}</h2>
          <p>Total Appointments</p>
        </article>

        <article className="stat-card">
          <h2>{booked.length}</h2>
          <p>Booked Appointments</p>
        </article>

        <article className="stat-card">
          <h2>Active</h2>
          <p>Patient Account</p>
        </article>
      </section>

      <h2>Quick Access</h2>

      <section className="dashboard-actions">
        {quickActions.map((action) => (
          <article className="action-card" key={action.path}>
            <span aria-hidden="true">{action.icon}</span>
            <h3>{action.title}</h3>
            <p>{action.description}</p>

            <Link to={action.path}>
              {action.button}
            </Link>
          </article>
        ))}
      </section>

      <section className="dashboard-section">
        <div className="dashboard-section-header">
          <h2>Upcoming Appointments</h2>
          <Link to="/appointments">View All</Link>
        </div>

        {booked.length === 0 ? (
          <p>No booked appointments.</p>
        ) : (
          <div className="appointment-list">
            {booked.slice(0, 3).map((appointment) => (
              <article
                key={appointment.appointment_id}
                className="appointment-card"
              >
                <h3>
                  {appointment.doctor_name ||
                    'Doctor Appointment'}
                </h3>
                <p>Status: {appointment.status}</p>
                <p>
                  Date:{' '}
                  {appointment.starts_at
                    ? new Date(
                        appointment.starts_at
                      ).toLocaleString()
                    : 'Not available'}
                </p>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="dashboard-section">
        <div className="dashboard-section-header">
          <h2>My Profile</h2>
          <Link to="/profile">View Profile</Link>
        </div>

        <p>
          <strong>Name:</strong> {profile?.full_name}
        </p>
        <p>
          <strong>Email:</strong> {profile?.email}
        </p>
      </section>
    </main>
  )
}
