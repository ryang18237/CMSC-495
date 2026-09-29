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
    {
      itemId: 'i2',
      kind: 'EDUCATION',
      name: 'Associate of Applied Science',
      organization: 'Central Texas College',
      source: 'MANUAL',
      addedAt: 'x',
    },
  ],
  completeness: { percent: 60, missingKinds: ['TRAINING', 'EXPERIENCE'] },
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

  it('groups items by kind and shows the organisation', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue(RECORD)
    render(<MyRecordPanel session={session} />)

    expect(await screen.findByRole('heading', { name: 'Education' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Credential' })).toBeInTheDocument()
    expect(screen.getByText('Central Texas College', { exact: false })).toBeInTheDocument()
  })

  it('shows how complete the profile is and what is missing', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue(RECORD)
    render(<MyRecordPanel session={session} />)

    expect(await screen.findByText(/60% complete/)).toBeInTheDocument()
    expect(screen.getByText(/add training, experience/)).toBeInTheDocument()
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '60')
  })

  it('adds an item with its employer, reloads, and tells the parent', async () =>
  {
    vi.spyOn(api, 'getRecord').mockResolvedValue(RECORD)
    vi.spyOn(api, 'addRecordItem').mockResolvedValue({})
    const onChange = vi.fn()
    render(<MyRecordPanel session={session} onChange={onChange} />)

    await userEvent.selectOptions(await screen.findByLabelText('Type'), 'EXPERIENCE')
    await userEvent.type(screen.getByLabelText('Name'), 'Help Desk Technician')
    await userEvent.type(screen.getByLabelText('Issuer, school or employer'), 'Fort Hood')
    await userEvent.click(screen.getByRole('button', { name: 'Add' }))

    await waitFor(() =>
      expect(api.addRecordItem).toHaveBeenCalledWith(
        'tok',
        'EXPERIENCE',
        'Help Desk Technician',
        'Fort Hood',
      ),
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
        { kind: 'EXPERIENCE', name: 'Basic Leader Course', organization: 'Fort Hood' },
      ],
      skippedLines: 2,
    })
    vi.spyOn(api, 'addRecordItems').mockResolvedValue({ added: [], alreadyOnRecord: 0 })
    render(<MyRecordPanel session={session} />)

    const file = new File(['Cisco CCNA\nBasic Leader Course'], 'list.txt', { type: 'text/plain' })
    await userEvent.upload(await screen.findByLabelText(/upload a resume/i), file)

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
