import { useState } from 'react'
import type { DanbooruLabelerTab } from '../types'
import SubTabs from './SubTabs'
import ReviewMode from './danbooru-labeler/ReviewMode'
import HistoryMode from './danbooru-labeler/HistoryMode'
import StatsMode from './danbooru-labeler/StatsMode'
import RecommendedMode from './danbooru-labeler/RecommendedMode'

const TABS: { key: DanbooruLabelerTab; label: string }[] = [
  { key: 'review', label: '审阅' },
  { key: 'recommended', label: '推荐' },
  { key: 'history', label: '历史' },
  { key: 'stats', label: '统计' },
]

export default function DanbooruLabeler() {
  const [tab, setTab] = useState<DanbooruLabelerTab>('review')

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6">
        <SubTabs value={tab} options={TABS} onChange={setTab} ariaLabel="Danbooru 标注模式" />
      </div>

      {tab === 'review' && <ReviewMode />}
      {tab === 'recommended' && <RecommendedMode />}
      {tab === 'history' && <HistoryMode />}
      {tab === 'stats' && <StatsMode />}
    </div>
  )
}
