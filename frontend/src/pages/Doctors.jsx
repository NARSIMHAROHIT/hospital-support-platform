
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import './Doctors.css'

function formatLocalDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatDateTime(value) {
  return new Date(value).toLocaleString([], {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function getErrorMessage(detail, status) {
  if (typeof detail === 'string') {
    return `HTTP ${status}: ${detail}`
  }

  if (Array.isArray(detail)) {
    return `HTTP ${status}: ${detail
      .map((item) => {
        const field = Array.isArray(item.loc)
          ? item.loc.join('.')
          : 'request'

        return `${field}: ${item.msg || 'Invalid value'}`
      })
      .join('; ')}`
  }

  return `HTTP ${status}: Request failed`
}

export default function Doctors() {
  const [doctors, setDoctors] = useState([])
  const [search, setSearch] = useState('')

  const [selectedDoctor, setSelectedDoctor] = useState(null)
  const [selectedDate, setSelectedDate] = useState(
    () => formatLocalDate(new Date())
  )
  const [slots, setSlots] = useState([])
  const [selectedSlot, setSelectedSlot] = useState(null)

  const [loading, setLoading] = useState(true)
  const [slotsLoading, setSlotsLoading] = useState(false)
  const [booking, setBooking] = useState(false)

  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')

  const requestId = useRef(0)
  const bookingLock = useRef(false)

  // ============================================
  // LOAD DOCTORS
  // ============================================

  useEffect(() => {
    const controller = new AbortController()

    async function loadDoctors() {
      try {
        const response = await fetch('/doctors', {
          credentials: 'include',
          signal: controller.signal,
        })

        const data = await response.json()

        if (!response.ok) {
          throw new Error(
            getErrorMessage(data.detail, response.status)
          )
        }

        if (!Array.isArray(data)) {
          throw new Error('Invalid doctor directory response')
        }

        if (!controller.signal.aborted) {
          setDoctors(data)
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

    loadDoctors()

    return () => controller.abort()
  }, [])

  // ============================================
  // LOAD DOCTOR AVAILABILITY
  // ============================================

  async function loadSlots(doctor, preserveSuccess = false) {
    if (!doctor) return

    const currentRequest = ++requestId.current

    setSlotsLoading(true)
    setSlots([])
    setSelectedSlot(null)
    setError('')

    if (!preserveSuccess) {
      setSuccess('')
    }

    try {
      const response = await fetch(
        `/doctors/${encodeURIComponent(doctor.doctor_id)}/slots`,
        { credentials: 'include' }
      )

      const data = await response.json()

      if (!response.ok) {
        throw new Error(
          getErrorMessage(data.detail, response.status)
        )
      }

      if (!Array.isArray(data)) {
        throw new Error('Invalid availability response')
      }

      if (requestId.current === currentRequest) {
        setSlots(data)
      }
    } catch (err) {
      if (requestId.current === currentRequest) {
        setError(err.message)
      }
    } finally {
      if (requestId.current === currentRequest) {
        setSlotsLoading(false)
      }
    }
  }

  function selectDoctor(doctor) {
    if (bookingLock.current) return

    setSelectedDoctor(doctor)
    setSelectedDate(formatLocalDate(new Date()))
    loadSlots(doctor)
  }

  // ============================================
  // FILTER AVAILABLE SLOTS BY DATE
  // ============================================

  const availableSlots = slots
    .filter((slot) => {
      const start = new Date(slot.starts_at)

      return (
        !Number.isNaN(start.getTime()) &&
        start.getTime() > Date.now() &&
        formatLocalDate(start) === selectedDate
      )
    })
    .sort(
      (a, b) =>
        new Date(a.starts_at).getTime() -
        new Date(b.starts_at).getTime()
    )

  const datesWithSlots = new Set(
    slots
      .filter(
        (slot) =>
          new Date(slot.starts_at).getTime() > Date.now()
      )
      .map((slot) =>
        formatLocalDate(new Date(slot.starts_at))
      )
  )

  const filteredDoctors = doctors.filter((doctor) => {
    const searchableText = [
      doctor.full_name,
      doctor.specialization,
      doctor.department,
    ]
      .filter(Boolean)
      .join(' ')
      .toLowerCase()

    return searchableText.includes(
      search.trim().toLowerCase()
    )
  })

  // ============================================
  // CONFIRM APPOINTMENT
  // ============================================

  async function confirmBooking() {
    if (!selectedSlot || !selectedDoctor) return
    if (bookingLock.current) return

    bookingLock.current = true
    setBooking(true)
    setError('')
    setSuccess('')

    try {
      const response = await fetch('/my/appointments', {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
        doctor_id: selectedDoctor.doctor_id,
        slot_id: selectedSlot.slot_id,
        }),
      })

      const result = await response.json()

      if (!response.ok) {
        throw new Error(
          getErrorMessage(result.detail, response.status)
        )
      }

      setSuccess(
        `Appointment confirmed with ${selectedDoctor.full_name} ` +
        `for ${formatDateTime(selectedSlot.starts_at)}.`
      )

      setSelectedSlot(null)

      // Refresh availability so the booked slot disappears
      await loadSlots(selectedDoctor, true)
    } catch (err) {
      setError(err.message || 'Unable to book appointment')

      // Refresh even after failure because another
      // patient may have booked the slot.
      if (selectedDoctor) {
        try {
          const response = await fetch(
            `/doctors/${encodeURIComponent(
              selectedDoctor.doctor_id
            )}/slots`,
            { credentials: 'include' }
          )

          if (response.ok) {
            const data = await response.json()
            if (Array.isArray(data)) {
              setSlots(data)
              setSelectedSlot(null)
            }
          }
        } catch {
          // Preserve the original booking error.
        }
      }
    } finally {
      bookingLock.current = false
      setBooking(false)
    }
  }

  // ============================================
  // RENDER
  // ============================================

  return (
    <main className="doctors-page">
      <header className="doctors-heading">
        <h1>Find Doctors</h1>
        <p>
          Search by doctor, specialization, or department
          and choose an appointment date.
        </p>
      </header>

      <div className="doctor-search">
        <input
          type="search"
          placeholder="Search doctors or departments..."
          aria-label="Search doctors"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
      </div>

      {error && (
        <div className="doctor-error" role="alert">
          {error}
        </div>
      )}

      {success && (
        <div className="booking-success" role="status">
          <strong>{success}</strong>
          <p>
            <Link to="/appointments">
              View My Appointments
            </Link>
          </p>
        </div>
      )}

      {/* DOCTOR DIRECTORY */}

      {loading ? (
        <p>Loading doctors...</p>
      ) : filteredDoctors.length === 0 ? (
        <p>No doctors found in the hospital directory.</p>
      ) : (
        <section className="doctors-grid">
          {filteredDoctors.map((doctor) => (
            <article
              className="doctor-card"
              key={doctor.doctor_id}
            >
              <div className="doctor-avatar" aria-hidden="true">
                🩺
              </div>

              <h2>{doctor.full_name}</h2>

              <p className="doctor-specialization">
                {doctor.specialization}
              </p>

              <p className="doctor-department">
                Department: {doctor.department}
              </p>

              <button
                type="button"
                disabled={booking}
                onClick={() => selectDoctor(doctor)}
              >
                View Availability
              </button>
            </article>
          ))}
        </section>
      )}

      {/* CALENDAR AND AVAILABLE SLOTS */}

      {selectedDoctor && (
        <section className="doctor-slots">
          <div className="slots-heading">
            <div>
              <h2>{selectedDoctor.full_name}</h2>
              <p>
                {selectedDoctor.specialization}
                {' · '}
                {selectedDoctor.department}
              </p>
            </div>

            <button
              type="button"
              className="close-slots"
              disabled={booking}
              onClick={() => {
                requestId.current += 1
                setSelectedDoctor(null)
                setSelectedSlot(null)
                setSlots([])
              }}
            >
              Close
            </button>
          </div>

          <div className="appointment-calendar">
            <label htmlFor="appointment-date">
              <strong>Choose Appointment Date</strong>
            </label>

            <input
              id="appointment-date"
              type="date"
              value={selectedDate}
              min={formatLocalDate(new Date())}
              disabled={booking}
              onChange={(event) => {
                setSelectedDate(event.target.value)
                setSelectedSlot(null)
              }}
            />

            <p>
              Dates with available slots: {datesWithSlots.size}
            </p>
          </div>

          <h3>Available Time Slots</h3>

          {slotsLoading ? (
            <p>Checking appointment availability...</p>
          ) : availableSlots.length === 0 ? (
            <div className="no-slots">
              <p>
                No available appointment times for this date.
              </p>
              <p>
                Choose another date or select another doctor.
              </p>
              <button
                type="button"
                onClick={() => loadSlots(selectedDoctor)}
                disabled={booking}
              >
                Refresh Availability
              </button>
            </div>
          ) : (
            <div className="slots-grid">
              {availableSlots.map((slot) => (
                <button
                  key={slot.slot_id}
                  type="button"
                  disabled={booking}
                  className={
                    selectedSlot?.slot_id === slot.slot_id
                      ? 'slot-card selected'
                      : 'slot-card'
                  }
                  aria-pressed={
                    selectedSlot?.slot_id === slot.slot_id
                  }
                  onClick={() => {
                    setSelectedSlot(slot)
                    setError('')
                  }}
                >
                  <strong>
                    {formatTime(slot.starts_at)}
                  </strong>

                  <span>
                    {slot.ends_at
                      ? `Until ${formatTime(slot.ends_at)}`
                      : 'Available'}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* BOOKING CONFIRMATION */}

          {selectedSlot && (
            <div className="booking-confirmation">
              <h3>Confirm Appointment</h3>

              <p>
                <strong>Doctor:</strong>{' '}
                {selectedDoctor.full_name}
              </p>

              <p>
                <strong>Department:</strong>{' '}
                {selectedDoctor.department}
              </p>

              <p>
                <strong>Date and Time:</strong>{' '}
                {formatDateTime(selectedSlot.starts_at)}
              </p>

              <p>
                <strong>End Time:</strong>{' '}
                {selectedSlot.ends_at
                  ? formatTime(selectedSlot.ends_at)
                  : 'Not specified'}
              </p>

              <div className="booking-buttons">
                <button
                  type="button"
                  disabled={booking}
                  onClick={confirmBooking}
                >
                  {booking
                    ? 'Confirming...'
                    : 'Confirm Booking'}
                </button>

                <button
                  type="button"
                  disabled={booking}
                  onClick={() => setSelectedSlot(null)}
                >
                  Cancel Selection
                </button>
              </div>
            </div>
          )}
        </section>
      )}
    </main>
  )
}
