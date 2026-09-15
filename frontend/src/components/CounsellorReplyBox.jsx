import { useState } from 'react'
import { handoffApi } from '../api/agentHandoff.js'

/**
 * Human agent escalation path -- the counsellor's reply box.
 *
 * OWNER: Benjamin Madden (Integration Lead)
 *
 * Sits under the transcript in the case detail panel. Sending a reply claims
 * the case server-side, so there is no separate claim step in this flow, and
 * `onReplied` lets the parent refresh the case so the status badge catches up.
 */

const MAX_REPLY_LENGTH = 4000

export default function CounsellorReplyBox({ session, caseId, caseStatus, onReplied })
{
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  // RESOLVED and CLOSED cases are finished as far as the member is concerned,
  // and the API refuses a reply on them. Hiding the box is friendlier than
  // letting someone type a paragraph and then rejecting it.
  const canReply = caseStatus === 'QUEUED' || caseStatus === 'ASSIGNED'
  if (!canReply)
  {
    return (
      <p className="muted">
        This case is {caseStatus.toLowerCase()}. Reopen it if the member needs more help.
      </p>
    )
  }

  async function send(event)
  {
    event.preventDefault()
    const text = draft.trim()
    if (!text)
    {
      return
    }

    setBusy(true)
    setError(null)

    try
    {
      await handoffApi.replyToMember(session.token, caseId, text)
      setDraft('')
      if (onReplied)
      {
        await onReplied()
      }
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

  const remaining = MAX_REPLY_LENGTH - draft.length

  return (
    <form className="reply-box" onSubmit={send}>
      <label htmlFor="counsellor-reply">Reply to the member</label>
      <textarea
        id="counsellor-reply"
        rows={4}
        value={draft}
        maxLength={MAX_REPLY_LENGTH}
        placeholder="Answer in your own words. The member sees this in their chat."
        onChange={(event) => setDraft(event.target.value)}
        disabled={busy}
      />

      <div className="reply-actions">
        <span className="muted">{remaining} characters left</span>
        <button type="submit" disabled={busy || !draft.trim()}>
          {busy ? 'Sending...' : 'Send reply'}
        </button>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </form>
  )
}
