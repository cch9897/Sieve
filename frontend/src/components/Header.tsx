import SegmentedTabs from './SegmentedTabs'

interface HeaderProps {
  view: 'gallery' | 'novels' | 'labeler' | 'danbooru' | 'stats'
  onViewChange: (v: 'gallery' | 'novels' | 'labeler' | 'danbooru' | 'stats') => void
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
    <header className="sticky top-0 z-40 border-b border-dark-700/50 bg-dark-950/88 backdrop-blur-xl">
      <div className="mx-auto flex h-auto max-w-[1920px] items-center justify-between px-4 py-3 md:h-16 md:py-0">
        <div>
          <h1 className="text-lg font-semibold tracking-tight text-dark-50">Booru Gallery</h1>
          <p className="mt-0.5 hidden text-xs text-dark-500 md:block">本地收藏库，按图、小说和来源快速浏览。</p>
        </div>
        <nav className="hidden md:block">
          <SegmentedTabs value={view} options={tabs} onChange={onViewChange} />
        </nav>
      </div>
    </header>
  )
}
