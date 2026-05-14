import { useCallback } from 'react'
import { fetchVisionModels, setActiveModel } from '../../api'
import type {
  CompareStatsResponse,
  MLModelsInfo,
  MLTaskStatus,
  ModelsResponse,
} from '../../api'

interface ModelManagementPanelProps {
  mlModels: MLModelsInfo | null
  visionModels: ModelsResponse | null
  setVisionModels: (m: ModelsResponse | null) => void
  compareStats: CompareStatsResponse | null
  retrainStatus: MLTaskStatus | null
  packStatus: MLTaskStatus | null
  vscoreStatus: MLTaskStatus | null
  tagTrainStatus: MLTaskStatus | null
  onRetrain: () => void
  onVscore: () => void
  onPack: (maxSize?: number) => void
  onTagTrain: () => void
}

export default function ModelManagementPanel({
  mlModels,
  visionModels,
  setVisionModels,
  compareStats,
  retrainStatus,
  packStatus,
  vscoreStatus,
  tagTrainStatus,
  onRetrain,
  onVscore,
  onPack,
  onTagTrain,
}: ModelManagementPanelProps) {
  const handleActiveChange = useCallback(async (e: React.ChangeEvent<HTMLSelectElement>) => {
    try {
      await setActiveModel(e.target.value)
      const updated = await fetchVisionModels()
      setVisionModels(updated)
    } catch (err) { console.error('set active model failed:', err) }
  }, [setVisionModels])

  return (
    <section className="rounded-ed-xl border border-[var(--line)] bg-[var(--panel)] editorial-panel p-5 shadow-sm md:p-6">
      <h3 className="text-sm font-medium text-[var(--text)]">模型管理</h3>
      <p className="mt-1 text-xs text-[var(--muted)]">偏好分类模型状态与训练操作。</p>

      {/* Model cards */}
      <div className="mt-4 grid gap-4 md:grid-cols-2">
        {/* XGBoost card */}
        <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
            <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
            XGBoost
            {mlModels?.xgboost ? (
              <span className="ml-auto rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-400">已加载</span>
            ) : (
              <span className="ml-auto rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">未加载</span>
            )}
          </div>
          {mlModels?.xgboost ? (
            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                <div className="text-[var(--muted)]">AUC</div>
                <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.xgboost.auc.toFixed(3)}</div>
              </div>
              <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                <div className="text-[var(--muted)]">样本数</div>
                <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.xgboost.n_samples.toLocaleString()}</div>
              </div>
              <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                <div className="text-[var(--muted)]">喜欢/不喜欢</div>
                <div className="mt-0.5 text-sm text-[var(--text)]">
                  <span className="text-emerald-400">{mlModels.xgboost.n_liked.toLocaleString()}</span>
                  {' / '}
                  <span className="text-red-400">{mlModels.xgboost.n_disliked.toLocaleString()}</span>
                </div>
              </div>
              <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                <div className="text-[var(--muted)]">特征维度</div>
                <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.xgboost.vocab_size.toLocaleString()}</div>
              </div>
            </div>
          ) : (
            <div className="mt-3 text-xs text-[var(--muted)]">模型文件不存在或加载失败</div>
          )}
        </div>

        {/* Vision model card */}
        <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-4">
          <div className="flex items-center gap-2 text-sm font-medium text-[var(--text)]">
            <span className="h-2.5 w-2.5 rounded-full bg-blue-400" />
            Vision
            {mlModels?.cnn ? (
              <span className="ml-auto rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-400">已加载</span>
            ) : (
              <span className="ml-auto rounded-full bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">未加载</span>
            )}
          </div>
          {mlModels?.cnn ? (
            <div className="mt-3 space-y-2 text-xs">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">CV AUC</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.cnn.cv_auc.toFixed(3)}</div>
                </div>
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">输入尺寸</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.cnn.input_size}px</div>
                </div>
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">样本数</div>
                  <div className="mt-0.5 font-mono text-sm font-semibold text-[var(--text)]">{mlModels.cnn.n_samples.toLocaleString()}</div>
                </div>
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)]">模型架构</div>
                  <div className="mt-0.5 text-[11px] font-medium text-[var(--text)] truncate" title={mlModels.cnn.model_name}>{mlModels.cnn.model_name}</div>
                </div>
              </div>
              {mlModels.cnn.fold_aucs.length > 0 && (
                <div className="rounded-ed-sm bg-[var(--surface)] px-3 py-2">
                  <div className="text-[var(--muted)] mb-1">Fold AUCs</div>
                  <div className="flex gap-1.5">
                    {mlModels.cnn.fold_aucs.map((auc, i) => (
                      <span key={i} className="rounded-ed-sm bg-blue-500/10 px-1.5 py-0.5 font-mono text-[10px] text-blue-300">{auc.toFixed(3)}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="mt-3 text-xs text-[var(--muted)]">模型文件不存在或加载失败</div>
          )}
        </div>
      </div>

      {/* Multi-model selector & comparison */}
      {visionModels && Object.keys(visionModels.models).length > 0 && (
        <div className="mt-4 rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-4">
          <div className="flex items-center justify-between">
            <div className="text-sm font-medium text-[var(--text)]">活跃模型</div>
            <select
              className="rounded-ed-sm border border-[var(--line)] bg-[var(--input-bg)] px-3 py-1.5 text-xs text-[var(--text)] focus:border-[var(--line-strong)] focus:outline-none"
              value={visionModels.active_model || ''}
              onChange={handleActiveChange}
            >
              {Object.entries(visionModels.models).map(([key, info]) => (
                <option key={key} value={key}>
                  {key} — {info.model_class} (AUC: {info.cv_auc ? info.cv_auc.toFixed(3) : 'N/A'})
                </option>
              ))}
            </select>
          </div>

          {/* Per-model comparison stats */}
          {compareStats && Object.keys(compareStats.models).length > 1 && (
            <div className="mt-3 grid gap-2 md:grid-cols-2">
              {Object.entries(compareStats.models).map(([modelName, st]) => {
                const shortName = modelName.split('/').pop() || modelName
                return (
                  <div key={modelName} className="rounded-ed-sm bg-[var(--surface)] p-3">
                    <div className="text-xs font-medium text-[var(--text)] truncate" title={modelName}>{shortName}</div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-[11px]">
                      <div>
                        <div className="text-[var(--muted)]">已评分</div>
                        <div className="font-mono text-[var(--text)]">{st.total.toLocaleString()}</div>
                      </div>
                      <div>
                        <div className="text-[var(--muted)]">均分</div>
                        <div className="font-mono text-[var(--text)]">{st.avg_score != null ? (st.avg_score * 100).toFixed(1) + '%' : '-'}</div>
                      </div>
                      <div>
                        <div className="text-[var(--muted)]">范围</div>
                        <div className="font-mono text-[var(--text)]">
                          {st.min_score != null ? (st.min_score * 100).toFixed(0) : '?'}–{st.max_score != null ? (st.max_score * 100).toFixed(0) : '?'}%
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {/* Vision score */}
        <div>
          <button
            onClick={onVscore}
            disabled={vscoreStatus?.running}
            className="w-full rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-[var(--line-strong)] hover:bg-[var(--surface)] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {vscoreStatus?.running ? (
              <span className="flex items-center justify-center gap-2">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-purple-400" />
                评分中...
              </span>
            ) : '视觉评分'}
          </button>
          {vscoreStatus && !vscoreStatus.running && vscoreStatus.finished && (
            <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${vscoreStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
              {vscoreStatus.exit_code === 0 ? '评分完成' : `评分失败 (exit ${vscoreStatus.exit_code})`}
            </div>
          )}
        </div>

        {/* Pack dataset */}
        <div className="flex gap-2">
          <button
            onClick={() => onPack()}
            disabled={packStatus?.running}
            className="flex-1 rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-[var(--line-strong)] hover:bg-[var(--surface)] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {packStatus?.running ? (
              <span className="flex items-center justify-center gap-2">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-amber-400" />
                打包中...
              </span>
            ) : '📦 打包训练集'}
          </button>
          <button
            onClick={() => onPack(0)}
            disabled={packStatus?.running}
            className="flex-1 rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-blue-500/60 hover:bg-blue-900/30 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            🖼️ 打包原图
          </button>
        </div>
        {packStatus && !packStatus.running && packStatus.finished && (
          <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${packStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
            {packStatus.exit_code === 0 ? '打包完成' : `打包失败 (exit ${packStatus.exit_code})`}
          </div>
        )}

        {/* Retrain XGBoost */}
        <div>
          <button
            onClick={onRetrain}
            disabled={retrainStatus?.running}
            className="w-full rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-[var(--line-strong)] hover:bg-[var(--surface)] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {retrainStatus?.running ? (
              <span className="flex items-center justify-center gap-2">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-blue-400" />
                训练中...
              </span>
            ) : '重训 XGBoost'}
          </button>
          {retrainStatus && !retrainStatus.running && retrainStatus.finished && (
            <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${retrainStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
              {retrainStatus.exit_code === 0 ? '训练完成，模型已热加载' : `训练失败 (exit ${retrainStatus.exit_code})`}
            </div>
          )}
        </div>

        {/* Tag Train (incremental sync + WD14) */}
        <div>
          <button
            onClick={onTagTrain}
            disabled={tagTrainStatus?.running}
            className="w-full rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] px-4 py-3 text-sm font-medium text-[var(--text)] transition-all hover:border-pink-500/60 hover:bg-pink-900/30 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {tagTrainStatus?.running ? (
              <span className="flex items-center justify-center gap-2">
                <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-[var(--muted)] border-t-pink-400" />
                打标中...
              </span>
            ) : '🏷️ 同步打标训练集'}
          </button>
          {tagTrainStatus && !tagTrainStatus.running && tagTrainStatus.finished && (
            <div className={`mt-2 rounded-ed-sm px-3 py-2 text-xs ${tagTrainStatus.exit_code === 0 ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
              {tagTrainStatus.exit_code === 0 ? '打标完成 (GPU)' : `打标失败 (exit ${tagTrainStatus.exit_code})`}
            </div>
          )}
        </div>
      </div>

      {/* Log output */}
      {(retrainStatus?.log || packStatus?.log || vscoreStatus?.log || tagTrainStatus?.log) && (
        <div className="mt-4 space-y-3">
          {vscoreStatus?.log && (
            <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
              <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">视觉评分日志</div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{vscoreStatus.log}</pre>
            </div>
          )}
          {packStatus?.log && (
            <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
              <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">打包日志</div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{packStatus.log}</pre>
            </div>
          )}
          {retrainStatus?.log && (
            <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
              <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">训练日志</div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{retrainStatus.log}</pre>
            </div>
          )}
          {tagTrainStatus?.log && (
            <div className="rounded-ed-md border border-[var(--line)] bg-[var(--panel-strong)] p-3">
              <div className="mb-2 text-[10px] uppercase tracking-wide text-[var(--muted)]">打标日志</div>
              <pre className="max-h-40 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--muted)]">{tagTrainStatus.log}</pre>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
