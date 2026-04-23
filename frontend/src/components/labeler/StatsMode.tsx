import { useState, useEffect } from 'react'
import {
  fetchLabelerStats,
  getExportUrl,
  type LabelerStats,
} from '../../api'
import { getSourceMeta } from '../../sourceMeta'
import Spinner from '../Spinner'

export default function StatsMode() {
  const [stats, setStats] = useState<LabelerStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchLabelerStats().then(setStats).catch(e => console.error('fetchLabelerStats failed:', e)).finally(() => setLoading(false))
  }, [])

  if (loading || !stats) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner size="md" />
      </div>
    )
  }

  const statCards = [
    { label: '总图片', value: stats.total_images, color: 'text-[var(--text)]' },
    { label: '已标注', value: stats.total_labeled, color: 'text-[var(--info)]' },
    { label: '喜欢', value: stats.liked, color: 'text-[var(--success)]' },
    { label: '不喜欢', value: stats.disliked, color: 'text-[var(--danger)]' },
    { label: '跳过', value: stats.skipped, color: 'text-[var(--muted)]' },
    { label: '剩余', value: stats.remaining, color: 'text-[var(--warning)]' },
  ]

  const likeRate = stats.total_labeled > 0
    ? ((stats.liked / (stats.liked + stats.disliked || 1)) * 100).toFixed(1)
    : '0'

  const labeledPercent = stats.total_images > 0 ? stats.total_labeled / stats.total_images : 0

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {statCards.map(s => (
          <div key={s.label} className="editorial-panel p-4 text-center">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value.toLocaleString()}</div>
            <div className="mt-1 micro-label">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="editorial-panel p-5">
        <div className="mb-3 text-sm text-[var(--text)]">喜欢率</div>
        <div className="flex items-end gap-3">
          <span className="text-3xl font-bold text-[var(--success)]">{likeRate}%</span>
          <span className="mb-1 text-sm text-[var(--muted)]">
            ({stats.liked} / {stats.liked + stats.disliked})
          </span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-[rgba(255,255,255,0.05)]">
          <div
            className="h-full rounded-full bg-[var(--success)] progress-bar-fill"
            style={{ transform: `scaleX(${Number(likeRate) / 100})` }}
          />
        </div>
      </div>

      <div className="editorial-panel p-5">
        <div className="mb-3 text-sm text-[var(--text)]">标注进度</div>
        <div className="h-3 overflow-hidden rounded-full bg-[rgba(255,255,255,0.05)]">
          <div
            className="flex h-full origin-left"
            style={{ transform: `scaleX(${labeledPercent})` }}
          >
            <div className="h-full bg-[var(--success)]" style={{ width: `${stats.liked / (stats.total_labeled || 1) * 100}%` }} />
            <div className="h-full bg-[var(--danger)]" style={{ width: `${stats.disliked / (stats.total_labeled || 1) * 100}%` }} />
            <div className="h-full bg-[var(--muted)]/40" style={{ width: `${stats.skipped / (stats.total_labeled || 1) * 100}%` }} />
          </div>
        </div>
        <div className="mt-2 flex gap-4 text-xs text-[var(--muted)]">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--success)]" />喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--danger)]" />不喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--muted)]/40" />跳过</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[rgba(255,255,255,0.05)]" />未标注</span>
        </div>
      </div>

      {stats.top_tags.length > 0 && (
        <div className="editorial-panel p-5">
          <div className="mb-3 text-sm text-[var(--text)]">常用标签</div>
          <div className="flex flex-wrap gap-2">
            {stats.top_tags.map(t => (
              <span
                key={t.tag}
                className="rounded-ed-sm border border-[var(--line)] bg-[var(--accent-soft)] px-3 py-1.5 text-sm text-[var(--text)]"
              >
                {t.tag} <span className="text-[var(--muted)]">×{t.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {stats.liked > 0 && Object.keys(stats.liked_by_source || {}).length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="editorial-panel p-5">
            <div className="mb-1 text-sm text-[var(--text)]">👍 喜欢来源占比</div>
            <p className="mb-4 micro-label">喜欢的图片中，各站点贡献了多少。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_source)
                .sort(([, a], [, b]) => b - a)
                .map(([source, count]) => {
                  const meta = getSourceMeta(source)
                  const pct = ((count / stats.liked) * 100).toFixed(1)
                  return (
                    <div key={source} className="group rounded-ed-lg border border-[var(--line)] bg-[rgba(0,0,0,0.16)] p-3 transition-colors hover:border-[var(--line-strong)]">
                      <div className="mb-2 flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2 text-[var(--text)]">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} />
                          <span>{meta.label}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="micro-label">{pct}%</span>
                          <span className="text-[var(--muted)]">{count.toLocaleString()}</span>
                        </div>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-[rgba(255,255,255,0.05)]">
                        <div
                          className="h-full rounded-full transition-colors duration-500 group-hover:brightness-110"
                          style={{ width: `${(count / stats.liked) * 100}%`, backgroundColor: meta.color }}
                        />
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>

          <div className="editorial-panel p-5">
            <div className="mb-1 text-sm text-[var(--text)]">📊 站点喜欢率</div>
            <p className="mb-4 micro-label">各站点已审阅图片中，被喜欢的比例。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_source)
                .map(([source, likedCount]) => {
                  const labeledCount = (stats.labeled_by_source || {})[source] || 0
                  const rate = labeledCount > 0 ? (likedCount / labeledCount) * 100 : 0
                  return { source, likedCount, labeledCount, rate }
                })
                .sort((a, b) => b.rate - a.rate)
                .map(({ source, likedCount, labeledCount, rate }) => {
                  const meta = getSourceMeta(source)
                  return (
                    <div key={source} className="group rounded-ed-lg border border-[var(--line)] bg-[rgba(0,0,0,0.16)] p-3 transition-colors hover:border-[var(--line-strong)]">
                      <div className="mb-2 flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2 text-[var(--text)]">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} />
                          <span>{meta.label}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold" style={{ color: meta.color }}>{rate.toFixed(1)}%</span>
                          <span className="micro-label">{likedCount}/{labeledCount}</span>
                        </div>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-[rgba(255,255,255,0.05)]">
                        <div
                          className="h-full rounded-full transition-colors duration-500 group-hover:brightness-110"
                          style={{ width: `${rate}%`, backgroundColor: meta.color }}
                        />
                      </div>
                    </div>
                  )
                })}
            </div>
          </div>
        </div>
      )}

      {(stats.liked_top_auto_tags || []).length > 0 && (() => {
        const tags = stats.liked_top_auto_tags.slice(0, 30)
        const maxCount = tags[0]?.count || 1
        return (
          <div className="editorial-panel p-5">
            <div className="mb-1 text-sm text-[var(--text)]">👍 喜欢标签排名</div>
            <p className="mb-4 micro-label">标记为喜欢的图片中，AI 自动标签出现频率 Top 30。</p>
            <div className="space-y-1.5">
              {tags.map((t, i) => {
                const barPct = (t.count / maxCount) * 100
                const opacity = Math.max(0.3, 1 - i * 0.023)
                return (
                  <div key={t.tag} className="group flex items-center gap-2">
                    <span className="w-5 shrink-0 text-right text-[10px] tabular-nums text-[var(--muted)]/50">{i + 1}</span>
                    <div className="relative h-7 flex-1 overflow-hidden rounded-ed-sm bg-[rgba(255,255,255,0.03)]">
                      <div
                        className="absolute inset-y-0 left-0 rounded-ed-sm transition-all duration-500 group-hover:brightness-125"
                        style={{
                          width: `${Math.max(barPct, 2)}%`,
                          backgroundColor: `rgba(52, 211, 153, ${opacity})`,
                        }}
                      />
                      <div className="relative flex h-full items-center justify-between px-2.5">
                        <span className="text-xs text-[var(--text)] drop-shadow-sm">{t.tag}</span>
                        <span className="text-[11px] tabular-nums text-[var(--muted)]">{t.count}</span>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })()}

      {stats.liked > 0 && (
        <div className="flex flex-wrap justify-center gap-3">
          <a
            href={getExportUrl('liked')}
            className="rounded-ed-md border border-[var(--success)]/30 bg-[var(--success-soft)] px-6 py-3 text-sm font-medium text-[var(--success)] transition-colors hover:bg-[rgba(52,211,153,0.2)]"
          >
            📦 导出喜欢的 ({stats.liked} 张)
          </a>
          <a
            href={getExportUrl('liked', undefined, 0)}
            className="rounded-ed-md border border-[var(--info)]/30 bg-[var(--info-soft)] px-6 py-3 text-sm font-medium text-[var(--info)] transition-colors hover:bg-[rgba(96,165,250,0.2)]"
          >
            🖼️ 导出原始分辨率
          </a>
        </div>
      )}
    </div>
  )
}
