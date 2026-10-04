/**
 * Pathway recommendations -- client call.
 *
 * OWNER: Benjamin Madden (Integration Lead)
 *
 * Uses the shared `request` helper, so a failure arrives as the same
 * `ApiError` every other screen already knows how to show.
 */

import { request } from './client.js'

export const pathwaysApi = {
  recommended: (token, limit = 5) =>
    request(`/api/v1/pathways/recommended?limit=${encodeURIComponent(limit)}`, { token }),
}
