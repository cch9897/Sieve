import { useState, useCallback } from 'react'
import type { NovelFilterState, PersistedState } from './usePersistedState'

export function useNovelFilters(initial: PersistedState) {
  const [novelState, setNovelState] = useState<NovelFilterState>({
    search: initial.novelSearch,
    date: initial.novelDate,
    sort: initial.novelSort,
    page: initial.novelPage,
  })

  const handleNovelStateChange = useCallback((patch: Partial<NovelFilterState>) => {
    setNovelState(prev => ({ ...prev, ...patch }))
  }, [])

  return { novelState, handleNovelStateChange }
}
