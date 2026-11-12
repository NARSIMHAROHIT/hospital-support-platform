
import { useEffect, useState } from 'react'
import { api } from '../api/client'

export default function SupportTickets() {
  const [tickets, setTickets] = useState([])
  const [category, setCategory] = useState('general')
  const [question, setQuestion] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  async function loadTickets() {
    try {
      setError('')
      const data = await api('/my/queries')
      setTickets(data)
    } catch {
      setError('Unable to load your support tickets.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadTickets()
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()

    setError('')
    setMessage('')
    setSubmitting(true)

    try {
      await api('/my/queries', {
        method: 'POST',
        body: JSON.stringify({
          category,
          question,
        }),
      })

      setQuestion('')
      setMessage('Your support ticket was created.')
      await loadTickets()
    } catch (err) {
      setError(err.message || 'Unable to create ticket.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="container">
      <h1>Patient Support</h1>
      <p>Submit questions and track your support requests.</p>

      <section className="card">
        <h2>Create Support Ticket</h2>

        <form onSubmit={handleSubmit}>
          <label htmlFor="category">Category</label>

          <select
            id="category"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="general">General</option>
            <option value="appointment">Appointment</option>
            <option value="billing">Billing</option>
            <option value="portal_access">Portal Access</option>
          </select>

          <label htmlFor="question">Your Question</label>

          <textarea
            id="question"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            minLength={5}
            maxLength={1000}
            required
            rows={5}
            placeholder="Describe your question..."
          />

          <button type="submit" disabled={submitting}>
            {submitting ? 'Submitting...' : 'Submit Ticket'}
          </button>
        </form>

        {message && <p role="status">{message}</p>}
        {error && <p role="alert" className="error">{error}</p>}
      </section>

      <section className="card">
        <h2>My Support Tickets</h2>

        <button type="button" onClick={loadTickets}>
          Refresh Tickets
        </button>

        {loading ? (
          <p>Loading tickets...</p>
        ) : tickets.length === 0 ? (
          <p>No support tickets found.</p>
        ) : (
          tickets.map((ticket) => (
            <article className="appointment" key={ticket.ticket_id}>
              <h3>{ticket.category.replaceAll('_', ' ')}</h3>
              <p>{ticket.question}</p>
              <p>Status: <strong>{ticket.status}</strong></p>
              <p>Priority: {ticket.priority || 'medium'}</p>
            </article>
          ))
        )}
      </section>
    </main>
  )
}
