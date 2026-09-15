import { useEffect } from 'react'
import { api } from '../api/client.js'

/**
 * Human agent escalation path -- the member's side.
 *
 * OWNER: Benjamin Madden (Integration Lead)
 *
 * After a conversation is escalated, a counsellor may answer at any point.
 * This polls the conversation the member already has open and hands any new
 * counsellor messages to the caller.
 *
 * Polling rather than websockets on purpose: the Alpha has one instance and no
 * message broker, and a websocket would need both plus a reconnection story.
 * Every few seconds is fast enough for a person typing a considered reply, and
 * it reuses an endpoint that already exists and is already authorised.
 *
 * Polling stops when the conversation is not escalated, so an ordinary
 * assistant conversation costs nothing.
 */

const POLL_INTERVAL_MS = 5000

export default function useCounsellorReplies(session, conversationId, isEscalated, onNewReplies)
{
  useEffect(() =>
  {
    if (!conversationId || !isEscalated)
    {
      return undefined
    }

    // Ids already shown, so a reply is appended once rather than on every tick.
    const seen = new Set()
    let cancelled = false

    async function poll()
    {
      try
      {
        const conversation = await api.getConversation(session.token, conversationId)
        if (cancelled)
        {
          return
        }

        const fresh = conversation.messages.filter(
          (message) => message.sender === 'AGENT' && !seen.has(message.messageId),
        )

        if (fresh.length > 0)
        {
          fresh.forEach((message) => seen.add(message.messageId))
          onNewReplies(fresh)
        }
      }
      catch
      {
        // A failed poll is not worth telling the member about -- the next one
        // is a few seconds away. A persistent failure shows up when they send
        // their next message.
      }
    }

    poll()
    const timer = setInterval(poll, POLL_INTERVAL_MS)

    return () =>
    {
      cancelled = true
      clearInterval(timer)
    }
  }, [session.token, conversationId, isEscalated, onNewReplies])
}
