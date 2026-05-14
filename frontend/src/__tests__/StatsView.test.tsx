import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { http, HttpResponse } from 'msw'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { server } from '../test/handlers'
import StatsView from '../components/StatsView'

const baseStats = {
  total: 1000,
  total_db: 1200,
  total_novels: 12,
  by_source: { pixiv: 700, danbooru: 300 },
  by_date: {
    '2024-01-01': 50,
    '2024-01-02': 60,
    '2024-01-03': 70,
  },
  by_date_source: {},
}

describe('StatsView', () => {
  beforeEach(() => {
    server.use(
      http.get('/api/stats', () => HttpResponse.json(baseStats)),
    )
  })

  afterEach(() => {
    vi.restoreAllMocks()
    server.resetHandlers()
  })

  it('renders without crashing', async () => {
    render(<StatsView />)
    // After data loads, the heading is visible.
    await waitFor(() =>
      expect(screen.getByText('统计概览')).toBeInTheDocument(),
    )
  })

  it('shows model management buttons after load', async () => {
    render(<StatsView />)
    await waitFor(() =>
      expect(screen.getByText('模型管理')).toBeInTheDocument(),
    )
    // The four action buttons.
    expect(screen.getByText('视觉评分')).toBeInTheDocument()
    expect(screen.getByText('📦 打包训练集')).toBeInTheDocument()
    expect(screen.getByText('重训 XGBoost')).toBeInTheDocument()
    expect(screen.getByText('🏷️ 同步打标训练集')).toBeInTheDocument()
  })

  it('renders source distribution bars', async () => {
    render(<StatsView />)
    await waitFor(() =>
      expect(screen.getByText('来源分布')).toBeInTheDocument(),
    )
    // by_source has pixiv and danbooru → both labels must appear.
    // Default source meta uses Chinese-friendly labels; we check for the count display.
    expect(screen.getByText('700')).toBeInTheDocument()
    expect(screen.getByText('300')).toBeInTheDocument()
  })

  it('clicking 重训 XGBoost calls the retrain endpoint', async () => {
    const retrainHit = vi.fn()
    server.use(
      http.post('/api/ml/retrain-xgboost', () => {
        retrainHit()
        return HttpResponse.json({ status: 'started' })
      }),
    )
    render(<StatsView />)
    await waitFor(() => screen.getByText('重训 XGBoost'))

    const user = userEvent.setup()
    await user.click(screen.getByText('重训 XGBoost'))
    await waitFor(() => expect(retrainHit).toHaveBeenCalledTimes(1))
  })

  it('clicking 视觉评分 calls the vision-score endpoint', async () => {
    const vscoreHit = vi.fn()
    server.use(
      http.post('/api/ml/vision-score', () => {
        vscoreHit()
        return HttpResponse.json({ status: 'started' })
      }),
    )
    render(<StatsView />)
    await waitFor(() => screen.getByText('视觉评分'))

    const user = userEvent.setup()
    await user.click(screen.getByText('视觉评分'))
    await waitFor(() => expect(vscoreHit).toHaveBeenCalledTimes(1))
  })

  it('clicking 📦 打包训练集 calls pack-dataset', async () => {
    const packHit = vi.fn()
    server.use(
      http.post('/api/ml/pack-dataset', () => {
        packHit()
        return HttpResponse.json({ status: 'started' })
      }),
    )
    render(<StatsView />)
    await waitFor(() => screen.getByText('📦 打包训练集'))

    const user = userEvent.setup()
    await user.click(screen.getByText('📦 打包训练集'))
    await waitFor(() => expect(packHit).toHaveBeenCalledTimes(1))
  })

  it('shows auto-tags progress when /api/autotags/stats returns data', async () => {
    render(<StatsView />)
    await waitFor(() =>
      expect(screen.getByText('自动打标进度')).toBeInTheDocument(),
    )
    // Default handler returns 50/100 (50%).
    expect(screen.getByText(/50.*\/.*100/)).toBeInTheDocument()
  })

  it('shows spinner while loading', () => {
    server.use(
      http.get('/api/stats', () => new Promise(() => {})),  // never resolves
    )
    const { container } = render(<StatsView />)
    // The Spinner component should appear inside the loading wrapper.
    expect(container.querySelector('div.flex.h-64')).toBeInTheDocument()
  })
})
