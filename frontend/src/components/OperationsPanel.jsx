import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client.js'

/**
 * Monitoring and Logging.
 *
 * ALPHA SCOPE -- barebones. These counters are collected by the live request
 * path but live in process memory and are read back through one endpoint. A
 * production deployment exports them to a monitoring system instead, and the
 * figures shown are for a single instance, which is why the instance id is
 * displayed rather than implying a cluster-wide total.
 */
const RESPONSE_TARGET_MS = 5000

export default function OperationsPanel({ session, onError })
{
  const [metrics, setMetrics] = useState(null)

  const refresh = useCallback(async () =>
  {
    try
    {
      setMetrics(await api.metrics(session.token))
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

  if (!metrics)
  {
    return (
      <div className="card">
        <p className="muted empty">Loading counters...</p>
      </div>
    )
  }

  const turns = metrics.conversationTurns
  const latency = metrics.latencyMs
  const withinTarget = latency.p95 <= RESPONSE_TARGET_MS

  return (
    <div className="card">
      <header className="chat-header">
        <div>
          <h2>Operations</h2>
          <p className="muted">
            Instance {metrics.instanceId} &middot; up {metrics.uptimeSeconds}s &middot; counters
            are per instance, not cluster-wide.
          </p>
        </div>
        <button type="button" className="secondary" onClick={refresh}>
          Refresh
        </button>
      </header>

      <div className="tiles">
        <div className="tile">
          <span className="tile-value">{metrics.requests.total}</span>
          <span className="tile-label">API requests</span>
        </div>
        <div className="tile">
          <span className="tile-value">{turns.total}</span>
          <span className="tile-label">Conversation turns</span>
        </div>
        <div className="tile">
          <span className="tile-value">{Math.round(turns.escalationRate * 100)}%</span>
          <span className="tile-label">Escalated to a person</span>
        </div>
        <div className={withinTarget ? 'tile' : 'tile warn'}>
          <span className="tile-value">{latency.p95} ms</span>
          <span className="tile-label">p95 turn latency (target {RESPONSE_TARGET_MS})</span>
        </div>
        <div className="tile">
          <span className="tile-value">{Math.round(metrics.cache.hitRate * 100)}%</span>
          <span className="tile-label">Cache hit rate ({metrics.cache.implementation})</span>
        </div>
        <div className={latency.overFiveSecondTarget > 0 ? 'tile warn' : 'tile'}>
          <span className="tile-value">{latency.overFiveSecondTarget}</span>
          <span className="tile-label">Turns over the 5s target</span>
        </div>
      </div>

      <h3 className="section">Escalations by reason</h3>
      {Object.keys(turns.escalationsByReason).length === 0 && (
        <p className="muted">None recorded on this instance yet.</p>
      )}
      <ul className="breakdown">
        {Object.entries(turns.escalationsByReason).map(([reason, count]) => (
          <li key={reason}>
            <span className={`pill ${reason.toLowerCase()}`}>{reason}</span>
            <span className="status">{count}</span>
          </li>
        ))}
      </ul>

      <h3 className="section">Responses by status class</h3>
      <ul className="breakdown">
        {Object.entries(metrics.requests.byStatusClass).map(([statusClass, count]) => (
          <li key={statusClass}>
            <span className="pill">{statusClass}</span>
            <span className="status">{count}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}
