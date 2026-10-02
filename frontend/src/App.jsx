import { useEffect, useState } from 'react'
import LoginPanel from './components/LoginPanel.jsx'
import CustomerChat from './pages/CustomerChat.jsx'
import MyRecordPanel from './components/MyRecordPanel.jsx'
import AgentDashboard from './pages/AgentDashboard.jsx'
import PathwayRecommendations from './components/PathwayRecommendations.jsx'
import { api } from './api/client.js'

const SESSION_KEY = 'csp.session'

function readStoredSession()
{
  try
  {
    const raw = window.sessionStorage.getItem(SESSION_KEY)
    return raw ? JSON.parse(raw) : null
  }
  catch
  {
    return null
  }
}

export default function App()
{
  const [session, setSession] = useState(readStoredSession)
  const [health, setHealth] = useState(null)
  // Bumped when the member edits My record, so recommendations re-rank at once.

  useEffect(() =>
  {
    api.health().then(setHealth).catch(() => setHealth({ status: 'unreachable' }))
  }, [])

  useEffect(() =>
  {
    try
    {
      if (session) window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
      else window.sessionStorage.removeItem(SESSION_KEY)
    }
    catch
    {
      // Storage is a convenience only; the app works without it.
    }
  }, [session])

  if (!session)
  {
    return (
      <main className="shell centered">
        <LoginPanel onSignedIn={setSession} />
      </main>
    )
  }

  return (
    <main className="shell">
      <nav className="topbar">
        <span className="brand">SkillbridgeAI</span>
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
        <MemberView session={session} />
      )}
    </main>
  )
}

/**
 * What a member sees: a conversation, and the profile it draws on.
 *
 * The profile outgrew the sidebar it started in -- four kinds of entry, each
 * with a name and a place, do not fit in 320 pixels without every line
 * wrapping. It gets its own tab and the full width, which also lets the
 * conversation have the full width back.
 */
function MemberView({ session })
{
  const [tab, setTab] = useState('chat')
  // Bumped whenever the profile changes, so the recommendations re-rank
  // against it without the member having to reload anything.
  const [recordVersion, setRecordVersion] = useState(0)

  const tabs = [
    ['chat', 'Chat'],
    ['profile', 'My profile'],
  ]

  return (
    <div className="member-shell">
      <div className="tabs" role="tablist" aria-label="Member sections">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            className={`tab ${tab === key ? 'active' : ''}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Both stay mounted: switching tabs should not throw away a half-typed
          question or reload the profile. */}
      <div className="member-layout" hidden={tab !== 'chat'}>
        <CustomerChat session={session} />
        <aside className="member-sidebar">
          <PathwayRecommendations
            session={session}
            refreshKey={recordVersion}
            onPlanned={() => setRecordVersion((v) => v + 1)}
          />
        </aside>
      </div>
      <div hidden={tab !== 'profile'}>
        <MyRecordPanel
          session={session}
          refreshKey={recordVersion}
          onChange={() => setRecordVersion((v) => v + 1)}
        />
      </div>
    </div>
  )
}
