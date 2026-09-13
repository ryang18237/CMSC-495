/**
 * Typed-ish client for the platform API.
 *
 * Every call goes through `request`, which applies the bearer token and
 * translates the documented error contract into a single `ApiError` shape so
 * the UI never has to parse error bodies itself.
 */

const BASE_URL = import.meta.env?.VITE_API_BASE_URL ?? ''

export class ApiError extends Error {
  constructor(status, code, message, requestId) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.requestId = requestId
  }
}

export async function request(path, { method = 'GET', token, body } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  let response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (cause) {
    throw new ApiError(0, 'NETWORK_ERROR', 'Could not reach the service.', null, { cause })
  }

  if (response.status === 204) return null

  let payload = null
  try {
    payload = await response.json()
  } catch {
    payload = null
  }

  if (!response.ok) {
    const error = payload?.error ?? {}
    throw new ApiError(
      response.status,
      error.code ?? 'UNKNOWN_ERROR',
      error.message ?? 'The request could not be completed.',
      error.requestId ?? null,
    )
  }

  return payload
}

export const api = {
  login: (email, password) =>
    request('/api/v1/auth/login', { method: 'POST', body: { email, password } }),

  health: () => request('/api/v1/health'),

  createConversation: (token) => request('/api/v1/conversations', { method: 'POST', token }),

  sendMessage: (token, conversationId, message) =>
    request(`/api/v1/conversations/${conversationId}/messages`, {
      method: 'POST',
      token,
      body: { message },
    }),

  getConversation: (token, conversationId) =>
    request(`/api/v1/conversations/${conversationId}`, { token }),

  escalate: (token, conversationId, reason) =>
    request(`/api/v1/conversations/${conversationId}/escalate`, {
      method: 'POST',
      token,
      body: { reason },
    }),

  sendFeedback: (token, conversationId, messageId, rating, comment) =>
    request(`/api/v1/conversations/${conversationId}/feedback`, {
      method: 'POST',
      token,
      body: { messageId, rating, comment: comment || undefined },
    }),

  listCases: (token) => request('/api/v1/agent/cases', { token }),

  getCase: (token, caseId) => request(`/api/v1/agent/cases/${caseId}`, { token }),

  updateCase: (token, caseId, status) =>
    request(`/api/v1/agent/cases/${caseId}`, { method: 'PATCH', token, body: { status } }),
}
