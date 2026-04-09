import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'

const mockImages = [
  { id: 1, source: 'pixiv', source_id: '100', file_path: 'downloads/test1.jpg', url: 'https://pixiv.net/100', created_at: '2024-01-01', date: '2024-01-01', subfolder: null, is_video: false, thumb_url: '/api/thumb/downloads/test1.jpg' },
  { id: 2, source: 'danbooru', source_id: '200', file_path: 'downloads/test2.jpg', url: 'https://danbooru.donmai.us/200', created_at: '2024-01-02', date: '2024-01-02', subfolder: null, is_video: false, thumb_url: '/api/thumb/downloads/test2.jpg' },
]

export const handlers = [
  http.get('/api/images', () => {
    return HttpResponse.json({ images: mockImages, total: 2, page: 1, per_page: 50, pages: 1 })
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
]

export const server = setupServer(...handlers)
