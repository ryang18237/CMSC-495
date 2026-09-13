import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

const ESCALATION_LABELS = {
  CUSTOMER_REQUEST: 'Transferred at your request',
  UNSUPPORTED_TOPIC: 'Outside what the assistant can answer',
  SECURITY_CONCERN: 'Routed to a security specialist',
  VALIDATION_FAILURE: 'Answer failed our quality checks',
  AI_SERVICE_FAILURE: 'Assistant service unavailable',
}

export default function CustomerChat({ session }) {
  const [conversationId, setConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [feedbackGiven, setFeedbackGiven] = useState({})
  const transcriptRef = useRef(null)

  const startConversation = useCallback(async () => {
    setError(null)
    try {
      const created = await api.createConversation(session.token)
      setConversationId(created.conversationId)
      setMessages([])
      setFeedbackGiven({})
    } catch (caught) {
      setError(caught.message)
    }
  }, [session.token])

  useEffect(() => {
    startConversation()
  }, [startConversation])

  useEffect(() => {
    const node = transcriptRef.current
    // scrollTo is absent in some environments (jsdom, older browsers).
    if (node && typeof node.scrollTo === 'function') {
      node.scrollTo({ top: node.scrollHeight })
    }
  }, [messages])

  async function send(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || !conversationId) return

    setBusy(true)
    setError(null)
    setMessages((current) => [...current, { sender: 'CUSTOMER', content: text, key: `c-${Date.now()}` }])
    setDraft('')

    try {
      const reply = await api.sendMessage(session.token, conversationId, text)
      setMessages((current) => [
        ...current,
        {
          sender: 'ASSISTANT',
          content: reply.response,
          status: reply.status,
          escalationReason: reply.escalationReason,
          messageId: reply.messageId,
          key: reply.messageId,
        },
      ])
    } catch (caught) {
      setError(`${caught.message} (${caught.code})`)
    } finally {
      setBusy(false)
    }
  }

  async function rate(messageId, rating) {
    try {
      await api.sendFeedback(session.token, conversationId, messageId, rating)
      setFeedbackGiven((current) => ({ ...current, [messageId]: rating }))
    } catch (caught) {
      setError(caught.message)
    }
  }

  async function requestHuman() {
    try {
      await api.escalate(session.token, conversationId, 'CUSTOMER_REQUEST')
      setMessages((current) => [
        ...current,
        {
          sender: 'ASSISTANT',
          content: 'A human specialist has been added to this conversation.',
          status: 'ESCALATED',
          escalationReason: 'CUSTOMER_REQUEST',
          key: `e-${Date.now()}`,
        },
      ])
    } catch (caught) {
      setError(caught.message)
    }
  }

  return (
    <section className="card chat">
      <header className="chat-header">
        <div>
          <h2>Support chat</h2>
          <p className="muted">
            {conversationId ? `Conversation ${conversationId.slice(0, 8)}` : 'Starting...'}
          </p>
        </div>
        <div className="chat-actions">
          <button type="button" className="secondary" onClick={requestHuman} disabled={!conversationId}>
            Request a human
          </button>
          <button type="button" className="secondary" onClick={startConversation}>
            New conversation
          </button>
        </div>
      </header>

      <div className="transcript" ref={transcriptRef} aria-live="polite">
        {messages.length === 0 && (
          <p className="muted empty">Ask about an order, a charge, a return or your account.</p>
        )}

        {messages.map((message) => (
          <article key={message.key} className={`bubble ${message.sender.toLowerCase()}`}>
            <p>{message.content}</p>

            {message.escalationReason && (
              <p className="tag">{ESCALATION_LABELS[message.escalationReason] ?? message.escalationReason}</p>
            )}

            {message.sender === 'ASSISTANT' && message.messageId && (
              <div className="feedback">
                {feedbackGiven[message.messageId] ? (
                  <span className="muted">Thanks for the feedback.</span>
                ) : (
                  <>
                    <button type="button" className="link" onClick={() => rate(message.messageId, 'HELPFUL')}>
                      Helpful
                    </button>
                    <button type="button" className="link" onClick={() => rate(message.messageId, 'UNHELPFUL')}>
                      Not helpful
                    </button>
                  </>
                )}
              </div>
            )}
          </article>
        ))}
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <form className="composer" onSubmit={send}>
        <label className="visually-hidden" htmlFor="message">
          Message
        </label>
        <input
          id="message"
          value={draft}
          maxLength={2000}
          placeholder="Type your question"
          onChange={(event) => setDraft(event.target.value)}
          disabled={!conversationId || busy}
        />
        <button type="submit" disabled={!draft.trim() || busy}>
          {busy ? 'Sending' : 'Send'}
        </button>
      </form>
    </section>
  )
}
