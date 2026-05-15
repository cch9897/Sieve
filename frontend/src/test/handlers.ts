import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

const mockImages = [
  { id: 1, source: 'pixiv', source_id: '100', file_path: 'downloads/test1.jpg', url: 'https://pixiv.net/100', created_at: '2024-01-01', date: '2024-01-01', subfolder: null, is_video: false, thumb_url: '/api/thumb/downloads/test1.jpg' },
  { id: 2, source: 'danbooru', source_id: '200', file_path: 'downloads/test2.jpg', url: 'https://danbooru.donmai.us/200', created_at: '2024-01-02', date: '2024-01-02', subfolder: null, is_video: false, thumb_url: '/api/thumb/downloads/test2.jpg' },
]

export const handlers = [
  http.get('/api/images', ({ request }) => {
    const url = new URL(request.url)
    if (url.searchParams.get('error') === '500') {
      return new HttpResponse('Internal Server Error', { status: 500 })
    }
    if (url.searchParams.get('error') === 'empty') {
      return HttpResponse.json({ images: [], total: 0, page: 1, per_page: 50, pages: 0 })
    }
    return HttpResponse.json({ images: mockImages, total: 2, page: 1, per_page: 50, pages: 1 })
  }),

  http.post('/api/autotags/batch', () => {
    return HttpResponse.json({
      tags: {
        '1': { top_tags: 'tag_a, tag_b', rating: 'sfw' },
        '2': { top_tags: 'tag_c', rating: 'nsfw' },
      },
    })
  }),

  http.get('/api/stats', () => {
    return HttpResponse.json({
      total: 100, total_db: 100, total_novels: 5,
      by_source: { pixiv: 60, danbooru: 40 },
      by_date: { '2024-01-01': 50, '2024-01-02': 50 },
      by_date_source: {},
    })
  }),

  http.get('/api/dates', () => {
    return HttpResponse.json({ dates: ['2024-01-01', '2024-01-02'] })
  }),

  http.get('/api/sources', () => {
    return HttpResponse.json({ sources: ['pixiv', 'danbooru'], counts: { pixiv: 60, danbooru: 40 } })
  }),

  http.get('/api/novels', () => {
    return HttpResponse.json({ novels: [], total: 0, page: 1, per_page: 20, pages: 0 })
  }),

  http.get('/api/labeler/next', () => {
    return HttpResponse.json({ image: mockImages[0], remaining: 10, total_labeled: 5 })
  }),

  http.get('/api/labeler/stats', () => {
    return HttpResponse.json({ total_images: 100, liked: 20, disliked: 10, skipped: 5, total_labeled: 35, remaining: 65 })
  }),

  http.get('/api/labeler/history', () => {
    return HttpResponse.json({ images: [], total: 0, page: 1, per_page: 60, pages: 0 })
  }),

  http.get('/api/labeler/export', () => {
    return new HttpResponse(null, { status: 200 })
  }),

  http.get('/api/novels/dates', () => {
    return HttpResponse.json({ dates: [] })
  }),

  http.get('/api/novels/:id', () => {
    return HttpResponse.json({ id: 1, title: 'Test Novel', author: 'Test', text: '...', tags: [] })
  }),

  http.get('/api/autotags/search', () => {
    return HttpResponse.json({ images: [], total: 0 })
  }),

  http.get('/api/liked', () => {
    return HttpResponse.json({ images: [], total: 0, page: 1, per_page: 50, pages: 0 })
  }),

  // ---- StatsView ML endpoints (defaults; tests can override) -----------
  http.get('/api/autotags/stats', () => {
    return HttpResponse.json({
      tagged: 50,
      total: 100,
      remaining: 50,
      progress_pct: 50,
      top_tags: [{ tag: 'cat', count: 10 }],
      errored: 0,
      errors_by_source: {},
    })
  }),

  http.get('/api/ml/models', () => {
    return HttpResponse.json({
      xgboost: { loaded: true, auc: 0.9, n_samples: 1000, n_liked: 500, n_disliked: 500, model_type: 'xgb', vocab_size: 200 },
      cnn: { loaded: true, model_name: 'siglip2', cv_auc: 0.85, n_samples: 800, input_size: 384, fold_aucs: [0.8, 0.85, 0.9] },
    })
  }),

  http.get('/api/models', () => {
    return HttpResponse.json({ models: {}, active_model: null })
  }),

  http.get('/api/vision-scores/compare-stats', () => {
    return HttpResponse.json({ models: {} })
  }),

  http.get('/api/ml/retrain-xgboost/status', () => {
    return HttpResponse.json({ running: false, finished: false, exit_code: null, log: '' })
  }),

  http.get('/api/ml/pack-dataset/status', () => {
    return HttpResponse.json({ running: false, finished: false, exit_code: null, log: '' })
  }),

  http.get('/api/ml/vision-score/status', () => {
    return HttpResponse.json({ running: false, finished: false, exit_code: null, log: '' })
  }),

  http.get('/api/ml/tag-train/status', () => {
    return HttpResponse.json({ running: false, finished: false, exit_code: null, log: '' })
  }),

  http.post('/api/ml/retrain-xgboost', () => HttpResponse.json({ status: 'started' })),
  http.post('/api/ml/pack-dataset', () => HttpResponse.json({ status: 'started' })),
  http.post('/api/ml/vision-score', () => HttpResponse.json({ status: 'started' })),
  http.post('/api/ml/tag-train', () => HttpResponse.json({ status: 'started' })),
]

export const server = setupServer(...handlers)
