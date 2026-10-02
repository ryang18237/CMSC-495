import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

/**
 * My profile -- what the member has done, entered once.
 *
 * The service record comes from the personnel system and is shown read-only;
 * it only ever holds military training. Everything else -- certifications
 * earned since, degrees, jobs -- the member enters here, by typing it or by
 * uploading a resume or transcript. All of it is used by every conversation
 * and every recommendation from then on.
 *
 * An upload never saves on its own: the file is read on the server, likely
 * items come back, and the member ticks the ones to keep.
 */

const KIND_LABELS = {
  CREDENTIAL: 'Credential',
  TRAINING: 'Training',
  EDUCATION: 'Education',
  EXPERIENCE: 'Experience',
}

// The order the panel groups them in: what a career conversation asks about
// first comes first.
const KIND_ORDER = ['CREDENTIAL', 'EDUCATION', 'EXPERIENCE', 'TRAINING']

// An empty card should say what belongs in it, in the member's own terms.
const EMPTY_HINTS = {
  CREDENTIAL: 'Certifications and licences you hold, such as CompTIA Security+.',
  TRAINING: 'Military or civilian courses you have completed.',
  EDUCATION: 'Degrees and programmes, finished or in progress.',
  EXPERIENCE: 'Roles you have held, military or civilian.',
}

// A worked example beats a label: people fill a field faster when they can
// see the shape of the answer.
const PLACEHOLDERS = {
  CREDENTIAL: { name: 'e.g. CompTIA Security+', organization: 'Issuer (optional)' },
  TRAINING: { name: 'e.g. Basic Leader Course', organization: 'Where (optional)' },
  EDUCATION: { name: 'e.g. Associate of Applied Science', organization: 'School (optional)' },
  EXPERIENCE: { name: 'e.g. Help Desk Technician', organization: 'Employer (optional)' },
}

function readAsBase64(file)
{
  return new Promise((resolve, reject) =>
  {
    const reader = new FileReader()
    reader.onload = () =>
    {
      // "data:<type>;base64,<content>" -- keep only the content.
      const result = String(reader.result)
      resolve(result.slice(result.indexOf(',') + 1))
    }
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

export default function MyRecordPanel({ session, onChange })
{
  const [record, setRecord] = useState(null)
  const [kind, setKind] = useState('CREDENTIAL')
  const [name, setName] = useState('')
  const [organization, setOrganization] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const [candidates, setCandidates] = useState(null)
  const [chosen, setChosen] = useState({})
  const fileRef = useRef(null)

  const load = useCallback(async () =>
  {
    try
    {
      setRecord(await api.getRecord(session.token))
    }
    catch (caught)
    {
      setError(`${caught.message} (${caught.code})`)
    }
  }, [session.token])

  useEffect(() =>
  {
    load()
  }, [load])

  async function changed()
  {
    await load()
    if (onChange)
    {
      onChange()
    }
  }

  async function add(event)
  {
    event.preventDefault()
    if (!name.trim())
    {
      return
    }
    setBusy(true)
    setError(null)
    try
    {
      await api.addRecordItem(session.token, kind, name, organization)
      setName('')
      setOrganization('')
      await changed()
    }
    catch (caught)
    {
      setError(`${caught.message} (${caught.code})`)
    }
    finally
    {
      setBusy(false)
    }
  }

  async function remove(itemId)
  {
    setError(null)
    try
    {
      await api.removeRecordItem(session.token, itemId)
      await changed()
    }
    catch (caught)
    {
      setError(`${caught.message} (${caught.code})`)
    }
  }

  async function upload(event)
  {
    const file = event.target.files?.[0]
    if (!file)
    {
      return
    }
    setBusy(true)
    setError(null)
    try
    {
      const content = await readAsBase64(file)
      const preview = await api.importRecord(session.token, file.name, content)
      setCandidates(preview.candidates)
      setChosen(Object.fromEntries(preview.candidates.map((_, index) => [index, true])))
    }
    catch (caught)
    {
      setError(`${caught.message} (${caught.code ?? 'READ_ERROR'})`)
    }
    finally
    {
      setBusy(false)
      if (fileRef.current)
      {
        fileRef.current.value = ''
      }
    }
  }

  async function saveChosen()
  {
    const items = candidates.filter((_, index) => chosen[index])
    setBusy(true)
    setError(null)
    try
    {
      if (items.length > 0)
      {
        await api.addRecordItems(session.token, items)
      }
      setCandidates(null)
      await changed()
    }
    catch (caught)
    {
      setError(`${caught.message} (${caught.code})`)
    }
    finally
    {
      setBusy(false)
    }
  }

  const official = record?.serviceRecord
  const added = record?.added ?? []
  const completeness = record?.completeness
  const selectedCount = candidates ? candidates.filter((_, index) => chosen[index]).length : 0

  // Every kind gets a card, empty ones included. Hiding the empty ones made
  // the panel shorter but left no sign that education or experience were
  // things you could add at all.
  const grouped = KIND_ORDER.map((groupKind) => [
    groupKind,
    added.filter((item) => item.kind === groupKind),
  ])

  return (
    <section className="card record" aria-labelledby="record-heading">
      <div className="profile-head">
        <div>
          <h2 id="record-heading">My profile</h2>
          <p className="muted">
            What you have done so far. Saved to your account and used in every
            conversation and recommendation from then on.
          </p>
        </div>
      </div>

      {completeness && (
        <div className="completeness">
          <div
            className="completeness-bar"
            role="progressbar"
            aria-valuenow={completeness.percent}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Profile completeness"
          >
            <span style={{ width: `${completeness.percent}%` }} />
          </div>
          <p className="muted">
            {completeness.percent}% complete
            {completeness.missingKinds.length > 0 && (
              <> &middot; add {completeness.missingKinds.map((k) => KIND_LABELS[k].toLowerCase()).join(', ')}</>
            )}
          </p>
        </div>
      )}

      <div className="profile-grid">
        {official && (
          <div className="record-group official">
            <h3 className="section">From your service record</h3>
            <ul className="record-list official">
              {[...official.credentials, ...official.completedTraining].map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
            <p className="record-empty">Read-only, from the personnel system.</p>
          </div>
        )}

        {grouped.map(([groupKind, items]) => (
          <div className="record-group" key={groupKind}>
            <h3 className="section">{KIND_LABELS[groupKind]}</h3>
            {items.length === 0 ? (
              <p className="record-empty">{EMPTY_HINTS[groupKind]}</p>
            ) : (
              <ul className="record-list">
                {items.map((item) => (
                  <li key={item.itemId}>
                    <span>
                      {item.name}
                      {item.organization && <span className="muted"> &middot; {item.organization}</span>}
                      {item.detail && <span className="muted"> &middot; {item.detail}</span>}
                    </span>
                    <button
                      type="button"
                      className="link"
                      aria-label={`Remove ${item.name}`}
                      onClick={() => remove(item.itemId)}
                    >
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>

      <form className="record-add" onSubmit={add}>
        <label className="visually-hidden" htmlFor="record-kind">Type</label>
        <select id="record-kind" value={kind} onChange={(event) => setKind(event.target.value)}>
          {KIND_ORDER.map((option) => (
            <option key={option} value={option}>
              {KIND_LABELS[option]}
            </option>
          ))}
        </select>
        <label className="visually-hidden" htmlFor="record-name">Name</label>
        <input
          id="record-name"
          value={name}
          maxLength={200}
          placeholder={PLACEHOLDERS[kind].name}
          onChange={(event) => setName(event.target.value)}
        />
        <label className="visually-hidden" htmlFor="record-organization">
          Issuer, school or employer
        </label>
        <input
          id="record-organization"
          className="record-organization"
          value={organization}
          maxLength={200}
          placeholder={PLACEHOLDERS[kind].organization}
          onChange={(event) => setOrganization(event.target.value)}
        />
        <button type="submit" disabled={busy || !name.trim()}>
          Add
        </button>
      </form>

      {/* Typing an entry is the main path. Importing a file is a shortcut for
          someone with a long record, so it stays folded away. */}
      <details className="record-import">
        <summary>Have a resume or transcript? Import it instead</summary>
        <div className="record-upload">
          <label htmlFor="record-file" className="muted">
            .txt, .csv or .pdf. Nothing is saved until you have checked it.
          </label>
          <input
            id="record-file"
            ref={fileRef}
            type="file"
            accept=".txt,.csv,.pdf"
            onChange={upload}
            disabled={busy}
          />
        </div>
      </details>

      {candidates && (
        <div className="record-review" role="group" aria-label="Items found in your file">
          <h3 className="section">Found in your file</h3>
          {candidates.length === 0 && (
            <p className="muted">Nothing that looked like a course or credential. Add items by hand instead.</p>
          )}
          <ul className="record-list">
            {candidates.map((item, index) => (
              <li key={`${item.kind}-${item.name}`}>
                <label>
                  <input
                    type="checkbox"
                    checked={Boolean(chosen[index])}
                    onChange={() => setChosen({ ...chosen, [index]: !chosen[index] })}
                  />
                  <span>
                    {item.name}
                    {item.organization && <span className="muted"> &middot; {item.organization}</span>}
                    <span className="muted"> &middot; {KIND_LABELS[item.kind]}</span>
                  </span>
                </label>
              </li>
            ))}
          </ul>
          <div className="record-actions">
            <button type="button" className="secondary" onClick={() => setCandidates(null)}>
              Cancel
            </button>
            <button type="button" onClick={saveChosen} disabled={busy || selectedCount === 0}>
              Save {selectedCount} {selectedCount === 1 ? 'item' : 'items'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  )
}
