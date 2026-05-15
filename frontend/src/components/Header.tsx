import SegmentedTabs from './SegmentedTabs'
import type { View } from '../types'

interface HeaderProps {
  view: View
  onViewChange: (v: View) => void
}

const tabs: { key: HeaderProps['view']; label: string }[] = [
  { key: 'gallery', label: '图库' },
  { key: 'novels', label: '小说' },
  { key: 'labeler', label: '标注' },
  { key: 'danbooru', label: 'Danbooru' },
  { key: 'stats', label: '统计' },
]

export default function Header({ view, onViewChange }: HeaderProps) {
  return (
    <header className="sticky top-0 z-40 px-2 pt-2 md:px-6 md:pt-6">
      <div className="editorial-panel mx-auto max-w-[1920px] overflow-hidden rounded-[28px]">
        <div className="flex flex-col gap-2 px-4 py-2 md:flex-row md:items-end md:justify-between md:px-8 md:py-4">
          <div className="max-w-3xl">
            <div className="micro-label text-[10px] md:text-[11px]">Sieve / Private Archive</div>
            <div className="mt-0.5 flex flex-col gap-1 md:flex-row md:items-end md:justify-between">
              <div>
                <h1 className="editorial-title text-lg leading-none text-[var(--text)] md:text-4xl">档案馆式浏览</h1>
                <p className="mt-1 hidden max-w-xl text-sm leading-6 text-[var(--muted)] md:block md:text-[15px]">以来源、日期与媒介重排你的本地收藏，把图库、小说与标注工具收束进一套更安静、但更有戏剧性的界面里。</p>
              </div>
            </div>
          </div>

          <div className="md:self-center">
            <nav aria-label="主导航" className="overflow-x-auto pb-1 md:pb-0">
              <SegmentedTabs value={view} options={tabs} onChange={onViewChange} ariaLabel="主导航" />
            </nav>
          </div>
        </div>
        <div className="hairline" />
      </div>
    </header>
  )
}

