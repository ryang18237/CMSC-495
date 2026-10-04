import { afterEach, describe, expect, it, vi } from 'vitest'
import { handoffApi } from './agentHandoff.js'
import { pathwaysApi } from './pathways.js'

/**
 * The thin client calls must hit the documented paths with the documented
 * methods and bodies. A typo here would only show up against a live server.
 */

function mockFetch(body = {}, status = 200)
{
  const fetch = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    json: () => Promise.resolve(body),
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

afterEach(() =>
{
  vi.unstubAllGlobals()
})

describe('handoffApi', () =>
{
  it('posts a reply as JSON with the bearer token', async () =>
  {
    const fetch = mockFetch({ sender: 'AGENT' }, 201)
    await handoffApi.replyToMember('tok', 'case-1', 'Hello')

    const [url, options] = fetch.mock.calls[0]
    expect(url).toBe('/api/v1/agent/cases/case-1/reply')
    expect(options.method).toBe('POST')
    expect(options.headers.Authorization).toBe('Bearer tok')
    expect(JSON.parse(options.body)).toEqual({ message: 'Hello' })
  })

  it('uses the documented paths for claim, replies and workload', async () =>
  {
    const fetch = mockFetch()
    await handoffApi.claimCase('tok', 'case-1')
    await handoffApi.listReplies('tok', 'case-1')
    await handoffApi.myWorkload('tok')

    expect(fetch.mock.calls.map(([url, options]) => `${options.method} ${url}`)).toEqual([
      'POST /api/v1/agent/cases/case-1/claim',
      'GET /api/v1/agent/cases/case-1/replies',
      'GET /api/v1/agent/workload',
    ])
  })
})

describe('pathwaysApi', () =>
{
  it('requests recommendations with the limit as a query parameter', async () =>
  {
    const fetch = mockFetch({ recommendations: [] })
    await pathwaysApi.recommended('tok', 3)
    expect(fetch.mock.calls[0][0]).toBe('/api/v1/pathways/recommended?limit=3')
  })
})
