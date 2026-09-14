import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client.js'

/**
 * Reviewed AI Configuration / Routing Improvements.
 *
 * ALPHA SCOPE -- barebones. The Learning Analytics Worker aggregates feedback
 * and escalation patterns into candidates, and a person approves or rejects
 * them here. Approving does not yet apply anything: no prompt or routing rule
 * changes as a result. The property that matters is already true -- an
 * individual conversation can never alter production AI behaviour on its own.
 */
export default function InsightsPanel({ session, onError })
{
  const [recommendations, setRecommendations] = useState([])
  const [busy, setBusy] = useState(false)
  const [lastRun, setLastRun] = useState(null)

  const refresh = useCallback(async () =>
  {
    try
    {
      setRecommendations(await api.listRecommendations(session.token))
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

  async function runWorker()
  {
    setBusy(true)
    try
    {
      const result = await api.runAnalytics(session.token)
      setLastRun(result.recommendationsCreated)
      await refresh()
    }
    catch (caught)
    {
      onError(caught)
    }
    finally
    {
      setBusy(false)
    }
  }

  async function decide(recommendationId, reviewStatus)
  {
    try
    {
      await api.reviewRecommendation(session.token, recommendationId, reviewStatus)
      await refresh()
    }
    catch (caught)
    {
      onError(caught)
    }
  }

  const pending = recommendations.filter((item) => item.reviewStatus === 'PENDING_REVIEW')
  const decided = recommendations.filter((item) => item.reviewStatus !== 'PENDING_REVIEW')

  return (
    <div className="card">
      <header className="chat-header">
        <div>
          <h2>AI insights</h2>
          <p className="muted">
            Aggregated patterns awaiting human review. Approved changes are applied by hand;
            nothing here alters the assistant automatically.
          </p>
        </div>
        <button type="button" onClick={runWorker} disabled={busy}>
          {busy ? 'Running...' : 'Run analysis'}
        </button>
      </header>

      {lastRun !== null && (
        <p className="muted">
          Last run produced {lastRun} new {lastRun === 1 ? 'candidate' : 'candidates'}.
        </p>
      )}

      {recommendations.length === 0 && (
        <p className="muted empty">
          No candidates yet. Patterns need to recur before they are worth a person&rsquo;s time
          &mdash; escalate a couple of conversations, then run the analysis.
        </p>
      )}

      {pending.length > 0 && <h3 className="section">Awaiting review</h3>}
      <ul className="recommendations">
        {pending.map((item) => (
          <li key={item.recommendationId} className="recommendation">
            <div className="recommendation-head">
              <span className="pill">{item.category}</span>
              <span className="muted">seen {item.occurrences}&times;</span>
            </div>
            <p>{item.detail}</p>
            <div className="recommendation-actions">
              <button
                type="button"
                onClick={() => decide(item.recommendationId, 'APPROVED')}
              >
                Approve
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => decide(item.recommendationId, 'REJECTED')}
              >
                Reject
              </button>
            </div>
          </li>
        ))}
      </ul>

      {decided.length > 0 && <h3 className="section">Decided</h3>}
      <ul className="recommendations">
        {decided.map((item) => (
          <li key={item.recommendationId} className="recommendation decided">
            <div className="recommendation-head">
              <span className="pill">{item.category}</span>
              <span className={`status ${item.reviewStatus.toLowerCase()}`}>
                {item.reviewStatus}
              </span>
            </div>
            <p className="muted">{item.detail}</p>
          </li>
        ))}
      </ul>
    </div>
  )
}
