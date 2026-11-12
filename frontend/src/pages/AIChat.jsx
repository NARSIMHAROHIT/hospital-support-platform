
import { useEffect, useState } from 'react'

const API = '/patient/ai/conversations'

async function apiRequest(url, options = {}) {
  const response = await fetch(url, {
    credentials: 'include',
    ...options,
    headers: {
      ...(options.body
        ? { 'Content-Type': 'application/json' }
        : {}),
      ...options.headers,
    },
  })

  const raw = await response.text()
  let data = {}

  try {
    data = raw ? JSON.parse(raw) : {}
  } catch {
    throw new Error('Unexpected server response.')
  }

  if (!response.ok) {
    if (response.status === 401) {
      throw new Error('Session expired. Please log in again.')
    }

    throw new Error(
      typeof data.detail === 'string'
        ? data.detail
        : `Request failed (${response.status}).`
    )
  }

  return data
}

function formatDate(value) {
  if (!value) return ''

  const date = new Date(value)

  if (Number.isNaN(date.getTime())) return ''

  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
  })
}

export default function AIChat() {
  const [conversations, setConversations] = useState([])
  const [activeId, setActiveId] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')

  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')

  const busy = loading || sending

  // Load saved conversations when the page opens.
  useEffect(() => {
    let cancelled = false

    async function initialize() {
      try {
        const result = await apiRequest(API)

        if (cancelled) return

        const items = result.conversations || []
        setConversations(items)

        if (items.length > 0) {
          const id = items[0].conversation_id

          const detail = await apiRequest(
            `${API}/${encodeURIComponent(id)}`
          )

          if (cancelled) return

          setActiveId(id)
          setMessages(detail.messages || [])
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.message)
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    initialize()

    return () => {
      cancelled = true
    }
  }, [])

  async function refreshConversations() {
    const result = await apiRequest(API)
    setConversations(result.conversations || [])
  }

  async function openConversation(id) {
    if (busy) return

    setLoading(true)
    setError('')

    try {
      const detail = await apiRequest(
        `${API}/${encodeURIComponent(id)}`
      )

      setActiveId(id)
      setMessages(detail.messages || [])
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function createConversation() {
    if (busy) return

    setLoading(true)
    setError('')

    try {
      const created = await apiRequest(API, {
        method: 'POST',
      })

      setActiveId(created.conversation_id)
      setMessages([])
      setInput('')

      await refreshConversations()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function sendMessage(event) {
    event.preventDefault()

    const text = input.trim()

    if (!text || busy || text.length > 2000) return

    setSending(true)
    setError('')

    try {
      let conversationId = activeId

      // Create a conversation automatically if needed.
      if (!conversationId) {
        const created = await apiRequest(API, {
          method: 'POST',
        })

        conversationId = created.conversation_id

        setActiveId(conversationId)
      }

      const result = await apiRequest(
        `${API}/${encodeURIComponent(conversationId)}/messages`,
        {
          method: 'POST',
          body: JSON.stringify({
            message: text,
          }),
        }
      )

      setMessages((previous) => [
        ...previous,
        result.user_message,
        result.assistant_message,
      ])

      setInput('')

      // Refresh titles and recent-chat ordering.
      try {
        await refreshConversations()
      } catch {
        // A list refresh failure does not undo
        // a successfully saved chat message.
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSending(false)
    }
  }

  async function deleteConversation() {
    if (!activeId || busy) return

    const confirmed = window.confirm(
      'Delete this conversation and all its saved messages?'
    )

    if (!confirmed) return

    setLoading(true)
    setError('')

    try {
      await apiRequest(
        `${API}/${encodeURIComponent(activeId)}`,
        { method: 'DELETE' }
      )

      setActiveId(null)
      setMessages([])
      setInput('')

      await refreshConversations()
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <main className="hospital-ai-page">
      <style>{`
        .hospital-ai-page {
          display: flex;
          gap: 16px;
          min-height: 620px;
          width: 100%;
          color: #17233b;
        }

        .hospital-ai-sidebar {
          width: 250px;
          flex-shrink: 0;
          background: #f6f8fc;
          border: 1px solid #e2e8f0;
          border-radius: 14px;
          padding: 16px;
          display: flex;
          flex-direction: column;
          gap: 12px;
        }

        .hospital-ai-sidebar h2 {
          margin: 0;
          font-size: 17px;
        }

        .hospital-ai-new {
          background: #1d4ed8;
          color: white;
          border: none;
          padding: 12px;
          border-radius: 9px;
          cursor: pointer;
          font-weight: 600;
        }

        .hospital-ai-new:disabled,
        .hospital-ai-send:disabled {
          opacity: 0.55;
          cursor: not-allowed;
        }

        .hospital-ai-history {
          display: flex;
          flex-direction: column;
          gap: 6px;
          overflow-y: auto;
          flex: 1;
        }

        .hospital-ai-history button {
          width: 100%;
          border: 1px solid transparent;
          border-radius: 9px;
          padding: 11px;
          background: transparent;
          color: inherit;
          cursor: pointer;
          text-align: left;
        }

        .hospital-ai-history button.active {
          background: #e0ebff;
          border-color: #bed2ff;
        }

        .hospital-ai-history button:hover {
          background: #e9eef8;
        }

        .hospital-ai-history button:disabled {
          cursor: not-allowed;
          opacity: 0.65;
        }

        .hospital-ai-history small {
          display: block;
          margin-top: 4px;
          color: #64748b;
        }

        .hospital-ai-chat {
          flex: 1;
          min-width: 0;
          background: white;
          border: 1px solid #e2e8f0;
          border-radius: 14px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }

        .hospital-ai-header {
          padding: 16px 20px;
          border-bottom: 1px solid #e2e8f0;
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
        }

        .hospital-ai-header h1 {
          font-size: 19px;
          margin: 0 0 4px;
        }

        .hospital-ai-header p {
          color: #64748b;
          font-size: 12px;
          margin: 0;
        }

        .hospital-ai-delete {
          background: white;
          border: 1px solid #fecaca;
          color: #b91c1c;
          padding: 8px 10px;
          border-radius: 8px;
          cursor: pointer;
        }

        .hospital-ai-delete:disabled {
          opacity: 0.5;
        }

        .hospital-ai-messages {
          flex: 1;
          min-height: 340px;
          padding: 22px;
          overflow-y: auto;
          display: flex;
          flex-direction: column;
          gap: 16px;
        }

        .hospital-ai-welcome {
          margin: auto;
          text-align: center;
          max-width: 420px;
        }

        .hospital-ai-welcome h2 {
          font-size: 23px;
          margin-bottom: 10px;
        }

        .hospital-ai-welcome p {
          color: #64748b;
          line-height: 1.6;
        }

        .hospital-ai-bubble {
          max-width: 80%;
          border-radius: 13px;
          padding: 12px 15px;
          line-height: 1.6;
          font-size: 14px;
          white-space: pre-wrap;
          overflow-wrap: anywhere;
        }

        .hospital-ai-bubble.user {
          align-self: flex-end;
          background: #1d4ed8;
          color: white;
        }

        .hospital-ai-bubble.assistant {
          align-self: flex-start;
          background: #f1f5f9;
          color: #17233b;
        }

        .hospital-ai-bubble small {
          display: block;
          margin-bottom: 5px;
          font-size: 11px;
          opacity: 0.75;
          font-weight: 600;
        }

        .hospital-ai-error {
          margin: 0 20px 10px;
          padding: 11px 13px;
          background: #fef2f2;
          color: #991b1b;
          border-radius: 8px;
          font-size: 13px;
        }

        .hospital-ai-form {
          border-top: 1px solid #e2e8f0;
          padding: 16px;
          display: flex;
          gap: 10px;
          align-items: flex-end;
        }

        .hospital-ai-form textarea {
          flex: 1;
          min-width: 0;
          min-height: 48px;
          max-height: 140px;
          resize: vertical;
          border: 1px solid #cbd5e1;
          border-radius: 10px;
          padding: 12px;
          font: inherit;
          font-size: 14px;
          color: #17233b;
        }

        .hospital-ai-send {
          background: #1d4ed8;
          color: white;
          border: none;
          border-radius: 9px;
          padding: 13px 18px;
          cursor: pointer;
          font-weight: 600;
        }

        .hospital-ai-disclaimer {
          padding: 0 18px 12px;
          font-size: 11px;
          color: #64748b;
        }

        @media (max-width: 800px) {
          .hospital-ai-page {
            flex-direction: column;
          }

          .hospital-ai-sidebar {
            width: 100%;
            max-height: 220px;
          }

          .hospital-ai-chat {
            min-height: 550px;
          }
        }
      `}</style>

      <aside className="hospital-ai-sidebar">
        <h2>AI Conversations</h2>

        <button
          type="button"
          className="hospital-ai-new"
          onClick={createConversation}
          disabled={busy}
        >
          + New Chat
        </button>

        <div className="hospital-ai-history">
          {conversations.length === 0 && (
            <p style={{ color: '#64748b', fontSize: 13 }}>
              No saved conversations yet.
            </p>
          )}

          {conversations.map((conversation) => (
            <button
              type="button"
              key={conversation.conversation_id}
              disabled={busy}
              className={
                conversation.conversation_id === activeId
                  ? 'active'
                  : ''
              }
              onClick={() =>
                openConversation(conversation.conversation_id)
              }
            >
              <strong>{conversation.title}</strong>
              <small>
                {formatDate(conversation.updated_at)}
              </small>
            </button>
          ))}
        </div>
      </aside>

      <section
        className="hospital-ai-chat"
        aria-label="Patient AI Assistant"
      >
        <header className="hospital-ai-header">
          <div>
            <h1>Hospital AI Assistant</h1>
            <p>Patient portal support</p>
          </div>

          {activeId && (
            <button
              type="button"
              className="hospital-ai-delete"
              onClick={deleteConversation}
              disabled={busy}
            >
              Delete Chat
            </button>
          )}
        </header>

        <div
          className="hospital-ai-messages"
          aria-live="polite"
        >
          {loading && (
            <p>Loading conversation...</p>
          )}

          {!loading && messages.length === 0 && (
            <div className="hospital-ai-welcome">
              <h2>How can I help you?</h2>
              <p>
                Ask about navigating appointments,
                medical records, or released clinical notes.
              </p>
            </div>
          )}

          {messages.map((message) => (
            <div
              key={message.message_id}
              className={`hospital-ai-bubble ${message.role}`}
            >
              <small>
                {message.role === 'user'
                  ? 'You'
                  : 'AI Assistant'}
              </small>
              {message.content}
            </div>
          ))}

          {sending && (
            <div className="hospital-ai-bubble assistant">
              <small>AI Assistant</small>
              Generating a reply...
            </div>
          )}
        </div>

        {error && (
          <div className="hospital-ai-error" role="alert">
            {error}
          </div>
        )}

        <form
          className="hospital-ai-form"
          onSubmit={sendMessage}
        >
          <textarea
            aria-label="Chat message"
            placeholder="Ask about your patient portal..."
            value={input}
            maxLength={2000}
            disabled={busy}
            onChange={(event) =>
              setInput(event.target.value)
            }
            onKeyDown={(event) => {
              if (
                event.key === 'Enter' &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault()
                event.currentTarget.form?.requestSubmit()
              }
            }}
          />

          <button
            type="submit"
            className="hospital-ai-send"
            disabled={busy || !input.trim()}
          >
            Send
          </button>
        </form>

        <div className="hospital-ai-disclaimer">
          Prototype using fictional data. Do not enter
          personal medical details. For medical guidance,
          follow your care team's verified instructions.
          This assistant is not for emergencies.
        </div>
      </section>
    </main>
  )
}
