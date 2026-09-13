import { useState } from 'react'
import { api } from '../api/client.js'

const DEMO_ACCOUNTS = [
  { label: 'Customer', email: 'customer@example.com' },
  { label: 'Agent', email: 'agent@example.com' },
]

export default function LoginPanel({ onSignedIn }) {
  const [email, setEmail] = useState('customer@example.com')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const session = await api.login(email.trim(), password)
      onSignedIn({
        token: session.accessToken,
        role: session.role,
        displayName: session.displayName,
      })
    } catch (caught) {
      setError(caught.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card login" onSubmit={submit}>
      <h1>Customer Service Platform</h1>
      <p className="muted">Alpha release. Sign in with a seeded account.</p>

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

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}

      <div className="hint">
        <span>Seeded accounts:</span>
        {DEMO_ACCOUNTS.map((account) => (
          <button
            key={account.email}
            type="button"
            className="link"
            onClick={() => setEmail(account.email)}
          >
            {account.label}
          </button>
        ))}
      </div>
    </form>
  )
}
