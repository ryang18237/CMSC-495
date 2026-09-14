import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

// One example per behaviour the Alpha demonstrates. Clicking one fills the
// composer so a reviewer can see each path without knowing the trigger phrases.
const EXAMPLES = [
  { label: 'Next certification', text: 'Which certification should I work toward next?' },
  { label: 'Degree or credential', text: 'Should I do a degree or a certification first?' },
  { label: 'Resume wording', text: 'How do I describe my training on a civilian resume?' },
  { label: 'Internship timing', text: 'When should I start a SkillBridge internship?' },
  { label: 'Apprenticeships', text: 'Do my completed courses count toward an apprenticeship?' },
  { label: 'Talk to a counsellor', text: 'I want to speak to a human please' },
  { label: 'Off-topic', text: 'What is the capital of France?' },
  { label: 'AI service outage', text: 'Certification advice __force_ai_failure__' },
]

// Plain-language version of the escalation reason. The raw enum value is
// precise for the API but means nothing to the person reading the chat.
const ESCALATION_LABELS = {
  CUSTOMER_REQUEST: 'Transferred at your request',
  UNSUPPORTED_TOPIC: 'Outside what the assistant can answer',
  SECURITY_CONCERN: 'Routed to account security',
  VALIDATION_FAILURE: 'Answer failed our quality checks',
  AI_SERVICE_FAILURE: 'Assistant service unavailable',
}

export default function CustomerChat({ session })
{
  const [conversationId, setConversationId] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [feedbackGiven, setFeedbackGiven] = useState({})
  const transcriptRef = useRef(null)

  const startConversation = useCallback(async () =>
  {
    setError(null)
    try
    {
      const created = await api.createConversation(session.token)
      setConversationId(created.conversationId)
      setMessages([])
      setFeedbackGiven({})
    }
    catch (caught)
    {
      setError(caught.message)
    }
  }, [session.token])

  useEffect(() =>
  {
    startConversation()
  }, [startConversation])

  useEffect(() =>
  {
    const node = transcriptRef.current
    // scrollTo is absent in some environments (jsdom, older browsers).
    if (node && typeof node.scrollTo === 'function')
    {
      node.scrollTo({ top: node.scrollHeight })
    }
  }, [messages])

  async function send(event)
  {
    event.preventDefault()
    const text = draft.trim()
    if (!text || !conversationId) return

    setBusy(true)
    setError(null)
    setMessages((current) => [...current, { sender: 'CUSTOMER', content: text, key: `c-${Date.now()}` }])
    setDraft('')

    try
    {
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
    }
    catch (caught)
    {
      setError(`${caught.message} (${caught.code})`)
    }
    finally
    {
      setBusy(false)
    }
  }

  async function rate(messageId, rating)
  {
    try
    {
      await api.sendFeedback(session.token, conversationId, messageId, rating)
      setFeedbackGiven((current) => ({ ...current, [messageId]: rating }))
    }
    catch (caught)
    {
      setError(caught.message)
    }
  }

  async function requestHuman()
  {
    try
    {
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
    }
    catch (caught)
    {
      setError(caught.message)
    }
  }

  return (
    <section className="card chat">
      <header className="chat-header">
        <div>
          <h2>Ask about your next step</h2>
          <p className="muted">
            {conversationId ? `Conversation ${conversationId.slice(0, 8)}` : 'Starting...'}
          </p>
        </div>
        <div className="chat-actions">
          <button
            type="button"
            className="secondary"
            onClick={requestHuman}
            disabled={!conversationId}
          >
            Talk to a counsellor
          </button>
          <button type="button" className="secondary" onClick={startConversation}>
            New conversation
          </button>
        </div>
      </header>

      <div className="transcript" ref={transcriptRef} aria-live="polite">
        {messages.length === 0 && (
          <div className="empty">
            <p className="muted">
              Ask about certifications, degrees, apprenticeships or how to describe your
              experience. Answers are based on the training you have already completed.
            </p>
            <p className="muted">Or try one of these:</p>
            <div className="examples">
              {EXAMPLES.map((example) => (
                <button
                  key={example.label}
                  type="button"
                  className="chip"
                  onClick={() => setDraft(example.text)}
                >
                  {example.label}
                </button>
              ))}
            </div>
          </div>
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
