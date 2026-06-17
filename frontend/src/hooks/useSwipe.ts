import { useCallback, useRef, useState } from 'react'

export type SwipeDirection = 'left' | 'right' | 'up' | null

interface SwipeState {
  /** Live translate offset in px during drag, null when not dragging */
  dx: number
  dy: number
  dragging: boolean
}

interface UseSwipeOptions {
  /** Minimum drag distance to trigger (px) */
  threshold?: number
  /** Called when a swipe is committed (past threshold on release) */
  onSwipe: (dir: SwipeDirection) => void
}

/**
 * Drag-to-swipe hook for card-style UIs (Tinder-like labelers).
 * Returns event handlers + live transform state.
 *
 * Uses pointer events for unified mouse/touch support.
 */
export function useSwipe({ threshold = 80, onSwipe }: UseSwipeOptions) {
  const [state, setState] = useState<SwipeState>({ dx: 0, dy: 0, dragging: false })
  const start = useRef<{ x: number; y: number } | null>(null)
  const onSwipeRef = useRef(onSwipe)
  onSwipeRef.current = onSwipe

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    // Only respond to primary button or touch
    if (e.button !== undefined && e.button !== 0) return
    start.current = { x: e.clientX, y: e.clientY }
    setState({ dx: 0, dy: 0, dragging: true })
  }, [])

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!start.current) return
    const dx = e.clientX - start.current.x
    const dy = e.clientY - start.current.y
    setState({ dx, dy, dragging: true })
  }, [])

  const onPointerUp = useCallback(() => {
    if (!start.current) return
    const { dx, dy } = state
    start.current = null
    setState({ dx: 0, dy: 0, dragging: false })

    const absX = Math.abs(dx)
    const absY = Math.abs(dy)

    if (absX > threshold && absX > absY) {
      onSwipeRef.current(dx > 0 ? 'right' : 'left')
    } else if (absY > threshold && absY > absX * 0.75) {
      onSwipeRef.current('up')
    } else {
      onSwipeRef.current(null)
    }
  }, [state, threshold])

  const onPointerCancel = useCallback(() => {
    start.current = null
    setState({ dx: 0, dy: 0, dragging: false })
  }, [])

  return {
    state,
    handlers: {
      onPointerDown,
      onPointerMove,
      onPointerUp,
      onPointerCancel,
    },
  }
}

/** Convert swipe state to CSS transform string for card drag */
export function swipeTransform(dx: number, dy: number): string {
  const rotation = Math.max(-12, Math.min(12, dx / 12))
  return `translate(${dx}px, ${dy}px) rotate(${rotation}deg)`
}
