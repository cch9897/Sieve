import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Minimum contract for any pollable task status: must expose a `running` boolean.
 * Additional fields (finished, exit_code, log, ...) are passed through unchanged.
 */
export interface TaskStatus {
  running: boolean
}

export interface UseTaskPollerOptions<S extends TaskStatus> {
  /** Async fetcher that returns the latest task status. */
  statusFn: () => Promise<S>
  /** Interval in ms between polls (default 3000, matching the original StatsView cadence). */
  intervalMs?: number
  /** Optional callback invoked once when polling stops because `running === false`. */
  onStop?: (status: S) => void
  /** Optional label used in console.error logs (e.g. "retrain", "pack"). */
  label?: string
}

export interface UseTaskPollerResult<S extends TaskStatus> {
  status: S | null
  /** Whether a setInterval is currently armed. */
  isPolling: boolean
  /** Imperatively replace the cached status (e.g. when kicking off a new task). */
  setStatus: (s: S | null) => void
  /** Begin polling. No-op if already polling. */
  start: () => void
  /** Stop polling immediately. */
  stop: () => void
}

/**
 * Generic ML-task poller. Calls `statusFn` every `intervalMs` until the response
 * reports `running === false`, then clears the interval and (optionally) fires
 * `onStop`. Auto-cleans up on unmount.
 *
 * Mirrors the four near-identical poll loops that previously lived in
 * StatsView (retrain / pack / vscore / tag-train).
 */
export function useTaskPoller<S extends TaskStatus>(
  options: UseTaskPollerOptions<S>,
): UseTaskPollerResult<S> {
  const { statusFn, intervalMs = 3000, onStop, label } = options
  const [status, setStatus] = useState<S | null>(null)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  // Stash callbacks/fn in refs so start() doesn't re-create on every render
  // and we never end up with stale closures inside the interval body.
  const statusFnRef = useRef(statusFn)
  const onStopRef = useRef(onStop)
  const labelRef = useRef(label)

  useEffect(() => { statusFnRef.current = statusFn }, [statusFn])
  useEffect(() => { onStopRef.current = onStop }, [onStop])
  useEffect(() => { labelRef.current = label }, [label])

  const stop = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  const start = useCallback(() => {
    if (intervalRef.current) return
    intervalRef.current = setInterval(async () => {
      try {
        const s = await statusFnRef.current()
        setStatus(s)
        if (!s.running) {
          if (intervalRef.current) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
          }
          onStopRef.current?.(s)
        }
      } catch (e) {
        const tag = labelRef.current ? `${labelRef.current} polling failed:` : 'polling failed:'
        console.error(tag, e)
      }
    }, intervalMs)
  }, [intervalMs])

  // Auto-cleanup on unmount.
  useEffect(() => () => stop(), [stop])

  return {
    status,
    isPolling: intervalRef.current !== null,
    setStatus,
    start,
    stop,
  }
}
