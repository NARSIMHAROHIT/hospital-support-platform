
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import './Profile.css'

export default function Profile() {
  const [profile, setProfile] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()

    async function loadProfile() {
      try {
        const response = await fetch('/my/profile', {
          credentials: 'include',
          signal: controller.signal,
        })

        if (response.status === 401) {
          throw new Error(
            'Your session has expired. Please log in again.'
          )
        }

        if (!response.ok) {
          throw new Error('Unable to load your profile.')
        }

        const data = await response.json()

        if (!controller.signal.aborted) {
          setProfile(data)
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

    loadProfile()

    return () => controller.abort()
  }, [])

  if (loading) {
    return (
      <main className="profile-page">
        <p>Loading your profile...</p>
      </main>
    )
  }

  if (error) {
    return (
      <main className="profile-page">
        <h1>My Profile</h1>
        <p role="alert" className="profile-error">
          {error}
        </p>
        <Link to="/login">Go to Login</Link>
      </main>
    )
  }

  if (!profile) {
    return (
      <main className="profile-page">
        <p>No profile information found.</p>
      </main>
    )
  }

  const initials = (profile.full_name || 'Patient')
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() || '')
    .join('')

  return (
    <main className="profile-page">
      <header className="profile-heading">
        <h1>My Profile</h1>
        <p>
          View your personal information stored in
          the hospital system.
        </p>
      </header>

      <section className="profile-card">
        <div className="profile-identity">
          <div className="profile-avatar" aria-hidden="true">
            {initials}
          </div>

          <div>
            <h2>{profile.full_name}</h2>
            <p>Patient Account</p>
          </div>
        </div>

        <div className="profile-information">
          <div className="profile-field">
            <span>Full Name</span>
            <strong>{profile.full_name}</strong>
          </div>

          <div className="profile-field">
            <span>Email Address</span>
            <strong>{profile.email}</strong>
          </div>

          <div className="profile-field">
            <span>Phone Number</span>
            <strong>
              {profile.phone || 'Not provided'}
            </strong>
          </div>

          <div className="profile-field">
            <span>Patient ID</span>
            <strong className="profile-id">
              {profile.patient_id}
            </strong>
          </div>
        </div>
      </section>

      <section className="profile-actions">
        <h2>Account Information</h2>

        <p>
          Your profile information is retrieved securely
          from the hospital backend.
        </p>

        <p>
          Editing personal details is not enabled yet.
          We'll add a protected update workflow later.
        </p>

        <Link to="/dashboard">
          Back to Dashboard
        </Link>
      </section>
    </main>
  )
}
