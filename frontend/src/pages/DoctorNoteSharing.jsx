
import { useEffect, useState } from 'react'

const BASE = '/clinical/note-sharing'

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
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

export default function DoctorNoteSharing({
  noteId,
}) {
  const [released, setReleased] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const encodedNoteId = encodeURIComponent(noteId)

  useEffect(() => {
    let active = true

    setLoading(true)
    setError('')
    setMessage('')

    requestJson(`${BASE}/doctor/${encodedNoteId}`)
      .then((data) => {
        if (active) {
          setReleased(data.released === true)
        }
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
  }, [encodedNoteId])

  async function changeRelease() {
    const action = released ? 'revoke' : 'release'

    const confirmed = window.confirm(
      released
        ? 'Remove this note from the patient portal?'
        : 'Release this signed note to the patient?'
    )

    if (!confirmed) return

    setBusy(true)
    setError('')
    setMessage('')

    try {
      const result = await requestJson(
        `${BASE}/doctor/${encodedNoteId}/${action}`,
        { method: 'POST' }
      )

      setReleased(result.released === true)

      setMessage(
        result.released
          ? 'The patient can now view this note.'
          : 'Patient access to this note has been revoked.'
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="clinical-note-sharing">
      <h4>Patient Access</h4>

      {loading ? (
        <p>Checking release status...</p>
      ) : (
        <>
          <p>
            Status:{' '}
            <strong>
              {released
                ? 'Released to patient'
                : 'Not released'}
            </strong>
          </p>

          <p className="clinical-notes-info">
            Signed notes stay private until you
            explicitly release them.
          </p>

          <button
            type="button"
            className={
              released
                ? 'clinical-notes-secondary'
                : 'clinical-notes-sign'
            }
            onClick={changeRelease}
            disabled={busy}
          >
            {busy
              ? 'Updating...'
              : released
                ? 'Revoke Patient Access'
                : 'Release to Patient'}
          </button>
        </>
      )}

      {error && (
        <p className="clinical-notes-error" role="alert">
          {error}
        </p>
      )}

      {message && (
        <p className="clinical-notes-success" role="status">
          {message}
        </p>
      )}
    </section>
  )
}
