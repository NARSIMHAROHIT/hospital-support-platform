
import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import './RescheduleAppointment.css'

function localDateKey(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''

  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')

  return `${year}-${month}-${day}`
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
}

export default function RescheduleAppointment() {
  const { appointmentId } = useParams()

  const [appointment, setAppointment] = useState(null)
  const [slots, setSlots] = useState([])
  const [date, setDate] = useState('')
  const [selectedSlotId, setSelectedSlotId] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    const controller = new AbortController()

    async function loadData() {
      try {
        const appointmentsResponse = await fetch(
          '/my/appointments',
          {
            credentials: 'include',
            signal: controller.signal,
          }
        )

        if (!appointmentsResponse.ok) {
          throw new Error('Unable to load appointments')
        }

        const appointments = await appointmentsResponse.json()
        const current = appointments.find(
          (item) => item.appointment_id === appointmentId
        )

        if (!current) {
          throw new Error('Appointment not found')
        }

        if (current.status !== 'booked') {
          throw new Error(
            'Only booked appointments can be rescheduled'
          )
        }

        if (!current.doctor_id || !current.slot_id) {
          throw new Error(
            'Doctor or slot information is missing. Check the backend response.'
          )
        }

        setAppointment(current)

        const slotsResponse = await fetch(
          `/doctors/${encodeURIComponent(current.doctor_id)}/slots`,
          {
            credentials: 'include',
            signal: controller.signal,
          }
        )

        if (!slotsResponse.ok) {
          throw new Error('Unable to load doctor availability')
        }

        const result = await slotsResponse.json()

        const availableSlots = Array.isArray(result)
          ? result
          : Array.isArray(result.slots)
            ? result.slots
            : []

        setSlots(availableSlots)
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

    loadData()
    return () => controller.abort()
  }, [appointmentId])

  const availableSlots = useMemo(() => {
    if (!appointment) return []

    return slots
      .filter((slot) => {
        if (!slot.slot_id || !slot.starts_at || !slot.ends_at) {
          return false
        }

        if (slot.slot_id === appointment.slot_id) {
          return false
        }

        if (
          slot.is_available === false ||
          slot.available === false ||
          slot.status === 'booked' ||
          slot.status === 'unavailable'
        ) {
          return false
        }

        return new Date(slot.starts_at).getTime() > Date.now()
      })
      .sort(
        (a, b) =>
          new Date(a.starts_at) - new Date(b.starts_at)
      )
  }, [slots, appointment])

  const availableDates = useMemo(
    () => [...new Set(
      availableSlots.map((slot) => localDateKey(slot.starts_at))
    )].filter(Boolean),
    [availableSlots]
  )

  const slotsForDate = availableSlots.filter(
    (slot) => localDateKey(slot.starts_at) === date
  )

  async function submitRequest(event) {
    event.preventDefault()

    if (!selectedSlotId || submitting) return

    setSubmitting(true)
    setError('')

    try {
      const response = await fetch(
        `/my/appointments/${encodeURIComponent(appointmentId)}/reschedule-requests`,
        {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            requested_slot_id: selectedSlotId,
          }),
        }
      )

      const result = await response.json().catch(() => ({}))

      if (!response.ok) {
        throw new Error(
          typeof result.detail === 'string'
            ? result.detail
            : 'Unable to submit reschedule request'
        )
      }

      setSuccess(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <main className="reschedule-page">
        <p>Loading appointment information...</p>
      </main>
    )
  }

  if (success) {
    return (
      <main className="reschedule-page">
        <section className="reschedule-card">
          <h1>Request Submitted</h1>
          <p className="reschedule-success">
            Your reschedule request is pending doctor approval.
          </p>
          <p>
            Your original appointment remains booked.
            No appointment time has changed yet.
          </p>
          <Link to="/appointments">
            Back to My Appointments
          </Link>
        </section>
      </main>
    )
  }

  return (
    <main className="reschedule-page">
      <div className="reschedule-header">
        <Link to="/appointments">← My Appointments</Link>
        <h1>Request Reschedule</h1>
        <p>Choose a new time and send it for doctor review.</p>
      </div>

      {error && (
        <p role="alert" className="reschedule-error">
          {error}
        </p>
      )}

      {appointment && (
        <section className="reschedule-card">
          <h2>Current Appointment</h2>
          <p><strong>Doctor:</strong> {appointment.doctor}</p>
          <p>
            <strong>Department:</strong>{' '}
            {appointment.specialization}
          </p>
          <p>
            <strong>Current Time:</strong>{' '}
            {new Date(appointment.starts_at).toLocaleString()}
          </p>
          <p className="reschedule-note">
            This appointment stays booked while your
            request is being reviewed.
          </p>
        </section>
      )}

      {appointment && (
        <form
          onSubmit={submitRequest}
          className="reschedule-card"
        >
          <h2>Choose a New Appointment</h2>

          <label htmlFor="reschedule-date">
            Available Dates
          </label>

          <select
            id="reschedule-date"
            value={date}
            onChange={(event) => {
              setDate(event.target.value)
              setSelectedSlotId('')
            }}
          >
            <option value="">Select a date</option>
            {availableDates.map((day) => (
              <option key={day} value={day}>
                {new Date(`${day}T12:00:00`).toLocaleDateString(
                  undefined,
                  { dateStyle: 'full' }
                )}
              </option>
            ))}
          </select>

          {availableDates.length === 0 && (
            <p>No future slots are currently available.</p>
          )}

          {date && (
            <>
              <h3>Available Times</h3>

              {slotsForDate.length === 0 && (
                <p>No available times for this date.</p>
              )}

              <div className="reschedule-slot-grid">
                {slotsForDate.map((slot) => (
                  <button
                    key={slot.slot_id}
                    type="button"
                    aria-pressed={
                      selectedSlotId === slot.slot_id
                    }
                    className={
                      selectedSlotId === slot.slot_id
                        ? 'reschedule-slot selected'
                        : 'reschedule-slot'
                    }
                    onClick={() =>
                      setSelectedSlotId(slot.slot_id)
                    }
                  >
                    <strong>
                      {formatTime(slot.starts_at)}
                    </strong>
                    <span>
                      Until {formatTime(slot.ends_at)}
                    </span>
                  </button>
                ))}
              </div>
            </>
          )}

          <button
            type="submit"
            className="reschedule-submit"
            disabled={!selectedSlotId || submitting}
          >
            {submitting
              ? 'Submitting...'
              : 'Submit Reschedule Request'}
          </button>
        </form>
      )}
    </main>
  )
}
