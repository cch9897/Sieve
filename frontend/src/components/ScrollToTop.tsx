import { useState, useEffect } from 'react'

export default function ScrollToTop() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    let ticking = false
    const onScroll = () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          setVisible(window.scrollY > 400)
          ticking = false
        })
        ticking = true
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  if (!visible) return null

  return (
    <button
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      className="fixed bottom-20 right-6 z-40 flex h-11 w-11 items-center justify-center rounded-ed-md border border-[var(--line)] bg-[var(--panel)] text-[var(--muted)] shadow-lg shadow-black/20 backdrop-blur-md transition-all hover:-translate-y-0.5 hover:bg-[var(--panel-strong)] hover:text-[var(--text)] md:bottom-6"
      aria-label="回到顶部"
      title="回到顶部"
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path d="M8 3v10M3 8l5-5 5 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      </svg>
    </button>
  )
}
