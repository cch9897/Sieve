import { useState, useEffect } from 'react'
import {
  fetchInferenceStatus,
  fetchGpuConfig,
  updateGpuConfig,
  testGpuConnection,
  setInferenceMode,
  type GpuConfig,
  type InferenceStatus,
  type InferenceMode,
} from '../../api'

export default function GpuSettingsPanel({ prefetchRunning }: { prefetchRunning: boolean }) {
  const [infStatus, setInfStatus] = useState<InferenceStatus | null>(null)
  const [gpu, setGpu] = useState<GpuConfig | null>(null)
  const [loading, setLoading] = useState(true)
  const [switching, setSwitching] = useState(false)
  const [switchError, setSwitchError] = useState('')
  const [urlInput, setUrlInput] = useState('')
  const [batchInput, setBatchInput] = useState(16)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; msg: string } | null>(null)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    Promise.all([
      fetchInferenceStatus().then(setInfStatus).catch(() => {}),
      fetchGpuConfig().then(cfg => {
        setGpu(cfg)
        setUrlInput(cfg.url)
        setBatchInput(cfg.batch_size)
      }).catch(() => {}),
    ]).finally(() => setLoading(false))
  }, [])

  const handleModeSwitch = async (mode: InferenceMode) => {
    setSwitching(true)
    setSwitchError('')
    try {
      const res = await setInferenceMode(mode)
      setInfStatus(prev => prev ? { ...prev, inference_mode: res.inference_mode, current_device: res.current_device, cuda_info: res.cuda_info } : prev)
      fetchGpuConfig().then(cfg => { setGpu(cfg); setUrlInput(cfg.url); setBatchInput(cfg.batch_size) }).catch(() => {})
    } catch (e: unknown) {
      setSwitchError(e instanceof Error ? e.message : '切换失败')
    }
    setSwitching(false)
  }

  const handleSaveRemote = async () => {
    setSaving(true)
    setTestResult(null)
    try {
      const updated = await updateGpuConfig({ url: urlInput, batch_size: batchInput })
      setGpu({ ...updated, remote_health: gpu?.remote_health ?? null })
    } catch (e) { console.error('save remote config failed:', e) }
    setSaving(false)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      await updateGpuConfig({ url: urlInput, batch_size: batchInput })
      const res = await testGpuConnection()
      if (res.ok) {
        const h = res.health
        setTestResult({
          ok: true,
          msg: `✅ 连接成功 · ${h?.model_name || '?'} · ${h?.device || '?'}${h?.fp16 ? ' · FP16' : ''}`
            + (h?.cv_auc ? ` · AUC ${(h.cv_auc * 100).toFixed(1)}%` : '')
            + (h?.gpu_memory_mb ? ` · ${h.gpu_memory_mb.toFixed(0)}MB` : ''),
        })
        fetchGpuConfig().then(setGpu).catch(() => {})
      } else {
        setTestResult({ ok: false, msg: `❌ ${res.error || '连接失败'}` })
      }
    } catch (e: unknown) {
      setTestResult({ ok: false, msg: `❌ ${e instanceof Error ? e.message : '请求失败'}` })
    }
    setTesting(false)
  }

  if (loading) return null

  const currentMode = infStatus?.inference_mode || 'cpu'

  const colorClasses: Record<string, { active: string; dot: string }> = {
    blue: { active: 'border-blue-500/50 bg-blue-500/10 ring-1 ring-blue-500/20', dot: 'bg-blue-400' },
    emerald: { active: 'border-emerald-500/50 bg-emerald-500/10 ring-1 ring-emerald-500/20', dot: 'bg-emerald-400' },
    purple: { active: 'border-purple-500/50 bg-purple-500/10 ring-1 ring-purple-500/20', dot: 'bg-purple-400' },
  }

  const modeOptions: { key: InferenceMode; label: string; icon: string; desc: string; color: string; disabledReason?: string }[] = [
    { key: 'cpu', label: 'CPU', icon: '🖥', desc: '本机 CPU 推理', color: 'blue' },
    {
      key: 'local_gpu',
      label: '本地 GPU',
      icon: '🎮',
      desc: infStatus?.cuda_info ? `${infStatus.cuda_info.device_name} · ${infStatus.cuda_info.total_memory_mb}MB` : 'CUDA 设备',
      color: 'emerald',
      disabledReason: !infStatus?.cuda_available ? 'CUDA 不可用' : undefined,
    },
    { key: 'remote', label: '远程 GPU', icon: '🌐', desc: gpu?.url || '未配置', color: 'purple' },
  ]

  return (
    <div className="mt-3 rounded-ed-sm border border-[var(--line)] bg-[var(--panel-strong)] p-3">
      <button
        onClick={() => setExpanded(!expanded)}
        aria-expanded={expanded}
        className="flex w-full items-center justify-between text-xs text-[var(--muted)] hover:text-[var(--text)] transition-colors"
      >
        <div className="flex items-center gap-2">
          <span>⚡</span>
          <span>推理模式</span>
          <span className={`rounded-full px-2 py-0.5 text-[10px] ${
            currentMode === 'local_gpu' ? 'bg-emerald-500/20 text-emerald-300' :
            currentMode === 'remote' ? 'bg-purple-500/20 text-purple-300' :
            'bg-blue-500/20 text-blue-300'
          }`}>
            {currentMode === 'local_gpu' ? '🎮 本地 GPU' : currentMode === 'remote' ? '🌐 远程' : '🖥 CPU'}
          </span>
          {infStatus?.current_device === 'cuda' && infStatus?.cuda_info && (
            <span className="text-[10px] text-[var(--muted)]">
              {infStatus.cuda_info.device_name} · {infStatus.cuda_info.allocated_mb}MB used
            </span>
          )}
        </div>
        <svg
          className={`h-4 w-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
          viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"
        >
          <path fillRule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clipRule="evenodd" />
        </svg>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          <div className="grid grid-cols-3 gap-2">
            {modeOptions.map(opt => {
              const active = currentMode === opt.key
              const disabled = switching || !!opt.disabledReason
              return (
                <button
                  key={opt.key}
                  onClick={() => !active && !disabled && handleModeSwitch(opt.key)}
                  disabled={disabled}
                  className={[
                    'relative rounded-ed-sm border p-3 text-left transition-all',
                    active
                      ? colorClasses[opt.color]?.active || colorClasses.blue.active
                      : 'border-[var(--line)] bg-[var(--surface)] hover:border-[var(--line-strong)]',
                    disabled && !active ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
                  ].join(' ')}
                  title={opt.disabledReason || ''}
                >
                  {switching && currentMode !== opt.key && !active && (
                    <span className="absolute right-2 top-2 h-3 w-3 animate-spin rounded-full border-2 border-[var(--muted)] border-t-transparent" />
                  )}
                  <div className="text-base">{opt.icon}</div>
                  <div className={`mt-1 text-xs font-medium ${active ? 'text-[var(--text)]' : 'text-[var(--text)]'}`}>{opt.label}</div>
                  <div className="mt-0.5 text-[10px] text-[var(--muted)] truncate">{opt.disabledReason || opt.desc}</div>
                  {active && (
                    <div className={`absolute right-2 top-2 h-2 w-2 rounded-full ${colorClasses[opt.color]?.dot || 'bg-blue-400'}`} />
                  )}
                </button>
              )
            })}
          </div>

          {switching && (
            <div className="flex items-center gap-2 text-xs text-[var(--muted)]">
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--muted)] border-t-blue-400" />
              模型迁移中…
            </div>
          )}

          {switchError && (
            <div className="rounded-ed-sm border border-red-500/20 bg-red-500/5 px-3 py-2 text-xs text-red-300">
              ❌ {switchError}
            </div>
          )}

          {infStatus?.cuda_available && infStatus.cuda_info && (
            <div className="rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] px-3 py-2">
              <div className="flex items-center justify-between text-[11px]">
                <span className="text-[var(--muted)]">CUDA 设备</span>
                <span className="text-[var(--text)]">{infStatus.cuda_info.device_name}</span>
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px]">
                <span className="text-[var(--muted)]">显存</span>
                <span className="text-[var(--text)]">{infStatus.cuda_info.allocated_mb}MB / {infStatus.cuda_info.total_memory_mb}MB</span>
              </div>
              {infStatus.cnn_loaded && (
                <div className="mt-1 flex items-center justify-between text-[11px]">
                  <span className="text-[var(--muted)]">当前设备</span>
                  <span className={`font-mono ${infStatus.current_device === 'cuda' ? 'text-emerald-400' : 'text-blue-400'}`}>{infStatus.current_device}</span>
                </div>
              )}
            </div>
          )}

          {currentMode === 'remote' && (
            <div className="space-y-2 rounded-ed-sm border border-purple-500/10 bg-purple-500/5 p-3">
              <div className="text-[11px] font-medium text-purple-300/80">远程 GPU 服务器配置</div>
              <div className="flex items-center gap-2">
                <label className="shrink-0 text-xs text-[var(--muted)] w-14">地址</label>
                <input
                  value={urlInput}
                  onChange={e => setUrlInput(e.target.value)}
                  placeholder="http://192.168.x.x:5099"
                  className="flex-1 rounded-ed-sm border border-[var(--line)] bg-[var(--input-bg)] px-3 py-1.5 text-sm text-[var(--text)] placeholder:text-[var(--muted)]/50 focus:border-purple-500/50 focus:outline-none"
                />
              </div>
              <div className="flex items-center gap-2">
                <label className="shrink-0 text-xs text-[var(--muted)] w-14">Batch</label>
                <input
                  type="number"
                  min={1}
                  max={64}
                  value={batchInput}
                  onChange={e => setBatchInput(Number(e.target.value))}
                  className="w-20 rounded-ed-sm border border-[var(--line)] bg-[var(--input-bg)] px-3 py-1.5 text-sm text-[var(--text)] focus:border-purple-500/50 focus:outline-none"
                />
                <span className="text-[10px] text-[var(--muted)]/50">张/请求 (1-64)</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSaveRemote}
                  disabled={saving}
                  className="rounded-ed-sm border border-[var(--line)] bg-[var(--surface)] px-3 py-1.5 text-xs text-[var(--text)] transition-all hover:bg-[var(--panel)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  {saving ? '保存中…' : '💾 保存'}
                </button>
                <button
                  onClick={handleTest}
                  disabled={testing || !urlInput}
                  className="rounded-ed-sm border border-purple-500/30 bg-purple-500/10 px-3 py-1.5 text-xs text-purple-300 transition-all hover:bg-purple-500/20 disabled:opacity-50"
                >
                  {testing ? (
                    <span className="flex items-center gap-1.5">
                      <span className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                      测试中…
                    </span>
                  ) : '🔌 测试连接'}
                </button>
              </div>
              {testResult && (
                <div className={`rounded-ed-sm px-3 py-2 text-xs ${
                  testResult.ok
                    ? 'border border-emerald-500/20 bg-emerald-500/5 text-emerald-300'
                    : 'border border-red-500/20 bg-red-500/5 text-red-300'
                }`}>
                  {testResult.msg}
                </div>
              )}
            </div>
          )}

          {prefetchRunning && (
            <div className="text-[10px] text-amber-400/70">
              ⚠ 预筛选正在运行，模式切换将在下次启动时生效
            </div>
          )}
        </div>
      )}
    </div>
  )
}
