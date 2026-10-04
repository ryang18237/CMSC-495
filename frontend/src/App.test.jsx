import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from './App.jsx'
import { api } from './api/client.js'
import { pathwaysApi } from './api/pathways.js'

/**
 * Top-level routing by role. A member lands on the chat with their
 * recommendations beside it; a counsellor lands on the dashboard; signing out
 * returns to the sign-in panel and forgets the session.
 */

function storeSession(session)
{
  window.sessionStorage.setItem('csp.session', JSON.stringify(session))
}

beforeEach(() =>
{
  window.sessionStorage.clear()
  vi.spyOn(api, 'health').mockResolvedValue({ status: 'healthy' })
})

afterEach(() =>
{
  vi.restoreAllMocks()
})

describe('App', () =>
{
  it('asks a signed-out visitor to sign in', async () =>
  {
    render(<App />)
    expect(await screen.findByRole('button', { name: /Continue as a member/ })).toBeInTheDocument()
  })

  it('shows a member the chat and their recommended next steps', async () =>
  {
    storeSession({ token: 't', role: 'CUSTOMER', displayName: 'Alex Rivera' })
    vi.spyOn(api, 'createConversation').mockResolvedValue({ conversationId: 'conv-1' })
    vi.spyOn(pathwaysApi, 'recommended').mockResolvedValue({
      basis: 'GENERAL',
      method: 'tfidf-cosine/1',
      disclaimer: 'x',
      recommendations: [],
    })

    render(<App />)

    expect(await screen.findByText('Recommended next steps')).toBeInTheDocument()
    expect(screen.getByLabelText('Message')).toBeInTheDocument()
    expect(await screen.findByText('healthy')).toBeInTheDocument()
  })

  it('shows a counsellor the dashboard and no recommendations', async () =>
  {
    storeSession({ token: 't', role: 'AGENT', displayName: 'Sam Okafor' })
    vi.spyOn(api, 'listCases').mockResolvedValue([])
    const recommended = vi.spyOn(pathwaysApi, 'recommended')

    render(<App />)

    expect(await screen.findByRole('tab', { name: 'Escalation queue' })).toBeInTheDocument()
    expect(recommended).not.toHaveBeenCalled()
  })

  it('signs out and clears the stored session', async () =>
  {
    storeSession({ token: 't', role: 'AGENT', displayName: 'Sam Okafor' })
    vi.spyOn(api, 'listCases').mockResolvedValue([])

    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }))

    expect(await screen.findByRole('button', { name: /Continue as a member/ })).toBeInTheDocument()
    expect(window.sessionStorage.getItem('csp.session')).toBeNull()
  })

  it('reports an unreachable API instead of hiding it', async () =>
  {
    storeSession({ token: 't', role: 'AGENT', displayName: 'Sam Okafor' })
    api.health.mockRejectedValue(new Error('offline'))
    vi.spyOn(api, 'listCases').mockResolvedValue([])

    render(<App />)

    expect(await screen.findByText('unreachable')).toBeInTheDocument()
  })
})
