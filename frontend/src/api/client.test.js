import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, api, request } from './client.js'

function mockFetch(status, payload)
{
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  })
}

afterEach(() =>
{
  vi.unstubAllGlobals()
})

describe('api client', () =>
{
  it('returns the parsed body on success', async () =>
  {
    vi.stubGlobal('fetch', mockFetch(200, { status: 'healthy' }))
    await expect(api.health()).resolves.toEqual({ status: 'healthy' })
  })

  it('attaches the bearer token', async () =>
  {
    const fetchMock = mockFetch(201, { conversationId: 'abc' })
    vi.stubGlobal('fetch', fetchMock)

    await api.createConversation('token-123')

    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers.Authorization).toBe('Bearer token-123')
    expect(options.method).toBe('POST')
  })

  it('translates the documented error contract into an ApiError', async () =>
  {
    vi.stubGlobal(
      'fetch',
      mockFetch(422, {
        error: {
          code: 'INVALID_MESSAGE',
          message: 'Message must contain between 1 and 2000 characters.',
          requestId: 'req-1',
        },
      }),
    )

    await expect(request('/api/v1/anything')).rejects.toMatchObject({
      status: 422,
      code: 'INVALID_MESSAGE',
      requestId: 'req-1',
    })
  })

  it('reports a network failure without leaking internals', async () =>
  {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('socket hang up')))

    const error = await request('/api/v1/health').catch((caught) => caught)
    expect(error).toBeInstanceOf(ApiError)
    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.message).not.toContain('socket hang up')
  })
})
