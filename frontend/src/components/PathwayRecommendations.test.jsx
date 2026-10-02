import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import PathwayRecommendations from './PathwayRecommendations.jsx'
import { pathwaysApi } from '../api/pathways.js'
import { ApiError } from '../api/client.js'

const session = { token: 'test-token', role: 'CUSTOMER', displayName: 'Alex Rivera' }

afterEach(() =>
{
  vi.restoreAllMocks()
})

describe('PathwayRecommendations', () =>
{
  it('shows each suggestion with the reason it was made', async () =>
  {
    vi.spyOn(pathwaysApi, 'recommended').mockResolvedValue({
      basis: 'COMPLETED_TRAINING',
      method: 'tfidf-cosine/1',
      disclaimer: 'Suggestions are a starting point.',
      recommendations: [
        {
          pathwayId: 'comptia-security-plus',
          title: 'CompTIA Security+',
          kind: 'CERTIFICATION',
          field: 'Cybersecurity',
          summary: 'Baseline security credential.',
          score: 0.337,
          strength: 'STRONG',
          reason: 'NEXT_STEP',
          buildsOn: 'CompTIA A+',
          matchedTerms: ['information assurance', 'network'],
        },
        {
          pathwayId: 'cisco-ccna',
          title: 'Cisco Certified Network Associate (CCNA)',
          kind: 'CERTIFICATION',
          field: 'Information Technology',
          summary: 'Routing and switching.',
          score: 0.218,
          strength: 'GOOD',
          reason: 'BUILDS_ON',
          buildsOn: 'Network Administration Course',
          matchedTerms: ['network administration'],
        },
      ],
    })

    render(<PathwayRecommendations session={session} />)

    expect(await screen.findByText('CompTIA Security+')).toBeInTheDocument()
    expect(pathwaysApi.recommended).toHaveBeenCalledWith('test-token', 5)
    expect(screen.getByText('Next step after CompTIA A+')).toBeInTheDocument()
    expect(screen.getByText('Builds on Network Administration Course')).toBeInTheDocument()
    expect(screen.getByText('Strong match')).toBeInTheDocument()
    expect(screen.getByText('Matched on information assurance, network')).toBeInTheDocument()
    expect(screen.getByText('Suggestions are a starting point.')).toBeInTheDocument()
  })

  it('says so when it is showing general starting points', async () =>
  {
    vi.spyOn(pathwaysApi, 'recommended').mockResolvedValue({
      basis: 'GENERAL',
      method: 'tfidf-cosine/1',
      disclaimer: 'x',
      recommendations: [
        {
          pathwayId: 'capm',
          title: 'CAPM',
          kind: 'CERTIFICATION',
          field: 'Project Management',
          summary: 'Entry project management.',
          score: 0,
          strength: 'EXPLORATORY',
          reason: 'STARTING_POINT',
          buildsOn: null,
          matchedTerms: [],
        },
      ],
    })

    render(<PathwayRecommendations session={session} />)

    expect(await screen.findByText(/common starting points/)).toBeInTheDocument()
    expect(screen.getByText('A common starting point')).toBeInTheDocument()
  })

  it('shows the error code instead of failing silently', async () =>
  {
    vi.spyOn(pathwaysApi, 'recommended').mockRejectedValue(
      new ApiError(403, 'FORBIDDEN', 'Members only.', 'req-1'),
    )

    render(<PathwayRecommendations session={session} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('FORBIDDEN')
  })
})
