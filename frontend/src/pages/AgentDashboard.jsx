import { useCallback, useEffect, useState } from 'react'
import EscalationQueue from '../components/EscalationQueue.jsx'
import InsightsPanel from '../components/InsightsPanel.jsx'
import OperationsPanel from '../components/OperationsPanel.jsx'

const TABS = [
  { id: 'queue', label: 'Escalation queue' },
  { id: 'insights', label: 'AI insights' },
  { id: 'ops', label: 'Operations' },
]

export default function AgentDashboard({ session })
{
  const [tab, setTab] = useState('queue')
  const [error, setError] = useState(null)

  const report = useCallback((caught) =>
  {
    setError(caught ? caught.message : null)
  }, [])

  useEffect(() =>
  {
    setError(null)
  }, [tab])

  return (
    <section className="agent-shell">
      <nav className="tabs" role="tablist">
        {TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={tab === item.id}
            className={tab === item.id ? 'tab active' : 'tab'}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </nav>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {tab === 'queue' && <EscalationQueue session={session} onError={report} />}
      {tab === 'insights' && <InsightsPanel session={session} onError={report} />}
      {tab === 'ops' && <OperationsPanel session={session} onError={report} />}
    </section>
  )
}
