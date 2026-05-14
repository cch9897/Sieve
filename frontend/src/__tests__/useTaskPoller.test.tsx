import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useTaskPoller } from '../hooks/useTaskPoller'

describe('useTaskPoller', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('starts in a non-polling state with status=null', () => {
    const statusFn = vi.fn().mockResolvedValue({ running: true })
    const { result } = renderHook(() => useTaskPoller({ statusFn }))
    expect(result.current.status).toBeNull()
    expect(result.current.isPolling).toBe(false)
    expect(statusFn).not.toHaveBeenCalled()
  })

  it('start() begins polling and updates status on each tick', async () => {
    const statusFn = vi.fn().mockResolvedValue({ running: true })
    const { result } = renderHook(() => useTaskPoller({ statusFn, intervalMs: 1000 }))

    act(() => {
      result.current.start()
    })
    // Advance one interval and flush microtasks for the awaited statusFn().
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000)
    })
    expect(statusFn).toHaveBeenCalledTimes(1)
    expect(result.current.status).toEqual({ running: true })
  })

  it('stops auto-polling when running=false and fires onStop', async () => {
    const onStop = vi.fn()
    const statusFn = vi.fn()
      .mockResolvedValueOnce({ running: true })
      .mockResolvedValueOnce({ running: false, finished: true, exit_code: 0, log: 'done' })

    const { result } = renderHook(() => useTaskPoller({ statusFn, intervalMs: 1000, onStop }))

    act(() => { result.current.start() })

    // First tick: still running.
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(result.current.status).toMatchObject({ running: true })

    // Second tick: running=false → must clear interval + call onStop.
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(onStop).toHaveBeenCalledTimes(1)
    expect(onStop).toHaveBeenCalledWith({ running: false, finished: true, exit_code: 0, log: 'done' })

    // Subsequent ticks must NOT call statusFn again.
    const previousCalls = statusFn.mock.calls.length
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    expect(statusFn.mock.calls.length).toBe(previousCalls)
  })

  it('stop() halts polling immediately', async () => {
    const statusFn = vi.fn().mockResolvedValue({ running: true })
    const { result } = renderHook(() => useTaskPoller({ statusFn, intervalMs: 1000 }))

    act(() => { result.current.start() })
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(statusFn).toHaveBeenCalledTimes(1)

    act(() => { result.current.stop() })
    await act(async () => { await vi.advanceTimersByTimeAsync(5000) })
    // No additional calls after stop.
    expect(statusFn).toHaveBeenCalledTimes(1)
  })

  it('start() is idempotent — re-calling does not stack intervals', async () => {
    const statusFn = vi.fn().mockResolvedValue({ running: true })
    const { result } = renderHook(() => useTaskPoller({ statusFn, intervalMs: 1000 }))

    act(() => { result.current.start() })
    act(() => { result.current.start() })  // second call must be a no-op

    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(statusFn).toHaveBeenCalledTimes(1)
  })

  it('cleans up interval on unmount', async () => {
    const statusFn = vi.fn().mockResolvedValue({ running: true })
    const { result, unmount } = renderHook(() => useTaskPoller({ statusFn, intervalMs: 1000 }))

    act(() => { result.current.start() })
    unmount()

    await vi.advanceTimersByTimeAsync(5000)
    // After unmount, no further calls should fire.
    expect(statusFn).not.toHaveBeenCalled()
  })

  it('logs and continues polling when statusFn rejects', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    const statusFn = vi.fn()
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ running: true })

    const { result } = renderHook(() => useTaskPoller({ statusFn, intervalMs: 1000, label: 'retrain' }))

    act(() => { result.current.start() })

    // First tick errors.
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(consoleSpy).toHaveBeenCalled()
    const firstCall = consoleSpy.mock.calls[0]
    expect(String(firstCall[0])).toContain('retrain')

    // Second tick recovers.
    await act(async () => { await vi.advanceTimersByTimeAsync(1000) })
    expect(result.current.status).toEqual({ running: true })
    expect(statusFn).toHaveBeenCalledTimes(2)
  })

  it('setStatus imperatively replaces cached status', () => {
    const statusFn = vi.fn().mockResolvedValue({ running: true })
    const { result } = renderHook(() => useTaskPoller({ statusFn, intervalMs: 1000 }))

    act(() => { result.current.setStatus({ running: true, finished: false } as any) })
    expect(result.current.status).toEqual({ running: true, finished: false })
  })
})
