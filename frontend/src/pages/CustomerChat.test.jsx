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

  it('lets the member pick a model and sends the choice with the message', async () =>
  {
    vi.spyOn(api, 'createConversation').mockResolvedValue({ conversationId: 'conv-9' })
    vi.spyOn(api, 'listProviders').mockResolvedValue([
      { providerId: 'anthropic', label: 'Claude', model: 'claude-haiku-4-5-20251001', isDefault: true },
      { providerId: 'openai', label: 'ChatGPT', model: 'gpt-6-luna', isDefault: false },
    ])
    vi.spyOn(api, 'sendMessage').mockResolvedValue({
      conversationId: 'conv-9',
      messageId: 'msg-9',
      response: 'Network+ builds on your A+.',
      status: 'ANSWERED',
      escalationReason: null,
      answeredBy: 'openai',
    })

    render(<CustomerChat session={session} />)
    await userEvent.selectOptions(await screen.findByLabelText('AI model'), 'openai')
    await userEvent.type(screen.getByLabelText('Message'), 'Which certification next?')
    await userEvent.click(screen.getByRole('button', { name: 'Send' }))

    await waitFor(() =>
      expect(api.sendMessage).toHaveBeenCalledWith('test-token', 'conv-9', 'Which certification next?', 'openai'),
    )
    expect(await screen.findByText('Answered by ChatGPT')).toBeInTheDocument()
  })

  it('hides the picker when only one model is available', async () =>
  {
    vi.spyOn(api, 'createConversation').mockResolvedValue({ conversationId: 'conv-10' })
    vi.spyOn(api, 'listProviders').mockResolvedValue([
      { providerId: 'mock', label: 'Demo assistant (no AI key)', model: 'mock', isDefault: true },
    ])
    render(<CustomerChat session={session} />)
    await waitFor(() => expect(api.listProviders).toHaveBeenCalled())
    expect(screen.queryByLabelText('AI model')).not.toBeInTheDocument()
  })
})

