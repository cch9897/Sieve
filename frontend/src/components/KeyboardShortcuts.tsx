import { useEffect, useState } from 'react'

const SHORTCUTS = [
  { key: 'G', desc: '切到图库' },
  { key: 'N', desc: '切到小说' },
  { key: 'D', desc: '切到标注' },
  { key: 'B', desc: '切到 Danbooru' },
  { key: 'S', desc: '切到统计' },
  { key: 'F', desc: '展开/收起筛选' },
  { key: 'J / K', desc: '下一页 / 上一页（分页模式）' },
  { key: '← / →', desc: '灯箱上一张 / 下一张' },
  { key: 'Z', desc: '灯箱内缩放图片' },
  { key: 'Esc', desc: '关闭灯箱或返回' },
  { key: '?', desc: '打开快捷键帮助' },
]

export default function KeyboardShortcuts() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onOpen = (_e: Event) => { setOpen(true) }
    window.addEventListener('booru-shortcuts-open', onOpen)
    return () => window.removeEventListener('booru-shortcuts-open', onOpen)
  }, [])

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 left-6 z-40 hidden rounded-ed-md border border-[var(--line)] bg-[var(--panel)] px-3 py-2 text-xs text-[var(--muted)] shadow-lg shadow-black/20 backdrop-blur-md transition-colors hover:bg-[var(--surface)] hover:text-[var(--text)] md:block"
        title="快捷键帮助"
      >
        ⌨︎ 快捷键
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="快捷键" onClick={() => setOpen(false)}>
          <div
            className="w-full max-w-lg rounded-ed-xl border border-[var(--line)] bg-[var(--bg)] editorial-panel p-5 shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-[var(--text)] editorial-title">快捷键</h3>
              <button
                onClick={() => setOpen(false)}
                aria-label="关闭"
                className="rounded-xl px-3 py-2 text-sm text-[var(--muted)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--text)]"
              >
                关闭
              </button>
            </div>

            <div className="mt-4 space-y-2">
              {SHORTCUTS.map(item => (
                <div key={item.key} className="flex items-center justify-between gap-4 rounded-ed-md border border-[var(--line)] bg-[var(--surface)] px-4 py-3">
                  <span className="text-sm text-[var(--muted)]">{item.desc}</span>
                  <kbd className="rounded-ed-sm border border-[var(--line)] bg-[var(--bg-soft)] px-2 py-1 text-xs text-[var(--text)]">{item.key}</kbd>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
