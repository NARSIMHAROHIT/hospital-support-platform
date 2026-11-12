
import { useEffect, useRef, useState } from 'react'
import './DoctorClinicalNotes.css'
import DoctorNoteSharing from './DoctorNoteSharing'

const BASE = '/doctor/clinical-notes'
const AUTOSAVE_DELAY = 1500

const EMPTY_NOTE = {
  observations: '',
  assessment: '',
  treatment_plan: '',
}

async function apiJson(path, options = {}) {
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

function normalizeNote(note) {
  return {
    observations: (note.observations || '').trim(),
    assessment: (note.assessment || '').trim(),
    treatment_plan: (note.treatment_plan || '').trim(),
  }
}

function sameNote(a, b) {
  return JSON.stringify(normalizeNote(a)) ===
    JSON.stringify(normalizeNote(b))
}

function formatDate(value) {
  if (!value) return 'Not available'

  const date = new Date(value)

  return Number.isNaN(date.getTime())
    ? 'Not available'
    : date.toLocaleString()
}

function availableForNewNote(appointments, notes) {
  return appointments.filter(
    (appointment) =>
      !notes.some(
        (note) =>
          note.appointment_id === appointment.appointment_id &&
          note.is_author === true
      )
  )
}

function AppointmentDetails({ note }) {
  return (
    <div className="clinical-notes-appointment-details">
      <h4>Appointment Information</h4>

      <p>
        <strong>Doctor:</strong>{' '}
        {note.doctor_name || 'Not available'}
      </p>

      <p>
        <strong>Appointment Date:</strong>{' '}
        {formatDate(note.appointment_starts_at)}
      </p>

      {note.appointment_ends_at && (
        <p>
          <strong>Appointment End:</strong>{' '}
          {formatDate(note.appointment_ends_at)}
        </p>
      )}

      <p>
        <strong>Appointment Status:</strong>{' '}
        {note.appointment_status || 'Not available'}
      </p>

      <p>
        <strong>Note Created:</strong>{' '}
        {formatDate(note.created_at)}
      </p>

      {note.signed_at && (
        <p>
          <strong>Note Signed:</strong>{' '}
          {formatDate(note.signed_at)}
        </p>
      )}
    </div>
  )
}

export default function DoctorClinicalNotes({ patientId }) {
  const [appointments, setAppointments] = useState([])
  const [notes, setNotes] = useState([])
  const [appointmentId, setAppointmentId] = useState('')

  const [selectedNote, setSelectedNote] = useState(null)

  const [form, setForm] = useState({ ...EMPTY_NOTE })
  const [savedForm, setSavedForm] = useState({ ...EMPTY_NOTE })

  const [addenda, setAddenda] = useState([])
  const [addendumText, setAddendumText] = useState('')

  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [autoSaving, setAutoSaving] = useState(false)

  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const currentNoteIdRef = useRef(null)
  const failedAutosaveRef = useRef('')

  const encodedPatient = encodeURIComponent(patientId)

  const isOwnDraft =
    selectedNote?.status === 'draft' &&
    selectedNote?.is_author === true

  const isSignedNote = selectedNote?.status === 'signed'

  const canEdit = !selectedNote || isOwnDraft

  const isDirty = selectedNote
    ? isOwnDraft && !sameNote(form, savedForm)
    : Object.values(normalizeNote(form)).some(Boolean)

  const availableAppointments = availableForNewNote(
    appointments,
    notes
  )

  const canShareWithPatient =
    isSignedNote &&
    selectedNote?.is_author === true

  // --------------------------------------------------------
  // INITIAL DATA LOADING
  // --------------------------------------------------------

  useEffect(() => {
    let active = true

    currentNoteIdRef.current = null
    failedAutosaveRef.current = ''

    setLoading(true)
    setError('')
    setMessage('')
    setSelectedNote(null)
    setForm({ ...EMPTY_NOTE })
    setSavedForm({ ...EMPTY_NOTE })
    setAddenda([])
    setAddendumText('')
    setAutoSaving(false)

    Promise.all([
      apiJson(
        `${BASE}/patient/${encodedPatient}/appointments`
      ),
      apiJson(
        `${BASE}/patient/${encodedPatient}`
      ),
    ])
      .then(([appointmentData, noteData]) => {
        if (!active) return

        const available = appointmentData.appointments || []
        const existingNotes = noteData.notes || []

        setAppointments(available)
        setNotes(existingNotes)

        const unused = availableForNewNote(
          available,
          existingNotes
        )

        setAppointmentId(unused[0]?.appointment_id || '')
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
  }, [encodedPatient])

  async function refreshNotes() {
    const result = await apiJson(
      `${BASE}/patient/${encodedPatient}`
    )

    setNotes(result.notes || [])
  }

  // --------------------------------------------------------
  // UNSAVED CHANGES PROTECTION
  // --------------------------------------------------------

  useEffect(() => {
    if (!isDirty && !autoSaving) return

    function beforeUnload(event) {
      event.preventDefault()
      event.returnValue = ''
    }

    window.addEventListener('beforeunload', beforeUnload)

    return () => {
      window.removeEventListener(
        'beforeunload',
        beforeUnload
      )
    }
  }, [isDirty, autoSaving])

  function canLeaveCurrentNote() {
    if (busy || autoSaving) {
      setError('A save is still in progress.')
      return false
    }

    if (!isDirty) return true

    return window.confirm(
      'You have unsaved changes. Discard them and continue?'
    )
  }

  // --------------------------------------------------------
  // AUTOSAVE EXISTING DRAFT
  // --------------------------------------------------------

  useEffect(() => {
    if (
      !isOwnDraft ||
      !isDirty ||
      busy ||
      autoSaving
    ) {
      return
    }

    const payload = normalizeNote(form)

    if (!payload.observations) return

    const noteId = selectedNote.note_id

    const fingerprint = JSON.stringify({
      note_id: noteId,
      ...payload,
    })

    if (failedAutosaveRef.current === fingerprint) {
      return
    }

    const timer = setTimeout(async () => {
      setAutoSaving(true)
      setError('')

      try {
        const saved = await apiJson(
          `${BASE}/${encodeURIComponent(noteId)}`,
          {
            method: 'PATCH',
            headers: {
              'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
          }
        )

        if (currentNoteIdRef.current !== noteId) {
          return
        }

        failedAutosaveRef.current = ''
        setSavedForm(payload)

        setSelectedNote((current) =>
          current?.note_id === noteId
            ? { ...current, ...saved, is_author: true }
            : current
        )
      } catch (err) {
        failedAutosaveRef.current = fingerprint

        if (currentNoteIdRef.current === noteId) {
          setError(
            `Autosave failed: ${err.message}. Use Save Draft to retry.`
          )
        }
      } finally {
        if (currentNoteIdRef.current === noteId) {
          setAutoSaving(false)
        }
      }
    }, AUTOSAVE_DELAY)

    return () => clearTimeout(timer)
  }, [
    selectedNote?.note_id,
    selectedNote?.status,
    selectedNote?.is_author,
    isOwnDraft,
    isDirty,
    form,
    busy,
    autoSaving,
  ])

  // --------------------------------------------------------
  // START NEW NOTE
  // --------------------------------------------------------

  function startNewNote() {
    if (!canLeaveCurrentNote()) return

    currentNoteIdRef.current = null
    failedAutosaveRef.current = ''

    setSelectedNote(null)
    setForm({ ...EMPTY_NOTE })
    setSavedForm({ ...EMPTY_NOTE })
    setAddenda([])
    setAddendumText('')
    setError('')
    setMessage('')

    const unused = availableForNewNote(
      appointments,
      notes
    )

    setAppointmentId(unused[0]?.appointment_id || '')
  }

  // --------------------------------------------------------
  // OPEN PREVIOUS NOTE
  // --------------------------------------------------------

  async function openNote(note) {
    if (selectedNote?.note_id === note.note_id) return
    if (!canLeaveCurrentNote()) return

    setBusy(true)
    setError('')
    setMessage('')

    try {
      const detail = await apiJson(
        `${BASE}/${encodeURIComponent(note.note_id)}`
      )

      currentNoteIdRef.current = detail.note_id
      failedAutosaveRef.current = ''

      const loadedForm = {
        observations: detail.observations || '',
        assessment: detail.assessment || '',
        treatment_plan: detail.treatment_plan || '',
      }

      setSelectedNote({
        ...detail,
        is_author: note.is_author === true,
      })

      setForm(loadedForm)
      setSavedForm(normalizeNote(loadedForm))
      setAddenda(detail.addenda || [])
      setAddendumText('')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function updateField(field, value) {
    setForm((current) => ({
      ...current,
      [field]: value,
    }))

    setError('')
  }

  // --------------------------------------------------------
  // SAVE DRAFT
  // --------------------------------------------------------

  async function saveNote(event) {
    event.preventDefault()

    if (busy || autoSaving) return

    if (selectedNote && !isOwnDraft) {
      setError('This note cannot be edited.')
      return
    }

    const payload = normalizeNote(form)

    if (!payload.observations) {
      setError('Observations are required.')
      return
    }

    if (!selectedNote && !appointmentId) {
      setError('Select an appointment.')
      return
    }

    setBusy(true)
    setError('')
    setMessage('')

    const editingDraft = isOwnDraft

    const path = editingDraft
      ? `${BASE}/${encodeURIComponent(selectedNote.note_id)}`
      : BASE

    const body = editingDraft
      ? payload
      : {
          patient_id: patientId,
          appointment_id: appointmentId,
          ...payload,
        }

    try {
      const saved = await apiJson(path, {
        method: editingDraft ? 'PATCH' : 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      })

      currentNoteIdRef.current = saved.note_id
      failedAutosaveRef.current = ''

      setSelectedNote({
        ...saved,
        is_author: true,
      })

      setForm(payload)
      setSavedForm(payload)

      await refreshNotes()

      setMessage('Clinical note saved successfully.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // --------------------------------------------------------
  // SIGN NOTE
  // --------------------------------------------------------

  async function signNote() {
    if (!isOwnDraft || busy || autoSaving) return

    if (isDirty) {
      setError('Save changes before signing.')
      return
    }

    if (!window.confirm(
      'Sign this note? The original cannot be edited afterward.'
    )) {
      return
    }

    setBusy(true)
    setError('')
    setMessage('')

    try {
      const signed = await apiJson(
        `${BASE}/${encodeURIComponent(selectedNote.note_id)}/sign`,
        { method: 'POST' }
      )

      setSelectedNote((current) => ({
        ...current,
        ...signed,
        is_author: true,
      }))

      setSavedForm(normalizeNote(signed))

      await refreshNotes()

      setMessage(
        'Note signed. You can now release it to the patient.'
      )
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  // --------------------------------------------------------
  // ADD CORRECTION
  // --------------------------------------------------------

  async function addCorrection(event) {
    event.preventDefault()

    if (
      !isSignedNote ||
      selectedNote.is_author !== true ||
      !addendumText.trim() ||
      busy
    ) {
      return
    }

    setBusy(true)
    setError('')
    setMessage('')

    try {
      const noteId = encodeURIComponent(
        selectedNote.note_id
      )

      await apiJson(`${BASE}/${noteId}/addenda`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: addendumText.trim(),
        }),
      })

      const updated = await apiJson(`${BASE}/${noteId}`)

      setSelectedNote({
        ...updated,
        is_author: true,
      })

      setAddenda(updated.addenda || [])
      setAddendumText('')

      setMessage('Correction added successfully.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="clinical-notes-section">
      <div className="clinical-notes-heading">
        <div>
          <h3>Clinical Notes</h3>

          <p>
            Consultation history, drafts, signed records,
            and patient sharing.
          </p>
        </div>

        <button
          type="button"
          className="clinical-notes-secondary"
          onClick={startNewNote}
          disabled={loading || busy || autoSaving}
        >
          + New Note
        </button>
      </div>

      {loading && <p>Loading clinical notes...</p>}

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

      {!loading && (
        <>

          {/* PREVIOUS NOTES WITH APPOINTMENT HISTORY */}
          <div className="clinical-notes-existing">
            <h4>Previous Consultation Notes</h4>

            {notes.length === 0 ? (
              <p>No clinical notes recorded yet.</p>
            ) : (
              <div className="clinical-notes-list">
                {notes.map((note) => (
                  <button
                    key={note.note_id}
                    type="button"
                    disabled={busy || autoSaving}
                    className={
                      selectedNote?.note_id === note.note_id
                        ? 'clinical-note-item selected'
                        : 'clinical-note-item'
                    }
                    onClick={() => openNote(note)}
                  >
                    <span>
                      <strong>
                        {note.appointment_starts_at
                          ? formatDate(note.appointment_starts_at)
                          : formatDate(note.created_at)}
                      </strong>

                      <small>
                        {note.doctor_name || 'Doctor not available'}
                      </small>

                      <small>
                        Appointment: {
                          note.appointment_status || 'Unknown'
                        }
                      </small>

                      <small>
                        Created: {formatDate(note.created_at)}
                      </small>

                      <small>
                        {note.is_author
                          ? 'Written by you'
                          : 'Another authorized doctor'}
                      </small>
                    </span>

                    <span
                      className={
                        `clinical-note-status ${note.status}`
                      }
                    >
                      {note.status}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {!selectedNote &&
            availableAppointments.length === 0 && (
              <p className="clinical-notes-info">
                No available appointment for a new note.
                Open an existing note above.
              </p>
            )}

          {/* NOTE EDITOR */}
          {(selectedNote ||
            availableAppointments.length > 0) && (
            <form
              onSubmit={saveNote}
              className="clinical-note-form"
            >
              <h4>
                {selectedNote
                  ? isSignedNote
                    ? 'Signed Clinical Note'
                    : 'Edit Draft Note'
                  : 'New Consultation Note'}
              </h4>

              {selectedNote && (
                <>
                  <p className="clinical-notes-info">
                    Note status:{' '}
                    <strong>{selectedNote.status}</strong>
                    {' · '}
                    {selectedNote.is_author
                      ? 'Written by you'
                      : 'Read-only'}
                  </p>

                  <AppointmentDetails note={selectedNote} />
                </>
              )}

              {!selectedNote && (
                <label>
                  Appointment

                  <select
                    required
                    value={appointmentId}
                    disabled={busy}
                    onChange={(event) =>
                      setAppointmentId(event.target.value)
                    }
                  >
                    <option value="" disabled>
                      Select an appointment
                    </option>

                    {availableAppointments.map((appointment) => (
                      <option
                        key={appointment.appointment_id}
                        value={appointment.appointment_id}
                      >
                        {formatDate(appointment.starts_at)}
                        {' — '}
                        {appointment.status}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <label>
                Observations

                <textarea
                  required
                  rows={4}
                  maxLength={5000}
                  value={form.observations}
                  readOnly={!canEdit || busy}
                  onChange={(event) =>
                    updateField('observations', event.target.value)
                  }
                  placeholder="Record observations..."
                />
              </label>

              <label>
                Assessment

                <textarea
                  rows={3}
                  maxLength={5000}
                  value={form.assessment}
                  readOnly={!canEdit || busy}
                  onChange={(event) =>
                    updateField('assessment', event.target.value)
                  }
                  placeholder="Assessment..."
                />
              </label>

              <label>
                Treatment Plan

                <textarea
                  rows={3}
                  maxLength={5000}
                  value={form.treatment_plan}
                  readOnly={!canEdit || busy}
                  onChange={(event) =>
                    updateField('treatment_plan', event.target.value)
                  }
                  placeholder="Follow-up plan..."
                />
              </label>

              {isOwnDraft && (
                <p className="clinical-notes-info" role="status">
                  {autoSaving
                    ? 'Saving draft automatically...'
                    : isDirty
                      ? 'Unsaved changes · Autosave pending'
                      : 'All changes saved'}
                </p>
              )}

              {!selectedNote && isDirty && (
                <p className="clinical-notes-info">
                  Save Draft once to create the note.
                  Later edits will save automatically.
                </p>
              )}

              {canEdit && (
                <div className="clinical-notes-actions">
                  <button
                    type="submit"
                    className="clinical-notes-primary"
                    disabled={busy || autoSaving}
                  >
                    {busy ? 'Saving...' : 'Save Draft'}
                  </button>

                  {isOwnDraft && (
                    <button
                      type="button"
                      className="clinical-notes-sign"
                      disabled={
                        busy ||
                        autoSaving ||
                        isDirty
                      }
                      onClick={signNote}
                    >
                      Sign Note
                    </button>
                  )}
                </div>
              )}
            </form>
          )}

          {/* CORRECTIONS */}
          {isSignedNote && (
            <div className="clinical-notes-addenda">
              <h4>Corrections & Addenda</h4>

              {addenda.length === 0 && (
                <p>No corrections have been added.</p>
              )}

              {addenda.map((addendum) => (
                <article
                  key={addendum.addendum_id}
                  className="clinical-note-addendum"
                >
                  <small>
                    {formatDate(addendum.created_at)}
                  </small>

                  <p>{addendum.content}</p>
                </article>
              ))}

              {selectedNote.is_author && (
                <form onSubmit={addCorrection}>
                  <label>
                    Add a correction

                    <textarea
                      required
                      rows={3}
                      maxLength={5000}
                      value={addendumText}
                      onChange={(event) =>
                        setAddendumText(event.target.value)
                      }
                      placeholder="Describe the correction..."
                    />
                  </label>

                  <button
                    type="submit"
                    className="clinical-notes-primary"
                    disabled={busy || !addendumText.trim()}
                  >
                    Add Signed-Note Correction
                  </button>
                </form>
              )}
            </div>
          )}

          {/* RELEASE / REVOKE PATIENT ACCESS */}
          {canShareWithPatient && (
            <DoctorNoteSharing
              key={selectedNote.note_id}
              noteId={selectedNote.note_id}
            />
          )}

        </>
      )}
    </section>
  )
}
