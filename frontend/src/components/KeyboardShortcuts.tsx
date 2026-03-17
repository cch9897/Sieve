import { useEffect, useState } from 'react'

const SHORTCUTS = [
  { key: 'G', desc: '切到图库' },
  { key: 'N', desc: '切到小说' },
  { key: 'S', desc: '切到统计' },
  { key: 'F', desc: '展开/收起筛选' },
  { key: 'J / K', desc: '下一页 / 上一页（分页模式）' },
  { key: '← / →', desc: '灯箱上一张 / 下一张' },
  { key: 'Esc', desc: '关闭灯箱或返回' },
  { key: '?', desc: '打开快捷键帮助' },
]

export default function KeyboardShortcuts() {
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const onOpen = () => setOpen(true)
    window.addEventListener('booru-shortcuts-open', onOpen as EventListener)
    return () => window.removeEventListener('booru-shortcuts-open', onOpen as EventListener)
  }, [])

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="fixed bottom-6 left-6 z-40 hidden rounded-2xl border border-dark-700/60 bg-dark-900/85 px-3 py-2 text-xs text-dark-300 shadow-lg shadow-black/20 backdrop-blur-md transition-colors hover:bg-dark-800 hover:text-white md:block"
        title="快捷键帮助"
      >
        ⌨︎ 快捷键
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setOpen(false)}>
          <div
            className="w-full max-w-lg rounded-3xl border border-dark-700/60 bg-dark-950 p-5 shadow-2xl"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold text-dark-100">快捷键</h3>
              <button
                onClick={() => setOpen(false)}
                className="rounded-xl px-3 py-2 text-sm text-dark-400 transition-colors hover:bg-dark-900 hover:text-white"
              >
                关闭
              </button>
            </div>

            <div className="mt-4 space-y-2">
              {SHORTCUTS.map(item => (
                <div key={item.key} className="flex items-center justify-between gap-4 rounded-2xl border border-dark-800 bg-dark-900/70 px-4 py-3">
                  <span className="text-sm text-dark-300">{item.desc}</span>
                  <kbd className="rounded-lg border border-dark-700 bg-dark-950 px-2 py-1 text-xs text-dark-100">{item.key}</kbd>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
