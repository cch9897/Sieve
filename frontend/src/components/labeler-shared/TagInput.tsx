import { useRef, useCallback } from 'react'

interface TagInputProps {
  tags: string[]
  onTagsChange: (tags: string[]) => void
  tagInput: string
  onTagInputChange: (value: string) => void
}

export default function TagInput({ tags, onTagsChange, tagInput, onTagInputChange }: TagInputProps) {
  const tagInputRef = useRef<HTMLInputElement>(null)

  const addTag = useCallback(() => {
    const t = tagInput.trim()
    if (t && !tags.includes(t)) {
      onTagsChange([...tags, t])
    }
    onTagInputChange('')
    tagInputRef.current?.focus()
  }, [tagInput, tags, onTagsChange, onTagInputChange])

  const removeTag = useCallback((t: string) => {
    onTagsChange(tags.filter(x => x !== t))
  }, [tags, onTagsChange])

  return (
    <div className="flex w-full max-w-2xl flex-wrap items-center gap-2">
      {tags.map(t => (
        <span
          key={t}
          className="inline-flex items-center gap-1 rounded-ed-sm border border-[var(--line)] bg-[var(--accent-soft)] px-2.5 py-1 text-xs text-[var(--text)]"
        >
          {t}
          <button onClick={() => removeTag(t)} className="text-[var(--muted)] hover:text-[var(--danger)]">×</button>
        </span>
      ))}
      <div className="flex flex-1 items-center gap-2">
        <input
          ref={tagInputRef}
          value={tagInput}
          onChange={e => onTagInputChange(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') { e.preventDefault(); addTag() }
            if (e.key === 'Escape') { onTagInputChange(''); (e.target as HTMLElement).blur() }
          }}
          placeholder="添加标签… (T 聚焦, Enter 确认)"
          className="min-w-[160px] flex-1 rounded-ed-sm border border-[var(--input-border)] bg-[var(--input-bg)] px-3 py-1.5 text-sm text-[var(--text)] placeholder:text-[var(--muted)]/50 focus:border-[var(--input-focus)] focus:outline-none"
        />
      </div>
    </div>
  )
}
