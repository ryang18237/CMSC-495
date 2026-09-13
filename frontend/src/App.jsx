import { useEffect, useState } from 'react'
import LoginPanel from './components/LoginPanel.jsx'
import CustomerChat from './pages/CustomerChat.jsx'
import AgentDashboard from './pages/AgentDashboard.jsx'
import { api } from './api/client.js'

const SESSION_KEY = 'csp.session'

function readStoredSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export default function App() {
  const [session, setSession] = useState(readStoredSession)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status: 'unreachable' }))
  }, [])

  useEffect(() => {
    try {
      if (session) window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
      else window.sessionStorage.removeItem(SESSION_KEY)
    } catch {
      // Storage is a convenience only; the app works without it.
    }
  }, [session])

  if (!session) {
    return (
      <main className="shell centered">
        <LoginPanel onSignedIn={setSession} />
      </main>
    )
  }

  return (
    <main className="shell">
      <nav className="topbar">
        <span className="brand">Customer Service Platform</span>
        <span className="muted">
          {session.displayName} &middot; {session.role}
        </span>
        {health && <span className={`pill health ${health.status}`}>{health.status}</span>}
        <button type="button" className="secondary" onClick={() => setSession(null)}>
          Sign out
        </button>
      </nav>

      {session.role === 'AGENT' ? (
        <AgentDashboard session={session} />
      ) : (
        <CustomerChat session={session} />
      )}
    </main>
  )
}
