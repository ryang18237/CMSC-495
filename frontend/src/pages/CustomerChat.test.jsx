import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CustomerChat from './CustomerChat.jsx'
import { api } from '../api/client.js'

const session = { token: 'test-token', role: 'CUSTOMER', displayName: 'Alex Rivera' }

afterEach(() =>
{
  vi.restoreAllMocks()
})

describe('CustomerChat', () =>
{
  it('starts a conversation and renders an answered reply', async () =>
  {
    vi.spyOn(api, 'createConversation').mockResolvedValue({ conversationId: 'conv-1' })
    vi.spyOn(api, 'sendMessage').mockResolvedValue({
      conversationId: 'conv-1',
      messageId: 'msg-1',
      response: 'A foundational IT certification is the closest next step.',
      status: 'ANSWERED',
      escalationReason: null,
    })

    render(<CustomerChat session={session} />)
    await waitFor(() => expect(api.createConversation).toHaveBeenCalledWith('test-token'))

    await userEvent.type(screen.getByLabelText('Message'), 'Which certification should I work toward next?')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('A foundational IT certification is the closest next step.')).toBeInTheDocument()
    expect(screen.getByText('Which certification should I work toward next?')).toBeInTheDocument()
  })

  it('labels an escalated reply with the reason', async () =>
  {
    vi.spyOn(api, 'createConversation').mockResolvedValue({ conversationId: 'conv-2' })
    vi.spyOn(api, 'sendMessage').mockResolvedValue({
      conversationId: 'conv-2',
      messageId: 'msg-2',
      response: 'Connecting you with a specialist.',
      status: 'ESCALATED',
      escalationReason: 'SECURITY_CONCERN',
    })

    render(<CustomerChat session={session} />)
    await waitFor(() => expect(api.createConversation).toHaveBeenCalled())

    await userEvent.type(screen.getByLabelText('Message'), 'My account was hacked')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByText('Routed to account security')).toBeInTheDocument()
  })

  it('surfaces the API error code when a message is rejected', async () =>
  {
    vi.spyOn(api, 'createConversation').mockResolvedValue({ conversationId: 'conv-3' })
    vi.spyOn(api, 'sendMessage').mockRejectedValue(
      Object.assign(new Error('Message must contain between 1 and 2000 characters.'), {
        code: 'INVALID_MESSAGE',
      }),
    )

    render(<CustomerChat session={session} />)
    await waitFor(() => expect(api.createConversation).toHaveBeenCalled())

    await userEvent.type(screen.getByLabelText('Message'), 'hello')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('INVALID_MESSAGE')
  })
})
