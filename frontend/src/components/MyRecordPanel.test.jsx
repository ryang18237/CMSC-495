import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MyRecordPanel from './MyRecordPanel.jsx'
import { api, ApiError } from '../api/client.js'

const session = { token: 'tok', role: 'CUSTOMER', displayName: 'Alex Rivera' }

const RECORD = {
  serviceRecord: {
    serviceBranch: 'Army',
    occupationalSpecialty: 'Information Technology Specialist',
    completedTraining: ['Network Administration Course'],
    credentials: ['CompTIA A+'],
  },
  added: [
    { itemId: 'i1', kind: 'CREDENTIAL', name: 'CompTIA Security+', source: 'MANUAL', addedAt: 'x' },
  ],
}

afterEach(() =>
{
  vi.restoreAllMocks()
})

describe('MyRecordPanel', () =>
{
  it('shows the service record and what the member added', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue(RECORD)
    render(<MyRecordPanel session={session} />)

    expect(await screen.findByText('CompTIA A+')).toBeInTheDocument()
    expect(screen.getByText('Network Administration Course')).toBeInTheDocument()
    expect(screen.getByText('CompTIA Security+')).toBeInTheDocument()
  })

  it('adds an item, reloads, and tells the parent', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue(RECORD)
    vi.spyOn(api, 'addRecordItem').mockResolvedValue({})
    const onChange = vi.fn()
    render(<MyRecordPanel session={session} onChange={onChange} />)

    await userEvent.selectOptions(await screen.findByLabelText('Type'), 'TRAINING')
    await userEvent.type(screen.getByLabelText('Name'), 'Lean Six Sigma Yellow Belt')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() =>
      expect(api.addRecordItem).toHaveBeenCalledWith('tok', 'TRAINING', 'Lean Six Sigma Yellow Belt'),
    )
    await waitFor(() => expect(onChange).toHaveBeenCalled())
    expect(api.getRecord).toHaveBeenCalledTimes(2)
  })

  it('removes an item the member added', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue(RECORD)
    vi.spyOn(api, 'removeRecordItem').mockResolvedValue(null)
    render(<MyRecordPanel session={session} />)

    await userEvent.click(await screen.findByRole('button', { name: 'Remove CompTIA Security+' }))
    await waitFor(() => expect(api.removeRecordItem).toHaveBeenCalledWith('tok', 'i1'))
  })

  it('previews an upload and saves only the ticked items', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue({ ...RECORD, added: [] })
    vi.spyOn(api, 'importRecord').mockResolvedValue({
      candidates: [
        { kind: 'CREDENTIAL', name: 'Cisco CCNA' },
        { kind: 'TRAINING', name: 'Basic Leader Course' },
      ],
      skippedLines: 2,
    })
    vi.spyOn(api, 'addRecordItems').mockResolvedValue({ added: [], alreadyOnRecord: 0 })
    render(<MyRecordPanel session={session} />)

    const file = new File(['Cisco CCNA\nBasic Leader Course'], 'list.txt', { type: 'text/plain' })
    await userEvent.upload(await screen.findByLabelText(/upload a list/i), file)

    expect(await screen.findByText('Cisco CCNA')).toBeInTheDocument()
    expect(api.importRecord).toHaveBeenCalledWith('tok', 'list.txt', expect.any(String))

    await userEvent.click(screen.getByRole('checkbox', { name: /Basic Leader Course/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Save 1 item' }))

    await waitFor(() =>
      expect(api.addRecordItems).toHaveBeenCalledWith('tok', [{ kind: 'CREDENTIAL', name: 'Cisco CCNA' }]),
    )
  })

  it('shows the error code when an item is refused', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue(RECORD)
    vi.spyOn(api, 'addRecordItem').mockRejectedValue(
      new ApiError(409, 'RECORD_ITEM_EXISTS', 'That item is already on your record.', 'r'),
    )
    render(<MyRecordPanel session={session} />)

    await userEvent.type(await screen.findByLabelText('Name'), 'CompTIA Security+')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('RECORD_ITEM_EXISTS')
  })
})
