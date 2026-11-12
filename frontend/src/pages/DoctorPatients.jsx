
import { useEffect, useState } from 'react'
import './DoctorPatients.css'
import DoctorClinicalNotes from './DoctorClinicalNotes'

async function getData(url) {
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

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value) {
  if (!value) return 'Not available'

  const date = new Date(value)

  return Number.isNaN(date.getTime())
    ? 'Not available'
    : date.toLocaleString()
}

export default function DoctorPatients() {
  const [search, setSearch] = useState('')
  const [patients, setPatients] = useState([])
  const [totalPatients, setTotalPatients] = useState(0)

  const [selected, setSelected] = useState(null)
  const [documents, setDocuments] = useState([])
  const [totalDocuments, setTotalDocuments] = useState(0)

  const [loading, setLoading] = useState(true)
  const [loadingDetails, setLoadingDetails] = useState(false)

  const [error, setError] = useState('')
  const [detailsError, setDetailsError] = useState('')

  async function loadPatients(query = '') {
    setLoading(true)
    setError('')
    setSelected(null)
    setDocuments([])
    setTotalDocuments(0)

    try {
      const params = new URLSearchParams({
        q: query,
        limit: '50',
        offset: '0',
      })

      const result = await getData(
        `/clinical/my-patients?${params.toString()}`
      )

      setPatients(result.patients || [])
      setTotalPatients(result.total || 0)
    } catch (err) {
      setPatients([])
      setTotalPatients(0)
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPatients()
  }, [])

  async function openPatient(patientId) {
    setLoadingDetails(true)
    setDetailsError('')
    setSelected(null)
    setDocuments([])
    setTotalDocuments(0)

    try {
      const encodedId = encodeURIComponent(patientId)

      const [patient, medicalRecords] = await Promise.all([
        getData(`/clinical/my-patients/${encodedId}`),
        getData(
          `/doctor/patients/${encodedId}/medical-documents`
        ),
      ])

      setSelected(patient)
      setDocuments(medicalRecords.documents || [])
      setTotalDocuments(medicalRecords.total || 0)
    } catch (err) {
      setDetailsError(err.message)
    } finally {
      setLoadingDetails(false)
    }
  }

  function handleSearch(event) {
    event.preventDefault()
    loadPatients(search.trim())
  }

  return (
    <section className="doctor-section doctor-patients-page">
      <h2>My Patients</h2>

      <p className="doctor-subtitle">
        View your patients, their medical records,
        and clinical notes.
      </p>

      <form
        className="doctor-patient-search"
        onSubmit={handleSearch}
      >
        <input
          type="search"
          value={search}
          placeholder="Search patients by name..."
          onChange={(event) => setSearch(event.target.value)}
          aria-label="Search patients"
        />

        <button type="submit" disabled={loading}>
          Search
        </button>
      </form>

      {error && (
        <p className="doctor-error" role="alert">
          {error}
        </p>
      )}

      {loading && <p>Loading patients...</p>}

      {!loading && !error && patients.length === 0 && (
        <p>
          No patients found. Patients with confirmed
          appointments will appear here automatically.
        </p>
      )}

      {!loading && !error && totalPatients > 50 && (
        <p className="doctor-subtitle">
          Showing the first 50 of {totalPatients} patients.
        </p>
      )}

      <div className="doctor-patient-layout">
        <div className="doctor-patient-list">
          {patients.map((patient) => (
            <button
              type="button"
              key={patient.patient_id}
              className="doctor-patient-card"
              onClick={() => openPatient(patient.patient_id)}
              disabled={loadingDetails}
            >
              <div className="doctor-patient-avatar">
                {patient.full_name
                  ?.charAt(0)
                  .toUpperCase() || 'P'}
              </div>

              <div>
                <strong>{patient.full_name}</strong>
                <small>
                  View records and clinical notes
                </small>
              </div>
            </button>
          ))}
        </div>

        <div className="doctor-patient-details">
          <h3>Patient Overview</h3>

          {loadingDetails && (
            <p>Loading patient records...</p>
          )}

          {detailsError && (
            <p className="doctor-error" role="alert">
              {detailsError}
            </p>
          )}

          {!selected && !loadingDetails && !detailsError && (
            <p>
              Select a patient to view their records.
            </p>
          )}

          {selected && (
            <>
              <p>
                <strong>Name:</strong> {selected.full_name}
              </p>

              <p>
                <strong>Patient reference:</strong>{' '}
                {selected.patient_id}
              </p>

              <p>
                <strong>Access type:</strong>{' '}
                {selected.access_source === 'appointment'
                  ? 'Confirmed appointment'
                  : 'Care-team assignment'}
              </p>

              {selected.assigned_at && (
                <p>
                  <strong>Assigned on:</strong>{' '}
                  {formatDate(selected.assigned_at)}
                </p>
              )}

              {/* MEDICAL RECORDS */}
              <div className="doctor-medical-records">
                <div className="doctor-medical-heading">
                  <h3>Medical Records</h3>

                  <span>
                    {totalDocuments} document(s)
                  </span>
                </div>

                {documents.length === 0 ? (
                  <p>
                    This patient has not uploaded
                    any medical documents yet.
                  </p>
                ) : (
                  <div className="doctor-document-list">
                    {documents.map((document) => {
                      const encodedPatient =
                        encodeURIComponent(selected.patient_id)

                      const encodedDocument =
                        encodeURIComponent(document.document_id)

                      const downloadUrl =
                        `/doctor/patients/${encodedPatient}` +
                        `/medical-documents/${encodedDocument}/download`

                      return (
                        <article
                          key={document.document_id}
                          className="doctor-document-card"
                        >
                          <div className="doctor-document-icon">
                            {document.media_type === 'application/pdf'
                              ? '📄'
                              : '🖼️'}
                          </div>

                          <div className="doctor-document-info">
                            <strong>
                              {document.filename}
                            </strong>

                            <small>
                              {formatSize(document.size_bytes)}
                            </small>

                            <small>
                              Uploaded:{' '}
                              {formatDate(document.uploaded_at)}
                            </small>
                          </div>

                          <a
                            className="doctor-document-download"
                            href={downloadUrl}
                          >
                            Download
                          </a>
                        </article>
                      )
                    })}
                  </div>
                )}

                {totalDocuments > documents.length && (
                  <p className="doctor-subtitle">
                    Showing {documents.length} of{' '}
                    {totalDocuments} documents.
                  </p>
                )}
              </div>

              {/* CLINICAL NOTES & DICTATION */}
              <DoctorClinicalNotes
                key={selected.patient_id}
                patientId={selected.patient_id}
              />
            </>
          )}
        </div>
      </div>
    </section>
  )
}
