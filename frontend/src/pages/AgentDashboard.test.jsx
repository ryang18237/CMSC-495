import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AgentDashboard from './AgentDashboard.jsx'
import { api, ApiError } from '../api/client.js'
import { handoffApi } from '../api/agentHandoff.js'

/**
 * The counsellor's side of the platform: the queue, a case, a reply, the
 * review workflow and the operations counters. Every API call is mocked, so
 * these tests pin what the screens do with each documented response.
 */

const session = { token: 'agent-token', role: 'AGENT', displayName: 'Sam Okafor' }

const QUEUED_CASE = {
  caseId: 'case-0001-aaaa',
  conversationId: 'conv-1',
  reason: 'CUSTOMER_REQUEST',
  status: 'QUEUED',
  queue: 'GENERAL_SUPPORT',
  summary: 'Member asked for a person.',
  createdAt: '2026-09-28T10:00:00Z',
}

const CASE_DETAIL = {
  ...QUEUED_CASE,
  messages: [
    { messageId: 'm1', sender: 'CUSTOMER', content: 'I want to speak to a human please', sources: [] },
    { messageId: 'm2', sender: 'ASSISTANT', content: 'Connecting you now.', sources: ['Handover policy'] },
  ],
}

const METRICS = {
  instanceId: 'vm-1234',
  uptimeSeconds: 42,
  requests: { total: 17, byStatusClass: { '2xx': 15, '4xx': 2 } },
  conversationTurns: { total: 4, escalationRate: 0.25, escalationsByReason: { CUSTOMER_REQUEST: 1 } },
  latencyMs: { p95: 120, overFiveSecondTarget: 0 },
  cache: { hitRate: 0.5, implementation: 'in-process' },
}

afterEach(() =>
{
  vi.restoreAllMocks()
})

describe('Escalation queue', () =>
{
  it('lists open cases and opens one with its transcript', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([QUEUED_CASE])
    vi.spyOn(api, 'getCase').mockResolvedValue(CASE_DETAIL)

    render(<AgentDashboard session={session} />)

    const row = await screen.findByRole('button', { name: /CUSTOMER_REQUEST/ })
    await userEvent.click(row)

    expect(await screen.findByText('Case case-000')).toBeInTheDocument()
    expect(screen.getByText('I want to speak to a human please')).toBeInTheDocument()
    expect(screen.getByText('Sources: Handover policy')).toBeInTheDocument()
    expect(api.getCase).toHaveBeenCalledWith('agent-token', 'case-0001-aaaa')
  })

  it('says so when the queue is empty', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([])

    render(<AgentDashboard session={session} />)

    expect(await screen.findByText('No open cases.')).toBeInTheDocument()
  })

  it('advances a case to the next status', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([QUEUED_CASE])
    vi.spyOn(api, 'getCase').mockResolvedValue(CASE_DETAIL)
    vi.spyOn(api, 'updateCase').mockResolvedValue({ ...QUEUED_CASE, status: 'ASSIGNED' })

    render(<AgentDashboard session={session} />)
    await userEvent.click(await screen.findByRole('button', { name: /CUSTOMER_REQUEST/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Mark assigned' }))

    await waitFor(() =>
      expect(api.updateCase).toHaveBeenCalledWith('agent-token', 'case-0001-aaaa', 'ASSIGNED'),
    )
  })

  it('shows an API failure as an alert', async () =>
  {
    vi.spyOn(api, 'listCases').mockRejectedValue(
      new ApiError(503, 'DEPENDENCY_UNAVAILABLE', 'The database is unavailable.', 'req-9'),
    )

    render(<AgentDashboard session={session} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('The database is unavailable.')
  })
})

describe('Counsellor reply box', () =>
{
  it('sends a trimmed reply and refreshes the case', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([QUEUED_CASE])
    vi.spyOn(api, 'getCase').mockResolvedValue(CASE_DETAIL)
    vi.spyOn(handoffApi, 'replyToMember').mockResolvedValue({ messageId: 'm3', sender: 'AGENT' })

    render(<AgentDashboard session={session} />)
    await userEvent.click(await screen.findByRole('button', { name: /CUSTOMER_REQUEST/ }))

    const box = await screen.findByLabelText('Reply to the member')
    await userEvent.type(box, '  Happy to help.  ')
    await userEvent.click(screen.getByRole('button', { name: 'Send reply' }))

    await waitFor(() =>
      expect(handoffApi.replyToMember).toHaveBeenCalledWith(
        'agent-token',
        'case-0001-aaaa',
        'Happy to help.',
      ),
    )
    // The case is re-read so the status badge catches up with the claim.
    await waitFor(() => expect(api.getCase).toHaveBeenCalledTimes(2))
  })

  it('keeps send disabled until there is something to send', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([QUEUED_CASE])
    vi.spyOn(api, 'getCase').mockResolvedValue(CASE_DETAIL)

    render(<AgentDashboard session={session} />)
    await userEvent.click(await screen.findByRole('button', { name: /CUSTOMER_REQUEST/ }))

    const send = await screen.findByRole('button', { name: 'Send reply' })
    expect(send).toBeDisabled()
    await userEvent.type(screen.getByLabelText('Reply to the member'), '   ')
    expect(send).toBeDisabled()
    expect(screen.getByText('3997 characters left')).toBeInTheDocument()
  })

  it('shows the error code when the API refuses the reply', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([QUEUED_CASE])
    vi.spyOn(api, 'getCase').mockResolvedValue(CASE_DETAIL)
    vi.spyOn(handoffApi, 'replyToMember').mockRejectedValue(
      new ApiError(409, 'CASE_NOT_OPEN', 'This case is resolved.', 'req-2'),
    )

    render(<AgentDashboard session={session} />)
    await userEvent.click(await screen.findByRole('button', { name: /CUSTOMER_REQUEST/ }))
    await userEvent.type(await screen.findByLabelText('Reply to the member'), 'Hello')
    await userEvent.click(screen.getByRole('button', { name: 'Send reply' }))

    expect(await screen.findByText('This case is resolved. (CASE_NOT_OPEN)')).toBeInTheDocument()
  })

  it('is replaced by a note on a resolved case', async () =>
  {
    const resolved = { ...CASE_DETAIL, status: 'RESOLVED' }
    vi.spyOn(api, 'listCases').mockResolvedValue([{ ...QUEUED_CASE, status: 'RESOLVED' }])
    vi.spyOn(api, 'getCase').mockResolvedValue(resolved)

    render(<AgentDashboard session={session} />)
    await userEvent.click(await screen.findByRole('button', { name: /CUSTOMER_REQUEST/ }))

    expect(await screen.findByText(/This case is resolved/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Reply to the member')).not.toBeInTheDocument()
  })
})

describe('AI insights', () =>
{
  it('runs the analysis and records a decision', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([])
    const pending = {
      recommendationId: 'rec-1',
      category: 'KNOWLEDGE_GAP',
      detail: 'Members keep asking about apprenticeships.',
      occurrences: 3,
      reviewStatus: 'PENDING_REVIEW',
    }
    vi.spyOn(api, 'listRecommendations')
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([pending])
      .mockResolvedValue([{ ...pending, reviewStatus: 'APPROVED' }])
    vi.spyOn(api, 'runAnalytics').mockResolvedValue({ recommendationsCreated: 1 })
    vi.spyOn(api, 'reviewRecommendation').mockResolvedValue({ ...pending, reviewStatus: 'APPROVED' })

    render(<AgentDashboard session={session} />)
    await userEvent.click(screen.getByRole('tab', { name: 'AI insights' }))

    expect(await screen.findByText(/No candidates yet/)).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Run analysis' }))
    expect(await screen.findByText('Last run produced 1 new candidate.')).toBeInTheDocument()

    await userEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    await waitFor(() =>
      expect(api.reviewRecommendation).toHaveBeenCalledWith('agent-token', 'rec-1', 'APPROVED'),
    )
    expect(await screen.findByText('Decided')).toBeInTheDocument()
  })
})

describe('Operations', () =>
{
  it('shows per-instance counters against the five-second target', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([])
    vi.spyOn(api, 'metrics').mockResolvedValue(METRICS)

    render(<AgentDashboard session={session} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Operations' }))

    expect(await screen.findByText(/Instance vm-1234/)).toBeInTheDocument()
    expect(screen.getByText('25%')).toBeInTheDocument()
    expect(screen.getByText('120 ms')).toBeInTheDocument()
    expect(screen.getByText('CUSTOMER_REQUEST')).toBeInTheDocument()
    expect(screen.getByText('4xx')).toBeInTheDocument()
  })

  it('flags a p95 over the target', async () =>
  {
    vi.spyOn(api, 'listCases').mockResolvedValue([])
    vi.spyOn(api, 'metrics').mockResolvedValue({
      ...METRICS,
      latencyMs: { p95: 6200, overFiveSecondTarget: 2 },
    })

    render(<AgentDashboard session={session} />)
    await userEvent.click(screen.getByRole('tab', { name: 'Operations' }))

    const value = await screen.findByText('6200 ms')
    expect(value.closest('.tile')).toHaveClass('warn')
  })
})
