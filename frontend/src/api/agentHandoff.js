/**
 * Human agent escalation path -- client calls.
 *
 * OWNER: Benjamin Madden (Integration Lead)
 *
 * Kept in its own file rather than added to `client.js` so the escalation path
 * merges as one unit. Once it lands, folding these four calls into the `api`
 * object in `client.js` is a tidy-up worth doing -- they use the same
 * `request` helper and get the same error translation for free.
 */

import { request } from './client.js'

export const handoffApi = {
  // Post a counsellor's reply into the member's conversation. Replying also
  // claims the case, so there is no need to claim first.
  replyToMember: (token, caseId, message) =>
    request(`/api/v1/agent/cases/${caseId}/reply`, {
      method: 'POST',
      token,
      body: { message },
    }),

  // Take a case without replying yet -- for reading a long thread first while
  // letting colleagues see it is being handled.
  claimCase: (token, caseId) =>
    request(`/api/v1/agent/cases/${caseId}/claim`, { method: 'POST', token }),

  listReplies: (token, caseId) => request(`/api/v1/agent/cases/${caseId}/replies`, { token }),

  myWorkload: (token) => request('/api/v1/agent/workload', { token }),
}
