export interface ImageItem {
  id: number
  source: string
  source_id: string
  file_path: string
  url: string
  created_at: string
  date: string | null
  subfolder: string | null
  is_video: boolean
  thumb_url: string
  vision_score?: number | null
  vision_scores?: Record<string, number>
}

export interface ImageDetail extends ImageItem {
  phash: string
}

export interface ImageListResponse {
  images: ImageItem[]
  total: number
  page: number
  per_page: number
  pages: number
}

export interface Stats {
  total: number
  total_db: number
  total_novels: number
  by_source: Record<string, number>
  by_date: Record<string, number>
  by_date_source: Record<string, Record<string, number>>
}

export interface NovelItem {
  id: number
  source: string
  source_id: string
  title: string
  author: string
  date: string | null
  url: string
  created_at: string
  text_length: number
  total_bookmarks: number
  total_view: number
  tags: string[]
  series_title: string | null
  r18: boolean
}

export interface NovelDetail extends NovelItem {
  text: string
  series_id: string | null
  caption: string
}

export interface NovelListResponse {
  novels: NovelItem[]
  total: number
  page: number
  per_page: number
  pages: number
}
