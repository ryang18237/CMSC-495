import { useState } from 'react'
import { api } from '../api/client.js'

/**
 * Sign-in for the Alpha.
 *
 * Authentication is real -- every button here performs a genuine login and
 * receives a signed token, and every later request is authorised with it. What
 * a development build removes is the *typing*: the seeded credentials are
 * filled in, so a single click signs you in.
 *
 * A production build (`npm run build`) drops the shortcuts and the pre-filled
 * password and shows an ordinary empty form.
 */

const DEMO_PASSWORD = 'DemoPassw0rd!'
const DEFAULT_EMAIL = 'member@example.com'

const DEMO_ACCOUNTS = [
  {
    label: 'Continue as a member',
    email: DEFAULT_EMAIL,
    hint: 'Ask about your next step',
  },
  {
    label: 'Continue as a counsellor',
    email: 'counselor@example.com',
    hint: 'Escalation queue, AI insights, operations',
  },
]

const IS_DEMO_BUILD = Boolean(import.meta.env?.DEV)

export default function LoginPanel({ onSignedIn })
{
  const [email, setEmail] = useState(DEFAULT_EMAIL)
  // Pre-filled in a demo build so the Sign in button works on the first click.
  const [password, setPassword] = useState(IS_DEMO_BUILD ? DEMO_PASSWORD : '')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [showForm, setShowForm] = useState(!IS_DEMO_BUILD)

  async function signIn(emailAddress, secret)
  {
    setBusy(true)
    setError(null)

    try
    {
      const session = await api.login(emailAddress.trim(), secret)
      onSignedIn({
        token: session.accessToken,
        role: session.role,
        displayName: session.displayName,
      })
    }
    catch (caught)
    {
      setError(caught.message)
    }
    finally
    {
      setBusy(false)
    }
  }

  return (
    <div className="card login">
      <h1>SkillBridge AI</h1>
      <p className="muted">
        Education and career development for military members and veterans. Free to use.
      </p>

      {IS_DEMO_BUILD && (
        <div className="demo-shortcuts">
          {DEMO_ACCOUNTS.map((account) => (
            <button
              key={account.email}
              type="button"
              disabled={busy}
              onClick={() => signIn(account.email, DEMO_PASSWORD)}
            >
              {account.label}
              <span className="sub">{account.hint}</span>
            </button>
          ))}
        </div>
      )}

      {IS_DEMO_BUILD && !showForm && (
        <button type="button" className="link reveal-form" onClick={() => setShowForm(true)}>
          Sign in with an email and password instead
        </button>
      )}

      {showForm && (
        <form
          onSubmit={(event) =>
          {
            event.preventDefault()
            signIn(email, password)
          }}
        >
          {IS_DEMO_BUILD && <p className="divider">or sign in manually</p>}

          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            value={email}
            autoComplete="username"
            onChange={(event) => setEmail(event.target.value)}
            required
          />

          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            value={password}
            autoComplete="current-password"
            onChange={(event) => setPassword(event.target.value)}
            required
          />

          <button type="submit" disabled={busy}>
            {busy ? 'Signing in...' : 'Sign in'}
          </button>
        </form>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      {IS_DEMO_BUILD && (
        <p className="hint">
          Demo accounts are seeded and their password is filled in for you. Sign-in itself is
          real &mdash; every request after it carries a signed token.
        </p>
      )}
    </div>
  )
}
