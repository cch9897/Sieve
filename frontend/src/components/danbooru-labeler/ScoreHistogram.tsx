import { useState, useEffect, useRef } from 'react'
import type { HistogramBin, CIStats } from '../../api'

export default function ScoreHistogram({ histogram, ci }: { histogram: HistogramBin[]; ci: CIStats }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [tooltip, setTooltip] = useState<{ x: number; text: string } | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return

    const dpr = window.devicePixelRatio || 1
    const width = container.offsetWidth
    const height = 200
    canvas.width = width * dpr
    canvas.height = height * dpr
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`

    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)

    const pad = { top: 24, right: 16, bottom: 32, left: 44 }
    const plotW = width - pad.left - pad.right
    const plotH = height - pad.top - pad.bottom

    const maxCount = Math.max(...histogram.map(b => b.count), 1)

    ctx.clearRect(0, 0, width, height)

    const sx = (v: number) => pad.left + v * plotW
    const cy = (c: number) => pad.top + plotH - (c / maxCount) * plotH

    ctx.fillStyle = 'rgba(139, 92, 246, 0.08)'
    ctx.fillRect(sx(ci.p25), pad.top, sx(ci.p75) - sx(ci.p25), plotH)

    ctx.fillStyle = 'rgba(52, 211, 153, 0.15)'
    ctx.fillRect(sx(ci.ci95_lo), pad.top, sx(ci.ci95_hi) - sx(ci.ci95_lo), plotH)

    const binW = plotW / histogram.length
    histogram.forEach((bin, i) => {
      if (bin.count === 0) return
      const x = pad.left + i * binW

      if (bin.rejected > 0) {
        const rejH = (bin.rejected / maxCount) * plotH
        const rejY = pad.top + plotH - rejH
        ctx.fillStyle = 'rgba(100, 116, 139, 0.35)'
        ctx.fillRect(x + 0.5, rejY, binW - 1, rejH)
      }

      if (bin.accepted > 0) {
        const totalH = (bin.count / maxCount) * plotH
        const accH = (bin.accepted / maxCount) * plotH
        const accY = pad.top + plotH - totalH

        const score = (bin.lo + bin.hi) / 2
        let color: string
        if (score >= 0.8) color = 'rgba(52, 211, 153, 0.75)'
        else if (score >= 0.6) color = 'rgba(96, 165, 250, 0.65)'
        else if (score >= 0.4) color = 'rgba(251, 191, 36, 0.55)'
        else color = 'rgba(248, 113, 113, 0.5)'

        ctx.fillStyle = color
        ctx.fillRect(x + 0.5, accY, binW - 1, accH)
      }
    })

    ctx.strokeStyle = 'rgba(251, 191, 36, 0.9)'
    ctx.lineWidth = 2
    ctx.setLineDash([6, 3])
    const mx = sx(ci.mean)
    ctx.beginPath()
    ctx.moveTo(mx, pad.top)
    ctx.lineTo(mx, pad.top + plotH)
    ctx.stroke()
    ctx.setLineDash([])

    ctx.strokeStyle = 'rgba(139, 92, 246, 0.9)'
    ctx.lineWidth = 1.5
    ctx.setLineDash([4, 4])
    const medX = sx(ci.median)
    ctx.beginPath()
    ctx.moveTo(medX, pad.top)
    ctx.lineTo(medX, pad.top + plotH)
    ctx.stroke()
    ctx.setLineDash([])

    ctx.strokeStyle = 'rgba(148, 163, 184, 0.4)'
    ctx.lineWidth = 1
    ctx.setLineDash([2, 4])
    for (const p of [ci.p10, ci.p90]) {
      const px = sx(p)
      ctx.beginPath()
      ctx.moveTo(px, pad.top)
      ctx.lineTo(px, pad.top + plotH)
      ctx.stroke()
    }
    ctx.setLineDash([])

    ctx.fillStyle = 'rgba(148, 163, 184, 0.6)'
    ctx.font = '10px system-ui, sans-serif'
    ctx.textAlign = 'center'
    for (let v = 0; v <= 1; v += 0.2) {
      const x = sx(v)
      ctx.fillText(`${(v * 100).toFixed(0)}%`, x, height - 8)
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.15)'
      ctx.beginPath()
      ctx.moveTo(x, pad.top + plotH)
      ctx.lineTo(x, pad.top + plotH + 4)
      ctx.stroke()
    }

    ctx.textAlign = 'right'
    ctx.fillStyle = 'rgba(148, 163, 184, 0.6)'
    const yTicks = 4
    for (let i = 0; i <= yTicks; i++) {
      const val = Math.round((maxCount / yTicks) * i)
      const y = cy(val)
      ctx.fillText(val.toLocaleString(), pad.left - 6, y + 3)
      ctx.strokeStyle = 'rgba(148, 163, 184, 0.06)'
      ctx.beginPath()
      ctx.moveTo(pad.left, y)
      ctx.lineTo(width - pad.right, y)
      ctx.stroke()
    }
  }, [histogram, ci])

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container) return
    const rect = canvas.getBoundingClientRect()
    const x = e.clientX - rect.left
    const pad = { left: 44, right: 16 }
    const plotW = container.offsetWidth - pad.left - pad.right
    const relX = (x - pad.left) / plotW
    if (relX < 0 || relX > 1) { setTooltip(null); return }
    const binIdx = Math.min(Math.floor(relX * histogram.length), histogram.length - 1)
    const bin = histogram[binIdx]
    const parts = [`${(bin.lo * 100).toFixed(0)}-${(bin.hi * 100).toFixed(0)}%: ${bin.count} 张`]
    if (bin.accepted > 0 || bin.rejected > 0) {
      parts.push(`✓${bin.accepted} ✗${bin.rejected}`)
    }
    setTooltip({
      x: e.clientX - rect.left,
      text: parts.join(' · '),
    })
  }

  return (
    <div className="mb-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs text-[var(--muted)]">分数分布直方图</div>
        <div className="flex flex-wrap items-center gap-3 text-[10px] text-[var(--muted)]">
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(96, 165, 250, 0.65)' }} /> 入选
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(100, 116, 139, 0.35)' }} /> 未入选
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3" style={{ background: 'rgba(251, 191, 36, 0.9)' }} /> 均值 {(ci.mean * 100).toFixed(1)}%
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-0.5 w-3" style={{ background: 'rgba(139, 92, 246, 0.9)', borderTop: '1px dashed' }} /> 中位数 {(ci.median * 100).toFixed(1)}%
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(52, 211, 153, 0.15)' }} /> 95% CI
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ background: 'rgba(139, 92, 246, 0.08)' }} /> IQR
          </span>
        </div>
      </div>
      <div ref={containerRef} className="relative">
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setTooltip(null)}
          className="w-full cursor-crosshair"
          aria-label="分数分布直方图"
          role="img"
        />
        {tooltip && (
          <div
            className="pointer-events-none absolute top-1 z-10 rounded-ed-sm border border-[var(--line)] bg-[var(--panel-strong)] px-2 py-1 text-[11px] text-[var(--text)] shadow-lg backdrop-blur"
            style={{ left: Math.min(Math.max(tooltip.x - 50, 0), (containerRef.current?.offsetWidth || 300) - 110) }}
          >
            {tooltip.text}
          </div>
        )}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-[var(--muted)]">
        <span>σ = {(ci.std * 100).toFixed(1)}%</span>
        <span>P10 = {(ci.p10 * 100).toFixed(0)}%</span>
        <span>P90 = {(ci.p90 * 100).toFixed(0)}%</span>
        <span>n = {ci.n.toLocaleString()}</span>
      </div>
    </div>
  )
}
