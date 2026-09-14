import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import LoginPanel from './LoginPanel.jsx'
import { api } from '../api/client.js'

const SESSION = { accessToken: 'token-1', role: 'CUSTOMER', displayName: 'Alex Rivera' }

afterEach(() =>
{
  vi.restoreAllMocks()
})

describe('LoginPanel', () =>
{
  it('signs in on a single click, with nothing typed', async () =>
  {
    const login = vi.spyOn(api, 'login').mockResolvedValue(SESSION)
    const onSignedIn = vi.fn()

    render(<LoginPanel onSignedIn={onSignedIn} />)
    await userEvent.click(screen.getByRole('button', { name: /Continue as a member/ }))

    await waitFor(() => expect(login).toHaveBeenCalledWith('member@example.com', 'DemoPassw0rd!'))
    expect(onSignedIn).toHaveBeenCalledWith({
      token: 'token-1',
      role: 'CUSTOMER',
      displayName: 'Alex Rivera',
    })
  })

  it('signs in as a counsellor from the second button', async () =>
  {
    const login = vi.spyOn(api, 'login').mockResolvedValue({ ...SESSION, role: 'AGENT' })

    render(<LoginPanel onSignedIn={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /Continue as a counsellor/ }))

    await waitFor(() =>
      expect(login).toHaveBeenCalledWith('counselor@example.com', 'DemoPassw0rd!'),
    )
  })

  it('the manual form is pre-filled, so Sign in also works untouched', async () =>
  {
    const login = vi.spyOn(api, 'login').mockResolvedValue(SESSION)

    render(<LoginPanel onSignedIn={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /email and password instead/ }))
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => expect(login).toHaveBeenCalledWith('member@example.com', 'DemoPassw0rd!'))
  })

  it('surfaces a failed sign-in', async () =>
  {
    vi.spyOn(api, 'login').mockRejectedValue(new Error('Email address or password is incorrect.'))

    render(<LoginPanel onSignedIn={vi.fn()} />)
    await userEvent.click(screen.getByRole('button', { name: /Continue as a member/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('incorrect')
  })
})
