
import { useCallback, useEffect, useRef, useState } from 'react'
import './MedicalRecords.css'
import PatientReleasedNotes from './PatientReleasedNotes'

const MAX_FILE_SIZE = 10 * 1024 * 1024
const ALLOWED_EXTENSIONS = ['pdf', 'jpg', 'jpeg', 'png']

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

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`

  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`
  }

  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(value) {
  if (!value) return 'Unknown date'

  const date = new Date(value)

  return Number.isNaN(date.getTime())
    ? 'Unknown date'
    : date.toLocaleString()
}

function fileLabel(mediaType) {
  if (mediaType === 'application/pdf') return 'PDF'
  if (mediaType === 'image/png') return 'PNG'
  return 'JPG'
}

export default function MedicalRecords() {
  const inputRef = useRef(null)

  const [documents, setDocuments] = useState([])
  const [selectedFile, setSelectedFile] = useState(null)

  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)

  const [error, setError] = useState('')
  const [uploadError, setUploadError] = useState('')
  const [success, setSuccess] = useState('')

  // Load patient's uploaded medical documents.
  const loadDocuments = useCallback(async () => {
    setLoading(true)
    setError('')

    try {
      const result = await requestJson('/my/medical-documents')

      setDocuments(result.documents || [])
    } catch (err) {
      setDocuments([])
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  // Validate selected medical document.
  function selectFile(event) {
    setUploadError('')
    setSuccess('')

    const file = event.target.files?.[0] || null

    setSelectedFile(null)

    if (!file) return

    const extension = file.name
      .split('.')
      .pop()
      .toLowerCase()

    if (!ALLOWED_EXTENSIONS.includes(extension)) {
      setUploadError(
        'Only PDF, JPG, JPEG and PNG files are allowed.'
      )

      event.target.value = ''
      return
    }

    if (file.size > MAX_FILE_SIZE) {
      setUploadError(
        'File size must be 10 MB or less.'
      )

      event.target.value = ''
      return
    }

    if (file.size === 0) {
      setUploadError(
        'Cannot upload an empty file.'
      )

      event.target.value = ''
      return
    }

    setSelectedFile(file)
  }

  // Upload a new medical document.
  async function uploadFile(event) {
    event.preventDefault()

    if (!selectedFile || uploading) return

    setUploading(true)
    setUploadError('')
    setSuccess('')

    try {
      const formData = new FormData()

      formData.append('file', selectedFile)

      const uploaded = await requestJson(
        '/my/medical-documents',
        {
          method: 'POST',
          body: formData,
        }
      )

      setSelectedFile(null)

      if (inputRef.current) {
        inputRef.current.value = ''
      }

      await loadDocuments()

      setSuccess(
        `${uploaded.filename} uploaded successfully.`
      )
    } catch (err) {
      setUploadError(err.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <main className="records-page">

      {/* PAGE HEADER */}
      <header className="records-header">
        <div>
          <p className="records-eyebrow">
            PATIENT PORTAL
          </p>

          <h1>My Medical Records</h1>

          <p>
            Upload, organize and download your medical reports.
            View consultation notes released by your doctors.
          </p>
        </div>

        <span className="records-private">
          Private Documents
        </span>
      </header>

      {/* RECORDS SUMMARY */}
      <section className="records-summary">
        <div className="records-summary-card">
          <span>Total Documents</span>

          <strong>
            {documents.length}
          </strong>

          <small>
            Your uploaded medical records
          </small>
        </div>

        <div className="records-summary-card">
          <span>Supported Formats</span>

          <strong>
            PDF · JPG · PNG
          </strong>

          <small>
            Maximum 10 MB per file
          </small>
        </div>
      </section>

      {/* DOCUMENT UPLOAD */}
      <section className="records-panel">
        <div className="records-section-header">
          <div>
            <h2>Upload a Medical Document</h2>

            <p>
              Add lab reports, prescriptions, discharge summaries
              or scanned medical records.
            </p>
          </div>
        </div>

        <form
          onSubmit={uploadFile}
          className="records-upload-form"
        >
          <div className="records-upload-area">
            <div className="records-upload-icon">
              +
            </div>

            <label htmlFor="medical-file">
              Select a PDF or image
            </label>

            <input
              id="medical-file"
              ref={inputRef}
              type="file"
              accept=".pdf,.jpg,.jpeg,.png"
              onChange={selectFile}
              disabled={uploading}
            />

            <small>
              PDF, JPG, JPEG or PNG · Maximum 10 MB
            </small>
          </div>

          {selectedFile && (
            <div className="records-selected-file">
              <span>
                <strong>
                  Selected:
                </strong>{' '}
                {selectedFile.name}
              </span>

              <small>
                {formatSize(selectedFile.size)}
              </small>
            </div>
          )}

          {uploadError && (
            <p
              className="records-error"
              role="alert"
            >
              {uploadError}
            </p>
          )}

          {success && (
            <p
              className="records-success"
              role="status"
            >
              {success}
            </p>
          )}

          <button
            type="submit"
            className="records-upload-button"
            disabled={!selectedFile || uploading}
          >
            {uploading
              ? 'Uploading...'
              : 'Upload Medical Record'}
          </button>
        </form>
      </section>

      {/* UPLOADED MEDICAL DOCUMENTS */}
      <section className="records-panel">
        <div className="records-section-header">
          <div>
            <h2>My Documents</h2>

            <p>
              Files uploaded to your patient account.
            </p>
          </div>

          <button
            type="button"
            className="records-refresh"
            onClick={loadDocuments}
            disabled={loading}
          >
            Refresh
          </button>
        </div>

        {loading && (
          <p>
            Loading documents...
          </p>
        )}

        {error && (
          <p
            className="records-error"
            role="alert"
          >
            {error}
          </p>
        )}

        {!loading &&
          !error &&
          documents.length === 0 && (
            <div className="records-empty">
              <div className="records-empty-icon">
                📄
              </div>

              <h3>
                No medical documents yet
              </h3>

              <p>
                Upload your first medical record
                using the form above.
              </p>
            </div>
          )}

        {!loading &&
          !error &&
          documents.length > 0 && (
            <div className="records-document-list">
              {documents.map((document) => (
                <article
                  key={document.document_id}
                  className="records-document-card"
                >
                  <div className="records-file-icon">
                    {document.media_type === 'application/pdf'
                      ? '📄'
                      : '🖼️'}
                  </div>

                  <div className="records-document-info">
                    <strong>
                      {document.filename}
                    </strong>

                    <div className="records-document-meta">
                      <span>
                        {fileLabel(document.media_type)}
                      </span>

                      <span>
                        {formatSize(document.size_bytes)}
                      </span>

                      <span>
                        Uploaded{' '}
                        {formatDate(document.uploaded_at)}
                      </span>
                    </div>
                  </div>

                  <a
                    className="records-download"
                    href={
                      `/my/medical-documents/` +
                      `${encodeURIComponent(document.document_id)}` +
                      `/download`
                    }
                  >
                    Download
                  </a>
                </article>
              ))}
            </div>
          )}
      </section>

      {/* NEW: DOCTOR CONSULTATION NOTES */}
      <PatientReleasedNotes />

      {/* PRIVACY INFORMATION */}
      <p className="records-privacy-note">
        Your medical documents are available through your
        authenticated patient account. Authorized doctors
        may access uploaded documents for your care.
        Consultation notes appear here only when a doctor
        has signed and explicitly released them to you.
      </p>

    </main>
  )
}
