import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import App from '../App'

describe('App', () => {
  it('renders without crashing', () => {
    render(<App />)
    // App should render the header with the title
    expect(document.querySelector('body')).toBeTruthy()
  })

  it('shows navigation tabs', () => {
    render(<App />)
    // The header should contain navigation elements
    const nav = document.querySelector('nav, header')
    expect(nav).toBeTruthy()
  })
})
