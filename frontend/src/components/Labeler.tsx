import { useState } from 'react'
import type { LabelerTab } from '../types'
import SubTabs from './SubTabs'
import ReviewMode from './labeler/ReviewMode'
import HistoryMode from './labeler/HistoryMode'
import StatsMode from './labeler/StatsMode'

const TABS: { key: LabelerTab; label: string }[] = [
  { key: 'review', label: '审阅' },
  { key: 'history', label: '历史' },
  { key: 'stats', label: '统计' },
]

export default function Labeler() {
  const [tab, setTab] = useState<LabelerTab>('review')

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-6">
        <SubTabs value={tab} options={TABS} onChange={setTab} ariaLabel="标注模式" />
      </div>

      {tab === 'review' && <ReviewMode />}
      {tab === 'history' && <HistoryMode />}
      {tab === 'stats' && <StatsMode />}
    </div>
  )
}
