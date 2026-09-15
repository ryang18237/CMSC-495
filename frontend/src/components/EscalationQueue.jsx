import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client.js'
import CounsellorReplyBox from './CounsellorReplyBox.jsx'

const NEXT_STATUS = {
  QUEUED: 'ASSIGNED',
  ASSIGNED: 'RESOLVED',
  RESOLVED: 'CLOSED',
}

export default function EscalationQueue({ session, onError })
{
  const [cases, setCases] = useState([])
  const [selected, setSelected] = useState(null)

  const refresh = useCallback(async () =>
  {
    try
    {
      setCases(await api.listCases(session.token))
      onError(null)
    }
    catch (caught)
    {
      onError(caught)
    }
  }, [session.token, onError])

  useEffect(() =>
  {
    refresh()
  }, [refresh])

  async function open(caseId)
  {
    try
    {
      setSelected(await api.getCase(session.token, caseId))
    }
    catch (caught)
    {
      onError(caught)
    }
  }

  async function advance(caseId, currentStatus)
  {
    const next = NEXT_STATUS[currentStatus]
    if (!next)
    {
      return
    }

    try
    {
      await api.updateCase(session.token, caseId, next)
      await refresh()
      await open(caseId)
    }
    catch (caught)
    {
      onError(caught)
    }
  }

  return (
    <div className="agent">
      <div className="card queue">
        <header className="chat-header">
          <h2>Escalation queue</h2>
          <button type="button" className="secondary" onClick={refresh}>
            Refresh
          </button>
        </header>

        {cases.length === 0 && <p className="muted empty">No open cases.</p>}

        <ul className="case-list">
          {cases.map((item) => (
            <li key={item.caseId}>
              <button
                type="button"
                className={
                  selected && selected.caseId === item.caseId ? 'case-row selected' : 'case-row'
                }
                onClick={() => open(item.caseId)}
              >
                <span className={`pill ${item.reason.toLowerCase()}`}>{item.reason}</span>
                <span className="case-id">{item.caseId.slice(0, 8)}</span>
                <span className="muted">{item.queue}</span>
                <span className="status">{item.status}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="card detail">
        {!selected && <p className="muted empty">Select a case to see the conversation.</p>}

        {selected && (
          <>
            <header className="chat-header">
              <div>
                <h2>Case {selected.caseId.slice(0, 8)}</h2>
                <p className="muted">
                  {selected.reason} &middot; {selected.queue} &middot; {selected.status}
                </p>
              </div>
              {NEXT_STATUS[selected.status] && (
                <button type="button" onClick={() => advance(selected.caseId, selected.status)}>
                  Mark {NEXT_STATUS[selected.status].toLowerCase()}
                </button>
              )}
            </header>

            <pre className="summary">{selected.summary}</pre>

            <div className="transcript">
              {selected.messages.map((message) => (
                <article
                  key={message.messageId}
                  className={`bubble ${message.sender.toLowerCase()}`}
                >
                  <p>{message.content}</p>
                  {message.sources && message.sources.length > 0 && (
                    <p className="tag">Sources: {message.sources.join(', ')}</p>
                  )}
                </article>
              ))}
            </div>


            <CounsellorReplyBox
              session={session}
              caseId={selected.caseId}
              caseStatus={selected.status}
              onReplied={async () =>
              {
                await refresh()
                await open(selected.caseId)
              }}
            />


          </>
        )}
      </div>
    </div>
  )
}
