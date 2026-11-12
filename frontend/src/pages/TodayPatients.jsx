
import { useMemo, useState } from 'react'
import './TodayPatients.css'

function dateKey(value) {
  const date = new Date(value)

  if (Number.isNaN(date.getTime())) return ''

  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, '0'),
    String(date.getDate()).padStart(2, '0'),
  ].join('-')
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

export default function TodayPatients({
  appointments = [],
  onUpdated,
}) {
  const [busyId, setBusyId] = useState(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [filter, setFilter] = useState('all')

  const today = dateKey(new Date())

  const todayAppointments = useMemo(
    () => appointments
      .filter(appointment =>
        dateKey(appointment.starts_at) === today
      )
      .sort((a, b) =>
        new Date(a.starts_at) - new Date(b.starts_at)
      ),
    [appointments, today]
  )

  const completed = todayAppointments.filter(
    appointment => appointment.status === 'completed'
  )

  const scheduled = todayAppointments.filter(
    appointment => appointment.status === 'booked'
  )

  const visible = todayAppointments.filter(
    appointment =>
      filter === 'all' || appointment.status === filter
  )

  async function completeVisit(appointment) {
    if (!window.confirm(
      `Mark ${appointment.patient_name}'s visit as completed?`
    )) {
      return
    }

    setBusyId(appointment.appointment_id)
    setError('')
    setMessage('')

    try {
      const response = await fetch(
        `/doctor/appointments/${encodeURIComponent(
          appointment.appointment_id
        )}/complete`,
        {
          method: 'PATCH',
          credentials: 'include',
        }
      )

      const data = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(
          typeof data.detail === 'string'
            ? data.detail
            : 'Unable to complete the visit'
        )
      }

      await onUpdated()

      setMessage('Visit marked as completed.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyId(null)
    }
  }

  return (
    <section className="today-patients">
      <div className="today-patients-heading">
        <h2>Today's Patients</h2>
        <p>
          {new Date().toLocaleDateString(undefined, {
            dateStyle: 'full',
          })}
        </p>
      </div>

      <div className="today-patients-stats">
        <article>
          <span>Total Visits</span>
          <strong>{todayAppointments.length}</strong>
        </article>

        <article>
          <span>Scheduled</span>
          <strong>{scheduled.length}</strong>
        </article>

        <article>
          <span>Completed</span>
          <strong>{completed.length}</strong>
        </article>
      </div>

      {error && (
        <p className="today-patients-error" role="alert">
          {error}
        </p>
      )}

      {message && (
        <p className="today-patients-success" role="status">
          {message}
        </p>
      )}

      <div className="today-patients-filters">
        {['all', 'booked', 'completed', 'cancelled'].map(
          status => (
            <button
              key={status}
              type="button"
              className={filter === status ? 'active' : ''}
              onClick={() => setFilter(status)}
            >
              {status}
            </button>
          )
        )}
      </div>

      <div className="today-patients-grid">
        {visible.length === 0 ? (
          <p>No patient visits in this category today.</p>
        ) : (
          visible.map(appointment => {
            const canComplete =
              appointment.status === 'booked' &&
              new Date(appointment.starts_at) <= new Date()

            return (
              <article
                key={appointment.appointment_id}
                className="today-patient-card"
              >
                <div className="today-patient-card-heading">
                  <h3>{appointment.patient_name}</h3>

                  <span className={
                    `today-patient-status ${appointment.status}`
                  }>
                    {appointment.status}
                  </span>
                </div>

                <p>
                  <strong>Time:</strong>{' '}
                  {formatTime(appointment.starts_at)}
                  {' – '}
                  {formatTime(appointment.ends_at)}
                </p>

                {canComplete && (
                  <button
                    type="button"
                    className="today-complete-button"
                    disabled={busyId !== null}
                    onClick={() => completeVisit(appointment)}
                  >
                    {busyId === appointment.appointment_id
                      ? 'Updating...'
                      : 'Mark Visit Completed'}
                  </button>
                )}

                {appointment.status === 'booked' &&
                  !canComplete && (
                    <p className="today-patient-note">
                      This appointment has not started yet.
                    </p>
                  )}
              </article>
            )
          })
        )}
      </div>

      <p className="today-patient-note">
        Completion records an administrative visit status.
        It does not certify clinical treatment.
      </p>
    </section>
  )
}
