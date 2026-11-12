
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import './Appointments.css'

const TABS = [
  { id: 'booked', label: 'Booked' },
  { id: 'cancelled', label: 'Cancelled' },
  { id: 'completed', label: 'Completed' },
]

export default function Appointments() {
  const [appointments, setAppointments] = useState([])
  const [requests, setRequests] = useState([])
  const [activeTab, setActiveTab] = useState('booked')
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  async function loadAppointments(signal) {
    try {
      setLoading(true)
      setError('')

      const [appointmentsResponse, requestsResponse] =
        await Promise.all([
          fetch('/my/appointments', {
            credentials: 'include',
            signal,
          }),
          fetch('/my/reschedule-requests', {
            credentials: 'include',
            signal,
          }),
        ])

      if (!appointmentsResponse.ok) {
        throw new Error('Failed to load appointments')
      }

      if (!requestsResponse.ok) {
        throw new Error('Failed to load reschedule requests')
      }

      const appointmentsData =
        await appointmentsResponse.json()

      const requestsData = await requestsResponse.json()

      if (!signal?.aborted) {
        setAppointments(
          Array.isArray(appointmentsData)
            ? appointmentsData
            : []
        )

        setRequests(
          Array.isArray(requestsData)
            ? requestsData
            : []
        )
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        setError(err.message)
      }
    } finally {
      if (!signal?.aborted) {
        setLoading(false)
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController()

    loadAppointments(controller.signal)

    return () => controller.abort()
  }, [])

  async function cancelAppointment(appointment) {
    const confirmed = window.confirm(
      `Cancel your appointment with ${appointment.doctor}?`
    )

    if (!confirmed) return

    setBusyId(appointment.appointment_id)
    setError('')

    try {
      const response = await fetch(
        `/my/appointments/${encodeURIComponent(
          appointment.appointment_id
        )}/cancel`,
        {
          method: 'PATCH',
          credentials: 'include',
        }
      )

      if (!response.ok) {
        const result = await response.json().catch(() => ({}))

        throw new Error(
          typeof result.detail === 'string'
            ? result.detail
            : 'Unable to cancel appointment'
        )
      }

      await loadAppointments()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  function getLatestRequest(appointmentId) {
    return requests.find(
      (request) => request.appointment_id === appointmentId
    )
  }

  function formatDate(value) {
    if (!value) return 'Date unavailable'

    const date = new Date(value)

    if (Number.isNaN(date.getTime())) {
      return 'Invalid date'
    }

    return date.toLocaleString(undefined, {
      dateStyle: 'full',
      timeStyle: 'short',
    })
  }

  function formatTime(value) {
    if (!value) return 'Unavailable'

    const date = new Date(value)

    if (Number.isNaN(date.getTime())) {
      return 'Invalid time'
    }

    return date.toLocaleTimeString(undefined, {
      hour: 'numeric',
      minute: '2-digit',
    })
  }

  const counts = Object.fromEntries(
    TABS.map((tab) => [
      tab.id,
      appointments.filter(
        (appointment) => appointment.status === tab.id
      ).length,
    ])
  )

  const visibleAppointments = appointments.filter(
    (appointment) => appointment.status === activeTab
  )

  return (
    <main className="appointments-page">
      <header className="appointments-heading">
        <div>
          <h1>My Appointments</h1>
          <p>
            View booked appointments, cancellations,
            and completed visits.
          </p>
        </div>

        <Link
          to="/doctors"
          className="book-appointment-btn"
        >
          + Book Appointment
        </Link>
      </header>

      <div
        className="appointments-tabs"
        role="tablist"
        aria-label="Appointment status"
      >
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={`tab-${tab.id}`}
            aria-selected={activeTab === tab.id}
            aria-controls="appointments-panel"
            className={
              activeTab === tab.id
                ? 'appointment-tab active'
                : 'appointment-tab'
            }
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}

            <span className="appointment-tab-count">
              {counts[tab.id]}
            </span>
          </button>
        ))}
      </div>

      {error && (
        <p className="appointments-error" role="alert">
          {error}
        </p>
      )}

      <section
        id="appointments-panel"
        role="tabpanel"
        aria-labelledby={`tab-${activeTab}`}
        className="appointments-list"
      >
        {loading ? (
          <p>Loading appointments...</p>
        ) : visibleAppointments.length === 0 ? (
          <div className="appointments-empty">
            <h2>No {activeTab} appointments</h2>
            <p>
              Appointments with this status will appear here.
            </p>
          </div>
        ) : (
          visibleAppointments.map((appointment) => {
            const latestRequest = getLatestRequest(
              appointment.appointment_id
            )

            const pendingRequest = requests.find(
              (request) =>
                request.appointment_id ===
                  appointment.appointment_id &&
                request.status === 'pending'
            )

            return (
              <article
                className="appointment-card"
                key={appointment.appointment_id}
              >
                <div className="appointment-card-header">
                  <div>
                    <h2>
                      {appointment.doctor ||
                        appointment.doctor_name ||
                        'Doctor Appointment'}
                    </h2>

                    <p>
                      {appointment.specialization ||
                        appointment.department ||
                        'Hospital Department'}
                    </p>
                  </div>

                  <span
                    className={`appointment-status status-${appointment.status}`}
                  >
                    {appointment.status}
                  </span>
                </div>

                <div className="appointment-card-details">
                  <p>
                    <strong>Date & Time:</strong>{' '}
                    {formatDate(appointment.starts_at)}
                  </p>

                  <p>
                    <strong>Ends:</strong>{' '}
                    {formatTime(appointment.ends_at)}
                  </p>
                </div>

                {pendingRequest && (
                  <div className="reschedule-pending-info">
                    <strong>Reschedule Pending Approval</strong>

                    <p>
                      Requested new time:{' '}
                      {formatDate(
                        pendingRequest.requested_starts_at
                      )}
                    </p>

                    <p>
                      Your original appointment is still booked.
                    </p>
                  </div>
                )}

                {!pendingRequest &&
                  latestRequest?.status === 'rejected' && (
                    <div className="reschedule-rejected-info">
                      Your previous reschedule request was rejected.
                      You can submit another request.
                    </div>
                  )}

                {appointment.status === 'booked' && (
                  <div className="appointment-card-actions">
                    {!pendingRequest && (
                      <Link
                        className="appointment-reschedule-btn"
                        to={`/appointments/${appointment.appointment_id}/reschedule`}
                      >
                        Request Reschedule
                      </Link>
                    )}

                    <button
                      type="button"
                      className="appointment-cancel-btn"
                      disabled={
                        busyId === appointment.appointment_id
                      }
                      onClick={() =>
                        cancelAppointment(appointment)
                      }
                    >
                      {busyId === appointment.appointment_id
                        ? 'Cancelling...'
                        : 'Cancel Appointment'}
                    </button>
                  </div>
                )}
              </article>
            )
          })
        )}
      </section>
    </main>
  )
}
