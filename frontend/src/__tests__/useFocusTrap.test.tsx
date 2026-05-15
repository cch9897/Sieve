import { describe, it, expect, afterEach } from 'vitest'
import { render, fireEvent, cleanup } from '@testing-library/react'
import { useFocusTrap } from '../hooks/useFocusTrap'

function TrapHarness({ active }: { active: boolean }) {
  const ref = useFocusTrap(active)
  return (
    <div>
      <button data-testid="outside-before">outside-before</button>
      <div ref={ref} data-testid="container">
        <button data-testid="b1">one</button>
        <button data-testid="b2">two</button>
        <button data-testid="b3">three</button>
      </div>
      <button data-testid="outside-after">outside-after</button>
    </div>
  )
}

// jsdom does not lay out elements, so offsetParent is null by default for
// non-attached subtrees. Patch it onto HTMLElement so the focus trap considers
// our buttons visible.
function withVisibleOffsetParents(run: () => void) {
  const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetParent')
  Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
    configurable: true,
    get() { return document.body },
  })
  try { run() } finally {
    if (desc) {
      Object.defineProperty(HTMLElement.prototype, 'offsetParent', desc)
    } else {
      delete (HTMLElement.prototype as { offsetParent?: unknown }).offsetParent
    }
  }
}

describe('useFocusTrap', () => {
  afterEach(() => {
    cleanup()
  })

  it('focuses the first focusable element when active', () => {
    withVisibleOffsetParents(() => {
      const { getByTestId } = render(<TrapHarness active={true} />)
      expect(document.activeElement).toBe(getByTestId('b1'))
    })
  })

  it('Tab on the last focusable wraps focus to the first', () => {
    withVisibleOffsetParents(() => {
      const { getByTestId } = render(<TrapHarness active={true} />)
      const b1 = getByTestId('b1')
      const b3 = getByTestId('b3')
      const container = getByTestId('container')

      b3.focus()
      expect(document.activeElement).toBe(b3)

      fireEvent.keyDown(container, { key: 'Tab' })
      expect(document.activeElement).toBe(b1)
    })
  })

  it('Shift+Tab on the first focusable wraps focus to the last', () => {
    withVisibleOffsetParents(() => {
      const { getByTestId } = render(<TrapHarness active={true} />)
      const b1 = getByTestId('b1')
      const b3 = getByTestId('b3')
      const container = getByTestId('container')

      b1.focus()
      expect(document.activeElement).toBe(b1)

      fireEvent.keyDown(container, { key: 'Tab', shiftKey: true })
      expect(document.activeElement).toBe(b3)
    })
  })

  it('does not move focus when active=false', () => {
    withVisibleOffsetParents(() => {
      const outside = document.createElement('button')
      outside.setAttribute('data-testid', 'preexisting')
      document.body.appendChild(outside)
      outside.focus()
      expect(document.activeElement).toBe(outside)

      render(<TrapHarness active={false} />)
      // The hook is inert, so focus must remain on the pre-existing button.
      expect(document.activeElement).toBe(outside)
      document.body.removeChild(outside)
    })
  })
})
