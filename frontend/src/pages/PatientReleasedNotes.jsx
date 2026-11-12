
import { useEffect, useState } from 'react'
import './PatientReleasedNotes.css'

const BASE = '/clinical/note-sharing'

async function getJson(url) {
  const response = await fetch(url, {
    credentials: 'include',
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

function formatDate(value) {
  if (!value) return 'Not available'

  const date = new Date(value)

  return Number.isNaN(date.getTime())
    ? 'Not available'
    : date.toLocaleString()
}

export default function PatientReleasedNotes() {
  const [notes, setNotes] = useState([])
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingNote, setLoadingNote] = useState(false)
  const [error, setError] = useState('')

  async function refreshNotes() {
    setLoading(true)
    setError('')

    try {
      const result = await getJson(`${BASE}/my-notes`)
      setNotes(result.notes || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let active = true

    getJson(`${BASE}/my-notes`)
      .then((result) => {
        if (active) setNotes(result.notes || [])
      })
      .catch((err) => {
        if (active) setError(err.message)
      })
      .finally(() => {
        if (active) setLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  async function openNote(noteId) {
    setLoadingNote(true)
    setError('')
    setSelected(null)

    try {
      const detail = await getJson(
        `${BASE}/my-notes/${encodeURIComponent(noteId)}`
      )

      setSelected(detail)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingNote(false)
    }
  }

  async function backToList() {
    setSelected(null)
    await refreshNotes()
  }

  return (
    <section className="patient-released-notes">
      <div className="patient-released-heading">
        <div>
          <h2>Doctor Consultation Notes</h2>
          <p>
            Signed notes your doctors have released
            to your patient account.
          </p>
        </div>

        {!selected && (
          <button
            type="button"
            onClick={refreshNotes}
            disabled={loading}
            className="patient-note-secondary"
          >
            Refresh Notes
          </button>
        )}
      </div>

      {error && (
        <p className="patient-note-error" role="alert">
          {error}
        </p>
      )}

      {loading && <p>Loading doctor notes...</p>}

      {!loading && !selected && (
        <>
          {notes.length === 0 && !error && (
            <p className="patient-note-empty">
              No doctor notes have been released
              to you yet.
            </p>
          )}

          <div className="patient-note-list">
            {notes.map((note) => (
              <button
                type="button"
                key={note.note_id}
                className="patient-note-card"
                onClick={() => openNote(note.note_id)}
                disabled={loadingNote}
              >
                <span>
                  <strong>{note.doctor_name}</strong>
                  <small>
                    Signed: {formatDate(note.signed_at)}
                  </small>
                  <small>
                    Released: {formatDate(note.released_at)}
                  </small>
                </span>

                <span className="patient-note-view">
                  View Note
                </span>
              </button>
            ))}
          </div>
        </>
      )}

      {loadingNote && (
        <p>Loading consultation note...</p>
      )}

      {selected && !loadingNote && (
        <article className="patient-note-detail">
          <button
            type="button"
            className="patient-note-secondary"
            onClick={backToList}
          >
            Back to Notes
          </button>

          <h3>Consultation Note</h3>

          <p>
            <strong>Doctor:</strong>{' '}
            {selected.doctor_name}
          </p>

          <p>
            <strong>Signed:</strong>{' '}
            {formatDate(selected.signed_at)}
          </p>

          <p>
            <strong>Released:</strong>{' '}
            {formatDate(selected.released_at)}
          </p>

          <div className="patient-note-field">
            <h4>Observations</h4>
            <p>
              {selected.observations ||
                'Not provided'}
            </p>
          </div>

          <div className="patient-note-field">
            <h4>Assessment</h4>
            <p>
              {selected.assessment ||
                'Not provided'}
            </p>
          </div>

          <div className="patient-note-field">
            <h4>Treatment Plan</h4>
            <p>
              {selected.treatment_plan ||
                'Not provided'}
            </p>
          </div>

          {selected.addenda?.length > 0 && (
            <div className="patient-note-addenda">
              <h4>Corrections & Addenda</h4>

              {selected.addenda.map((addendum, index) => (
                <div
                  key={`${addendum.created_at}-${index}`}
                  className="patient-note-field"
                >
                  <small>
                    {formatDate(addendum.created_at)}
                  </small>

                  <p>{addendum.content}</p>
                </div>
              ))}
            </div>
          )}

          <p className="patient-note-disclaimer">
            This is a fictional educational demonstration.
            It is not a source of medical advice.
          </p>
        </article>
      )}
    </section>
  )
}
