import { useEffect, useState } from 'react'
import { pathwaysApi } from '../api/pathways.js'
import { api } from '../api/client.js'

/**
 * "Recommended next steps" panel beside the member's chat.
 *
 * OWNER: Benjamin Madden (Integration Lead)
 *
 * The list is ranked on the server from the member's own record, so this
 * component only has to load it once and explain each item. It deliberately
 * shows the reason ("Next step after CompTIA A+") ahead of the score: a person
 * decides whether to follow a suggestion by whether the reason makes sense to
 * them, not by a number.
 */

const STRENGTH_LABELS = {
  STRONG: 'Strong match',
  GOOD: 'Good match',
  EXPLORATORY: 'Worth a look',
}

const KIND_LABELS = {
  CERTIFICATION: 'Certification',
  DEGREE: 'Degree',
  PROGRAM: 'Program',
  LICENSE: 'License',
  APPRENTICESHIP: 'Apprenticeship',
}

function reasonText(item)
{
  if (item.reason === 'NEXT_STEP') return `Next step after ${item.buildsOn}`
  if (item.reason === 'BUILDS_ON' && item.buildsOn) return `Builds on ${item.buildsOn}`
  return 'A common starting point'
}

// Five cards in a 340px column is a wall. Three is a shortlist someone will
// actually read, and the rest are one click away.
const SHOWN_BY_DEFAULT = 3

export default function PathwayRecommendations({ session, refreshKey = 0, onPlanned })
{
  const [state, setState] = useState({ status: 'loading', data: null, error: null })
  const [showAll, setShowAll] = useState(false)
  const [planning, setPlanning] = useState(null)
  const [planError, setPlanError] = useState(null)

  /**
   * Put a suggestion on the member's development plan.
   *
   * It is saved as a GOAL, never as a credential: the member intends to do
   * this, they have not done it. The list then re-ranks without it, so
   * choosing something moves the member on rather than leaving them looking
   * at a decision they have already made. Choosing the same thing twice is
   * not an error worth showing -- it is already on the plan either way.
   */
  async function addToPlan(item)
  {
    setPlanning(item.pathwayId)
    setPlanError(null)
    try
    {
      await api.addRecordItem(session.token, 'GOAL', item.title, '')
      if (onPlanned) onPlanned()
    }
    catch (caught)
    {
      if (caught.code !== 'RECORD_ITEM_EXISTS')
      {
        setPlanError(`${caught.message} (${caught.code})`)
      }
      else if (onPlanned)
      {
        onPlanned()
      }
    }
    finally
    {
      setPlanning(null)
    }
  }

  // refreshKey changes whenever My record changes, so the list is re-ranked
  // against the member's latest record without a page reload.
  useEffect(() =>
  {
    let cancelled = false

    pathwaysApi
      .recommended(session.token, 5)
      .then((data) =>
      {
        if (!cancelled) setState({ status: 'ready', data, error: null })
      })
      .catch((error) =>
      {
        if (!cancelled) setState({ status: 'error', data: null, error })
      })

    // A sign-out while the request is in flight must not update an unmounted panel.
    return () =>
    {
      cancelled = true
    }
  }, [session.token, refreshKey])

  return (
    <aside className="card pathways" aria-labelledby="pathways-heading">
      <h2 id="pathways-heading">Recommended next steps</h2>

      {state.status === 'loading' && <p className="muted">Looking at your record…</p>}

      {state.status === 'error' && (
        <p className="error" role="alert">
          Recommendations are unavailable right now ({state.error.code}).
        </p>
      )}

      {state.status === 'ready' && (
        <>
          <p className="muted">
            {state.data.basis === 'COMPLETED_TRAINING'
              ? 'Based on the training and credentials on your record.'
              : 'Nothing on your record matched yet, so these are common starting points.'}
          </p>

          <ol className="pathway-list">
            {(showAll
              ? state.data.recommendations
              : state.data.recommendations.slice(0, SHOWN_BY_DEFAULT)
            ).map((item, index) => (
              <li
                key={item.pathwayId}
                className={`pathway ${index === 0 ? 'top' : ''}`}
              >
                {/* The rank is the first thing read, so the strongest match is
                    obvious without comparing five pills to each other. */}
                <span className="pathway-rank" aria-hidden="true">{index + 1}</span>
                <div className="pathway-head">
                  <strong>{item.title}</strong>
                  <span className={`pill strength ${item.strength.toLowerCase()}`}>
                    {STRENGTH_LABELS[item.strength] ?? item.strength}
                  </span>
                </div>
                <p className="pathway-meta">
                  {KIND_LABELS[item.kind] ?? item.kind} &middot; {item.field}
                </p>
                <p className="pathway-reason">{reasonText(item)}</p>
                <p className="pathway-summary">{item.summary}</p>
                {item.matchedTerms.length > 0 && (
                  <p className="pathway-meta">Matched on {item.matchedTerms.join(', ')}</p>
                )}
                <button
                  type="button"
                  className="secondary pathway-add"
                  disabled={planning === item.pathwayId}
                  onClick={() => addToPlan(item)}
                >
                  {planning === item.pathwayId ? 'Adding…' : 'Add to my plan'}
                </button>
              </li>
            ))}
          </ol>

          {state.data.recommendations.length > SHOWN_BY_DEFAULT && (
            <button type="button" className="link" onClick={() => setShowAll(!showAll)}>
              {showAll
                ? 'Show fewer'
                : `Show ${state.data.recommendations.length - SHOWN_BY_DEFAULT} more`}
            </button>
          )}

          {planError && (
            <p className="error" role="alert">{planError}</p>
          )}

          <p className="muted disclaimer">{state.data.disclaimer}</p>
        </>
      )}
    </aside>
  )
}
