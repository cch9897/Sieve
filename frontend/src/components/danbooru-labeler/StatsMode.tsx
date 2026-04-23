import { useState, useEffect } from 'react'
import Spinner from '../Spinner'
import {
  fetchDanbooruLabelerStats,
  getDanbooruExportUrl,
  type DanbooruLabelerStats,
} from '../../api'
import { getRatingMeta } from './shared'
import AiScreeningCard from './AiScreeningCard'

export default function StatsMode() {
  const [stats, setStats] = useState<DanbooruLabelerStats | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchDanbooruLabelerStats().then(setStats).catch(e => console.error('fetch stats failed:', e)).finally(() => setLoading(false))
  }, [])

  if (loading || !stats) {
    return (
      <div className="flex h-40 items-center justify-center">
        <Spinner size="sm" />
      </div>
    )
  }

  const statCards = [
    { label: '数据库总量', value: stats.total_images, color: 'text-[var(--text)]' },
    { label: '已标注', value: stats.total_labeled, color: 'text-blue-400' },
    { label: '喜欢', value: stats.liked, color: 'text-emerald-400' },
    { label: '不喜欢', value: stats.disliked, color: 'text-red-400' },
    { label: '跳过', value: stats.skipped, color: 'text-[var(--muted)]' },
    { label: '剩余', value: stats.remaining, color: 'text-amber-400' },
  ]

  const likeRate = stats.total_labeled > 0
    ? ((stats.liked / (stats.liked + stats.disliked || 1)) * 100).toFixed(1)
    : '0'

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {statCards.map(s => (
          <div key={s.label} className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-4 text-center">
            <div className={`text-2xl font-bold ${s.color}`}>{s.value.toLocaleString()}</div>
            <div className="mt-1 text-xs text-[var(--muted)]">{s.label}</div>
          </div>
        ))}
      </div>

      <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
        <div className="mb-3 text-sm text-[var(--text)]">喜欢率</div>
        <div className="flex items-end gap-3">
          <span className="text-3xl font-bold text-emerald-400">{likeRate}%</span>
          <span className="mb-1 text-sm text-[var(--muted)]">
            ({stats.liked} / {stats.liked + stats.disliked})
          </span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--surface)]">
          <div className="h-full rounded-full bg-emerald-500 progress-bar-fill" style={{ transform: `scaleX(${Number(likeRate) / 100})` }} />
        </div>
      </div>

      <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
        <div className="mb-3 text-sm text-[var(--text)]">标注进度</div>
        <div className="h-3 overflow-hidden rounded-full bg-[var(--surface)]">
          <div
            className="flex h-full"
            style={{ width: `${stats.total_images > 0 ? (stats.total_labeled / stats.total_images * 100) : 0}%` }}
          >
            <div className="h-full bg-emerald-500" style={{ width: `${stats.liked / (stats.total_labeled || 1) * 100}%` }} />
            <div className="h-full bg-red-500" style={{ width: `${stats.disliked / (stats.total_labeled || 1) * 100}%` }} />
            <div className="h-full bg-[var(--muted)]/30" style={{ width: `${stats.skipped / (stats.total_labeled || 1) * 100}%` }} />
          </div>
        </div>
        <div className="mt-2 flex gap-4 text-xs text-[var(--muted)]">
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" aria-hidden="true" />喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-red-500" aria-hidden="true" />不喜欢</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--muted)]/30" aria-hidden="true" />跳过</span>
          <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-[var(--surface)]" aria-hidden="true" />未标注</span>
        </div>
      </div>

      <AiScreeningCard />

      {stats.liked > 0 && Object.keys(stats.liked_by_rating || {}).length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
            <div className="mb-1 text-sm text-[var(--text)]">👍 喜欢 Rating 占比</div>
            <p className="mb-4 text-xs text-[var(--muted)]">喜欢的图片中，各 Rating 贡献了多少。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_rating)
                .sort(([, a], [, b]) => b - a)
                .map(([rating, count]) => {
                  const meta = getRatingMeta(rating)
                  const pct = ((count / stats.liked) * 100).toFixed(1)
                  return (
                    <div key={rating} className="group rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3 transition-colors hover:border-[var(--line)]">
                      <div className="mb-2 flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2 text-[var(--text)]">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} aria-hidden="true" />
                          <span>{meta.label}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-[var(--muted)]">{pct}%</span>
                          <span className="text-[var(--muted)]">{count.toLocaleString()}</span>
                        </div>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-[var(--surface)]">
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

          <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
            <div className="mb-1 text-sm text-[var(--text)]">📊 Rating 喜欢率</div>
            <p className="mb-4 text-xs text-[var(--muted)]">各 Rating 已审阅图片中，被喜欢的比例。</p>
            <div className="space-y-3">
              {Object.entries(stats.liked_by_rating)
                .map(([rating, likedCount]) => {
                  const labeledCount = (stats.labeled_by_rating || {})[rating] || 0
                  const rate = labeledCount > 0 ? (likedCount / labeledCount) * 100 : 0
                  return { rating, likedCount, labeledCount, rate }
                })
                .sort((a, b) => b.rate - a.rate)
                .map(({ rating, likedCount, labeledCount, rate }) => {
                  const meta = getRatingMeta(rating)
                  return (
                    <div key={rating} className="group rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3 transition-colors hover:border-[var(--line)]">
                      <div className="mb-2 flex items-center justify-between text-sm">
                        <div className="flex items-center gap-2 text-[var(--text)]">
                          <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: meta.color }} aria-hidden="true" />
                          <span>{meta.label}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-semibold" style={{ color: meta.color }}>{rate.toFixed(1)}%</span>
                          <span className="text-xs text-[var(--muted)]">{likedCount}/{labeledCount}</span>
                        </div>
                      </div>
                      <div className="h-2 overflow-hidden rounded-full bg-[var(--surface)]">
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

      {(stats.liked_top_danbooru_tags || []).length > 0 && (() => {
        const tags = stats.liked_top_danbooru_tags.slice(0, 30)
        const maxCount = tags[0]?.count || 1
        return (
          <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
            <div className="mb-1 text-sm text-[var(--text)]">👍 喜欢标签排名</div>
            <p className="mb-4 text-xs text-[var(--muted)]">标记为喜欢的图片中，Danbooru 标签出现频率 Top 30。</p>
            <div className="space-y-1.5">
              {tags.map((t, i) => {
                const barPct = (t.count / maxCount) * 100
                const opacity = Math.max(0.3, 1 - i * 0.023)
                return (
                  <div key={t.tag} className="group flex items-center gap-2">
                    <span className="w-5 shrink-0 text-right text-[10px] tabular-nums text-[var(--muted)]/50">{i + 1}</span>
                    <div className="relative flex-1 h-7 rounded-ed-sm overflow-hidden bg-[var(--surface)]">
                      <div
                        className="absolute inset-y-0 left-0 rounded-ed-sm transition-all duration-500 group-hover:brightness-125"
                        style={{
                          width: `${Math.max(barPct, 2)}%`,
                          backgroundColor: `rgba(96, 165, 250, ${opacity})`,
                        }}
                      />
                      <div className="relative flex h-full items-center justify-between px-2.5">
                        <span className="text-xs text-[var(--text)] drop-shadow-sm">{t.tag.replace(/_/g, ' ')}</span>
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

      {stats.top_tags.length > 0 && (
        <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5">
          <div className="mb-3 text-sm text-[var(--text)]">常用自定义标签</div>
          <div className="flex flex-wrap gap-2">
            {stats.top_tags.map(t => (
              <span
                key={t.tag}
                className="rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-sm text-[var(--text)]"
              >
                {t.tag} <span className="text-[var(--muted)]">×{t.count}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {(stats.liked > 0 || stats.disliked > 0) && (
        <div className="flex justify-center gap-3 flex-wrap">
          {stats.liked > 0 && (
            <a
              href={getDanbooruExportUrl('liked')}
              className="rounded-ed-md bg-emerald-600 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-emerald-500"
            >
              📦 导出喜欢 ({stats.liked} 张)
            </a>
          )}
          {stats.liked > 0 && (
            <a
              href={getDanbooruExportUrl('liked', undefined, 0)}
              className="rounded-ed-md bg-blue-600 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-blue-500"
            >
              🖼️ 喜欢原图
            </a>
          )}
          {stats.disliked > 0 && (
            <a
              href={getDanbooruExportUrl('disliked')}
              className="rounded-ed-md bg-red-600/80 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-red-500"
            >
              📦 导出不喜欢 ({stats.disliked} 张)
            </a>
          )}
          {stats.disliked > 0 && (
            <a
              href={getDanbooruExportUrl('disliked', undefined, 0)}
              className="rounded-ed-md bg-orange-600/80 px-6 py-3 text-sm font-medium text-white transition-colors hover:bg-orange-500"
            >
              🖼️ 不喜欢原图
            </a>
          )}
        </div>
      )}
    </div>
  )
}
