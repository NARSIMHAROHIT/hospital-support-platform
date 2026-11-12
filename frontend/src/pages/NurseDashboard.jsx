
import { useEffect, useState } from 'react'
import './NurseDashboard.css'

async function apiGet(path) {
  const response = await fetch(path, {
    method: 'GET',
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

export default function NurseDashboard() {
  const [search, setSearch] = useState('')
  const [patients, setPatients] = useState([])
  const [total, setTotal] = useState(0)

  const [selectedPatient, setSelectedPatient] = useState(null)
  const [loading, setLoading] = useState(true)
  const [loadingDetails, setLoadingDetails] = useState(false)
  const [error, setError] = useState('')
  const [detailsError, setDetailsError] = useState('')

  async function loadPatients(query = '') {
    setLoading(true)
    setError('')

    try {
      const params = new URLSearchParams({
        q: query,
        limit: '50',
        offset: '0',
      })

      const result = await apiGet(
        `/clinical/my-patients?${params.toString()}`
      )

      setPatients(result.patients || [])
      setTotal(result.total || 0)
      setSelectedPatient(null)
    } catch (err) {
      setPatients([])
      setTotal(0)
      setSelectedPatient(null)
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
    setSelectedPatient(null)

    try {
      const patient = await apiGet(
        `/clinical/my-patients/${encodeURIComponent(patientId)}`
      )

      setSelectedPatient(patient)
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
    <main className="nurse-dashboard">
      <header className="nurse-header">
        <div>
          <p className="nurse-eyebrow">CLINICAL PORTAL</p>
          <h1>Nurse Dashboard</h1>
          <p>
            View patients assigned to your care team.
          </p>
        </div>
        <span className="nurse-role-badge">
          Nurse
        </span>
      </header>

      <section className="nurse-summary">
        <div className="nurse-summary-card">
          <span>Assigned Patients</span>
          <strong>{total}</strong>
          <small>Matching your current search</small>
        </div>

        <div className="nurse-summary-card">
          <span>Clinical Notes</span>
          <strong>Read-only</strong>
          <small>Available after notes API integration</small>
        </div>
      </section>

      <div className="nurse-grid">
        <section className="nurse-panel">
          <h2>My Patients</h2>

          <form
            className="nurse-search"
            onSubmit={handleSearch}
          >
            <input
              type="search"
              value={search}
              onChange={(event) =>
                setSearch(event.target.value)
              }
              placeholder="Search assigned patients"
              aria-label="Search assigned patients"
            />

            <button type="submit">
              Search
            </button>
          </form>

          {loading && <p>Loading patients...</p>}

          {error && (
            <p className="nurse-error" role="alert">
              {error}
            </p>
          )}

          {!loading && !error && patients.length === 0 && (
            <p className="nurse-empty">
              No assigned patients found.
            </p>
          )}

          {!loading && !error && patients.length > 0 && (
            <>
              <div className="nurse-patient-list">
                {patients.map((patient) => (
                  <button
                    key={patient.patient_id}
                    type="button"
                    className={
                      selectedPatient?.patient_id ===
                      patient.patient_id
                        ? 'nurse-patient active'
                        : 'nurse-patient'
                    }
                    onClick={() =>
                      openPatient(patient.patient_id)
                    }
                  >
                    <span className="nurse-avatar">
                      {patient.full_name
                        ?.charAt(0)
                        .toUpperCase() || 'P'}
                    </span>

                    <span className="nurse-patient-text">
                      <strong>{patient.full_name}</strong>
                      <small>View patient overview</small>
                    </span>

                    <span aria-hidden="true">›</span>
                  </button>
                ))}
              </div>

              {total > patients.length && (
                <p className="nurse-footnote">
                  Showing the first {patients.length} of {total}
                  {' '}patients. Pagination will be added later.
                </p>
              )}
            </>
          )}
        </section>

        <section className="nurse-panel">
          <h2>Patient Overview</h2>

          {loadingDetails && (
            <p>Loading patient details...</p>
          )}

          {detailsError && (
            <p className="nurse-error" role="alert">
              {detailsError}
            </p>
          )}

          {!loadingDetails &&
            !detailsError &&
            !selectedPatient && (
              <p className="nurse-empty">
                Select an assigned patient to view
                their basic information.
              </p>
            )}

          {selectedPatient && (
            <div className="nurse-details">
              <div>
                <span>Patient name</span>
                <strong>
                  {selectedPatient.full_name}
                </strong>
              </div>

              <div>
                <span>Patient reference</span>
                <code>
                  {selectedPatient.patient_id}
                </code>
              </div>

              <div>
                <span>Care-team assignment</span>
                <strong>Active</strong>
              </div>

              <div>
                <span>Assigned at</span>
                <strong>
                  {selectedPatient.assigned_at
                    ? new Date(
                        selectedPatient.assigned_at
                      ).toLocaleString()
                    : 'Not available'}
                </strong>
              </div>
            </div>
          )}

          <div className="nurse-coming-soon">
            <h3>Medical Records</h3>
            <p>
              Secure document viewing and released
              doctor notes will be added in
              upcoming lessons.
            </p>
            <p>
              Nurses will not be able to edit
              doctor dictation.
            </p>
          </div>
        </section>
      </div>
    </main>
  )
}
