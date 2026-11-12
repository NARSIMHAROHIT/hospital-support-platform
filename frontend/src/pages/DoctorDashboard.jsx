
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import './DoctorDashboard.css'
import TodayPatients from './TodayPatients'
import DoctorPatients from './DoctorPatients'

const TABS = [
  ['overview', 'Overview'],
  ['today', "Today's Appointments"],
  ['patients', 'My Patients'],
  ['appointments', 'All Appointments'],
  ['schedule', 'My Schedule'],
  ['requests', 'Reschedule Requests'],
]

function dayKey(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')

  return `${year}-${month}-${day}`
}

function formatDate(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Unavailable'

  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function formatTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Invalid time'

  return date.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

function minutesToTime(totalMinutes) {
  const hour = String(Math.floor(totalMinutes / 60)).padStart(2, '0')
  const minute = String(totalMinutes % 60).padStart(2, '0')
  return `${hour}:${minute}`
}

async function getJson(path, options = {}) {
  const response = await fetch(path, {
    credentials: 'include',
    ...options,
  })

  const data = await response.json().catch(() => ({}))

  if (!response.ok) {
    throw new Error(
      typeof data.detail === 'string'
        ? data.detail
        : `Request failed (${response.status})`
    )
  }

  return data
}

function AppointmentCard({ appointment }) {
  return (
    <article className="doctor-item-card">
      <div className="doctor-item-heading">
        <h3>{appointment.patient_name}</h3>
        <span className={`doctor-status status-${appointment.status}`}>
          {appointment.status}
        </span>
      </div>
      <p><strong>Starts:</strong> {formatDate(appointment.starts_at)}</p>
      <p><strong>Ends:</strong> {formatTime(appointment.ends_at)}</p>
    </article>
  )
}

export default function DoctorDashboard() {
  const navigate = useNavigate()

  const [doctor, setDoctor] = useState(null)
  const [appointments, setAppointments] = useState([])
  const [slots, setSlots] = useState([])
  const [requests, setRequests] = useState([])

  const [activeTab, setActiveTab] = useState('overview')
  const [appointmentFilter, setAppointmentFilter] = useState('booked')
  const [requestFilter, setRequestFilter] = useState('pending')

  const [selectedDate, setSelectedDate] = useState(
    () => dayKey(new Date())
  )

  const [startTime, setStartTime] = useState('09:00')
  const [endTime, setEndTime] = useState('09:30')

  const [loading, setLoading] = useState(true)
  const [busyRequestId, setBusyRequestId] = useState(null)
  const [busySlotId, setBusySlotId] = useState(null)
  const [addingSlot, setAddingSlot] = useState(false)
  const [loggingOut, setLoggingOut] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const loadDashboard = useCallback(async (signal) => {
    const [doctorData, appointmentData, slotData, requestData] =
      await Promise.all([
        getJson('/doctor/me', { signal }),
        getJson('/doctor/appointments', { signal }),
        getJson('/doctor/schedule', { signal }),
        getJson('/doctor/reschedule-requests', { signal }),
      ])

    if (signal?.aborted) return

    setDoctor(doctorData)
    setAppointments(appointmentData)
    setSlots(slotData)
    setRequests(requestData)
  }, [])

  useEffect(() => {
    const controller = new AbortController()

    async function initialize() {
      try {
        await loadDashboard(controller.signal)
      } catch (err) {
        if (err.name !== 'AbortError' && !controller.signal.aborted) {
          setError(err.message)
        }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }

    initialize()
    return () => controller.abort()
  }, [loadDashboard])

  async function refresh() {
    await loadDashboard()
  }

  async function addSlot(event) {
    event.preventDefault()
    setError('')
    setMessage('')

    if (!selectedDate || !startTime || !endTime) {
      setError('Choose a date, start time, and end time.')
      return
    }

    const start = new Date(`${selectedDate}T${startTime}:00`)
    const end = new Date(`${selectedDate}T${endTime}:00`)

    if (
      Number.isNaN(start.getTime()) ||
      Number.isNaN(end.getTime())
    ) {
      setError('Enter a valid appointment time.')
      return
    }

    if (start <= new Date()) {
      setError('You cannot create an appointment slot in the past.')
      return
    }

    const minutes = (end - start) / 60000

    if (minutes < 15 || minutes > 120) {
      setError('Slot duration must be between 15 and 120 minutes.')
      return
    }

    setAddingSlot(true)

    try {
      await getJson('/doctor/schedule/slots', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          starts_at: start.toISOString(),
          ends_at: end.toISOString(),
        }),
      })

      await refresh()
      setMessage('New appointment slot added successfully.')

      // Prepare the next 30-minute slot automatically.
      const nextStart = end.getHours() * 60 + end.getMinutes()

      if (nextStart + 30 < 24 * 60) {
        setStartTime(minutesToTime(nextStart))
        setEndTime(minutesToTime(nextStart + 30))
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setAddingSlot(false)
    }
  }

  async function blockSlot(slot) {
    if (slot.availability !== 'available') return

    if (!window.confirm(
      `Block ${formatTime(slot.starts_at)} on ${formatDate(slot.starts_at)}? Patients will no longer be able to book it.`
    )) {
      return
    }

    setBusySlotId(slot.slot_id)
    setError('')
    setMessage('')

    try {
      await getJson(
        `/doctor/schedule/slots/${encodeURIComponent(slot.slot_id)}/block`,
        { method: 'PATCH' }
      )

      await refresh()
      setMessage('Appointment slot blocked successfully.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusySlotId(null)
    }
  }

  async function decideRequest(request, action) {
    if (!window.confirm(
      `Do you want to ${action} this request for ${request.patient_name}?`
    )) {
      return
    }

    setBusyRequestId(request.request_id)
    setError('')
    setMessage('')

    try {
      await getJson(
        `/doctor/reschedule-requests/${encodeURIComponent(request.request_id)}/${action}`,
        { method: 'PATCH' }
      )

      await refresh()

      setMessage(
        action === 'approve'
          ? 'Request approved. The appointment has been updated.'
          : 'Request rejected. The original appointment is unchanged.'
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setBusyRequestId(null)
    }
  }

  async function logout() {
    setLoggingOut(true)
    setError('')

    try {
      await getJson('/auth/logout', { method: 'POST' })
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err.message)
      setLoggingOut(false)
    }
  }

  const today = dayKey(new Date())

  const booked = appointments.filter(a => a.status === 'booked')

  const todayAppointments = appointments.filter(
    a => dayKey(a.starts_at) === today && a.status === 'booked'
  )

  const pending = requests.filter(r => r.status === 'pending')
  const todaySlots = slots.filter(s => dayKey(s.starts_at) === today)

  const selectedSlots = slots
    .filter(s => dayKey(s.starts_at) === selectedDate)
    .sort((a, b) => new Date(a.starts_at) - new Date(b.starts_at))

  const visibleAppointments = appointments.filter(
    a => appointmentFilter === 'all' || a.status === appointmentFilter
  )

  const visibleRequests = requests.filter(
    r => requestFilter === 'all' || r.status === requestFilter
  )

  const scheduleDates = useMemo(
    () => [...new Set(slots.map(s => dayKey(s.starts_at)))]
      .filter(Boolean)
      .sort(),
    [slots]
  )

  const nextScheduledDate = scheduleDates.find(
    date => date >= today && slots.some(
      slot => dayKey(slot.starts_at) === date &&
        new Date(slot.ends_at) > new Date()
    )
  )

  const scheduleCounts = {
    available: selectedSlots.filter(
      s => s.availability === 'available'
    ).length,
    occupied: selectedSlots.filter(
      s => s.availability === 'occupied'
    ).length,
    blocked: selectedSlots.filter(
      s => s.availability === 'blocked'
    ).length,
  }

  function RequestCard({ request }) {
    const isPending = request.status === 'pending'

    return (
      <article className="doctor-item-card">
        <div className="doctor-item-heading">
          <h3>{request.patient_name}</h3>
          <span className={`doctor-status status-${request.status}`}>
            {request.status}
          </span>
        </div>

        <p>
          <strong>Current appointment:</strong>{' '}
          {formatDate(request.original_starts_at)}
        </p>
        <p>
          <strong>Requested time:</strong>{' '}
          {formatDate(request.requested_starts_at)}
        </p>

        {isPending && (
          <div className="doctor-actions">
            <button
              type="button"
              className="doctor-approve"
              disabled={busyRequestId !== null}
              onClick={() => decideRequest(request, 'approve')}
            >
              {busyRequestId === request.request_id
                ? 'Processing...'
                : 'Approve'}
            </button>
            <button
              type="button"
              className="doctor-reject"
              disabled={busyRequestId !== null}
              onClick={() => decideRequest(request, 'reject')}
            >
              Reject
            </button>
          </div>
        )}
      </article>
    )
  }

  return (
    <main className="doctor-page">
      <header className="doctor-topbar">
        <div>
          <h1>Doctor Portal</h1>
          <p>Hospital Patient Support Platform</p>
        </div>

        <button
          type="button"
          className="doctor-logout"
          disabled={loggingOut}
          onClick={logout}
        >
          {loggingOut ? 'Signing out...' : 'Log Out'}
        </button>
      </header>

      {doctor && (
        <section className="doctor-welcome">
          <h2>Welcome, {doctor.full_name}</h2>
          <p>{doctor.department} · {doctor.email}</p>
        </section>
      )}

      <nav className="doctor-tabs" aria-label="Doctor sections">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={
              activeTab === id
                ? 'doctor-tab active'
                : 'doctor-tab'
            }
            aria-current={activeTab === id ? 'page' : undefined}
            onClick={() => setActiveTab(id)}
          >
            {label}
            {id === 'requests' && pending.length > 0
              ? ` (${pending.length})`
              : ''}
          </button>
        ))}
      </nav>

      {error && <p role="alert" className="doctor-error">{error}</p>}
      {message && <p role="status" className="doctor-success">{message}</p>}

      {loading ? (
        <p>Loading doctor information...</p>
      ) : (
        <>
          {activeTab === 'overview' && (
            <>
              <section className="doctor-stats">
                {[
                  ['Today’s Appointments', todayAppointments.length, 'today'],
                  ['Today’s Slots', todaySlots.length, 'schedule'],
                  ['Booked Appointments', booked.length, 'appointments'],
                  ['Pending Requests', pending.length, 'requests'],
                ].map(([label, count, destination]) => (
                  <button
                    type="button"
                    key={label}
                    className="doctor-stat-card"
                    onClick={() => setActiveTab(destination)}
                  >
                    <span>{label}</span>
                    <strong>{count}</strong>
                    <small>View details</small>
                  </button>
                ))}
              </section>

              <section className="doctor-section">
                <h2>Upcoming Appointments</h2>
                <div className="doctor-content-grid">
                  {booked
                    .filter(a => new Date(a.ends_at) >= new Date())
                    .sort(
                      (a, b) =>
                        new Date(a.starts_at) - new Date(b.starts_at)
                    )
                    .slice(0, 5)
                    .map(a => (
                      <AppointmentCard
                        key={a.appointment_id}
                        appointment={a}
                      />
                    ))}
                </div>
              </section>
            </>
          )}

          {activeTab === 'today' && (
            <TodayPatients
              appointments={appointments}
              onUpdated={refresh}
            />
          )}

          {activeTab === 'patients' && (
            <DoctorPatients />
          )}

          {activeTab === 'appointments' && (
            <section className="doctor-section">
              <h2>All Appointments</h2>

              <div className="doctor-filters">
                {['booked', 'completed', 'cancelled', 'all'].map(status => (
                  <button
                    key={status}
                    type="button"
                    className={
                      appointmentFilter === status
                        ? 'doctor-filter active'
                        : 'doctor-filter'
                    }
                    onClick={() => setAppointmentFilter(status)}
                  >
                    {status}
                  </button>
                ))}
              </div>

              <div className="doctor-content-grid">
                {visibleAppointments.length === 0
                  ? <p>No appointments in this category.</p>
                  : visibleAppointments.map(a => (
                    <AppointmentCard
                      key={a.appointment_id}
                      appointment={a}
                    />
                  ))}
              </div>
            </section>
          )}

          {activeTab === 'schedule' && (
            <section className="doctor-section">
              <div className="doctor-section-heading">
                <div>
                  <h2>My Schedule</h2>
                  <p className="doctor-subtitle">
                    Add availability or block an unbooked future slot.
                  </p>
                </div>
                <button
                  type="button"
                  className="doctor-refresh"
                  onClick={() => refresh().catch(err => setError(err.message))}
                >
                  Refresh
                </button>
              </div>

              <div className="doctor-schedule-toolbar">
                <div>
                  <label className="doctor-date-label" htmlFor="doctor-date">
                    Choose a date
                  </label>
                  <input
                    id="doctor-date"
                    type="date"
                    value={selectedDate}
                    onChange={e => setSelectedDate(e.target.value)}
                  />
                </div>

                {nextScheduledDate && (
                  <button
                    type="button"
                    className="doctor-next-date"
                    onClick={() => setSelectedDate(nextScheduledDate)}
                  >
                    Next scheduled date
                  </button>
                )}
              </div>

              <div className="doctor-schedule-stats">
                <span>Available: {scheduleCounts.available}</span>
                <span>Booked: {scheduleCounts.occupied}</span>
                <span>Blocked: {scheduleCounts.blocked}</span>
              </div>

              <form className="doctor-add-slot-form" onSubmit={addSlot}>
                <h3>Add Appointment Slot</h3>

                <div className="doctor-form-grid">
                  <label>
                    Start time
                    <input
                      type="time"
                      required
                      value={startTime}
                      onChange={e => setStartTime(e.target.value)}
                    />
                  </label>

                  <label>
                    End time
                    <input
                      type="time"
                      required
                      value={endTime}
                      onChange={e => setEndTime(e.target.value)}
                    />
                  </label>

                  <button
                    type="submit"
                    className="doctor-approve"
                    disabled={addingSlot}
                  >
                    {addingSlot ? 'Adding...' : '+ Add Slot'}
                  </button>
                </div>

                <p className="doctor-subtitle">
                  Times use your device's local timezone.
                  Slots must be 15–120 minutes and cannot overlap.
                </p>
              </form>

              <h3>Slots for selected date</h3>

              <div className="doctor-slot-grid">
                {selectedSlots.length === 0 ? (
                  <p>No slots for this date. Add one using the form above.</p>
                ) : selectedSlots.map(slot => {
                  const canBlock =
                    slot.availability === 'available' &&
                    new Date(slot.starts_at) > new Date()

                  return (
                    <article
                      key={slot.slot_id}
                      className="doctor-slot-card"
                    >
                      <strong>{formatTime(slot.starts_at)}</strong>
                      <span>Until {formatTime(slot.ends_at)}</span>

                      <span
                        className={
                          `doctor-status status-${slot.availability}`
                        }
                      >
                        {slot.availability === 'occupied'
                          ? 'Booked'
                          : slot.availability}
                      </span>

                      {canBlock && (
                        <button
                          type="button"
                          className="doctor-block-button"
                          disabled={busySlotId !== null}
                          onClick={() => blockSlot(slot)}
                        >
                          {busySlotId === slot.slot_id
                            ? 'Blocking...'
                            : 'Block Slot'}
                        </button>
                      )}
                    </article>
                  )
                })}
              </div>
            </section>
          )}

          {activeTab === 'requests' && (
            <section className="doctor-section">
              <h2>Reschedule Requests</h2>

              <div className="doctor-filters">
                {['pending', 'approved', 'rejected', 'cancelled', 'all']
                  .map(status => (
                    <button
                      key={status}
                      type="button"
                      className={
                        requestFilter === status
                          ? 'doctor-filter active'
                          : 'doctor-filter'
                      }
                      onClick={() => setRequestFilter(status)}
                    >
                      {status}
                    </button>
                  ))}
              </div>

              <div className="doctor-content-grid">
                {visibleRequests.length === 0
                  ? <p>No reschedule requests in this category.</p>
                  : visibleRequests.map(r => (
                    <RequestCard key={r.request_id} request={r} />
                  ))}
              </div>
            </section>
          )}
        </>
      )}
    </main>
  )
}
