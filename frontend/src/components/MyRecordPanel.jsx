import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api/client.js'

/**
 * My record -- the member's training and credentials, saved once.
 *
 * The service record comes from the personnel system and is shown read-only.
 * Anything missing from it (a certification earned since, a civilian course)
 * the member adds here, by typing it or by uploading a list. Everything saved
 * is used by every conversation and every recommendation from then on.
 *
 * An upload never saves on its own: the file is read on the server, likely
 * items come back, and the member ticks the ones to keep.
 */

const KIND_LABELS = { TRAINING: 'Training', CREDENTIAL: 'Credential' }

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
      await api.addRecordItem(session.token, kind, name)
      setName('')
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
  const selectedCount = candidates ? candidates.filter((_, index) => chosen[index]).length : 0

  return (
    <section className="card record" aria-labelledby="record-heading">
      <h2 id="record-heading">My record</h2>
      <p className="muted">Saved to your account and used in every conversation.</p>

      {official && (
        <div className="record-group">
          <h3 className="section">From your service record</h3>
          <ul className="record-list official">
            {[...official.credentials, ...official.completedTraining].map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="record-group">
        <h3 className="section">Added by you</h3>
        {added.length === 0 && <p className="muted">Nothing yet. Add anything missing above.</p>}
        <ul className="record-list">
          {added.map((item) => (
            <li key={item.itemId}>
              <span>
                {item.name} <span className="muted">&middot; {KIND_LABELS[item.kind]}</span>
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
      </div>

      <form className="record-add" onSubmit={add}>
        <label className="visually-hidden" htmlFor="record-kind">Type</label>
        <select id="record-kind" value={kind} onChange={(event) => setKind(event.target.value)}>
          <option value="CREDENTIAL">Credential</option>
          <option value="TRAINING">Training</option>
        </select>
        <label className="visually-hidden" htmlFor="record-name">Name</label>
        <input
          id="record-name"
          value={name}
          maxLength={200}
          placeholder="e.g. CompTIA Security+"
          onChange={(event) => setName(event.target.value)}
        />
        <button type="submit" disabled={busy || !name.trim()}>
          Add
        </button>
      </form>

      <div className="record-upload">
        <label htmlFor="record-file" className="muted">
          Or upload a list or transcript (.txt, .csv, .pdf)
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
                  />{' '}
                  {item.name} <span className="muted">&middot; {KIND_LABELS[item.kind]}</span>
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
