export type View = 'gallery' | 'novels' | 'labeler' | 'danbooru' | 'stats'
export type GalleryMode = 'infinite' | 'paged'
export type MediaFilter = '' | 'image' | 'video'
export type LabelerTab = 'review' | 'history' | 'stats'
export type DanbooruLabelerTab = 'review' | 'history' | 'stats' | 'recommended'

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

// ---------------------------------------------------------------------------
// Labeler types (shared between local-gallery labeler and Danbooru labeler)
// ---------------------------------------------------------------------------

/**
 * Verdict values are the same on both labelers (matches backend regex
 * `^(liked|disliked|skipped)$`).
 */
export type LabelVerdict = 'liked' | 'disliked' | 'skipped'

export interface TagCount {
  tag: string
  count: number
}

/**
 * Generic paginated history response. Component code uses the concrete
 * specializations below; the generic exists so we don't repeat the
 * pagination shape twice.
 */
export interface PaginatedHistory<T> {
  images: T[]
  total: number
  page: number
  per_page: number
  pages: number
}

/**
 * Common labeler-stats fields. Concrete `LabelerStats` and
 * `DanbooruLabelerStats` extend this with their domain-specific buckets
 * (by_source vs by_rating, etc.) — those buckets are what the Stats UIs
 * actually visualize, so we keep two distinct types instead of forcing
 * a generic.
 */
export interface LabelerStatsBase {
  total_images: number
  liked: number
  disliked: number
  skipped: number
  total_labeled: number
  remaining: number
  top_tags: TagCount[]
}

// --- Local-gallery labeler ---------------------------------------------------

/**
 * Image payload returned by `/api/labeler/next`. Mirrors a subset of
 * `ImageItem` plus the labeler's lifecycle fields.
 */
export interface LabelerImage {
  id: number
  source: string
  source_id: string
  file_path: string
  url: string
  created_at: string
  date: string | null
  is_video: boolean
  thumb_url: string
  vision_score: number | null
  vision_scores?: Record<string, number>
}

export interface LabelerNextResponse {
  image: LabelerImage | null
  remaining: number
  total_labeled: number
}

export interface LabelerStats extends LabelerStatsBase {
  liked_by_source: Record<string, number>
  total_by_source: Record<string, number>
  labeled_by_source: Record<string, number>
  liked_top_auto_tags: TagCount[]
}

export interface LabeledImage extends LabelerImage {
  verdict: string
  tags: string[]
}

export type LabelerHistoryResponse = PaginatedHistory<LabeledImage>

// --- Danbooru labeler --------------------------------------------------------

export interface DanbooruImage {
  id: number
  ext: string
  score: number
  rating: string
  created_at: string
  file_size: number
  tags: string
  tag_categories: Record<string, string[]>
  is_video: boolean
  thumb_url: string
  preview_url: string
  video_url: string | null
  preference_score?: number
  aesthetic_score?: number
  tag_score?: number
}

export interface DanbooruLabelerNextResponse {
  image: DanbooruImage | null
  remaining: number
  total_labeled: number
}

export interface DanbooruLabelerStats extends LabelerStatsBase {
  liked_by_rating: Record<string, number>
  labeled_by_rating: Record<string, number>
  rating_distribution: Record<string, Record<string, number>>
  liked_top_danbooru_tags: TagCount[]
}

/**
 * Danbooru's labeled-image schema is intentionally *not* a structural
 * extension of `LabeledImage` — the storage shape differs (no source/url,
 * has ext/score/rating/preview_url/video_url, no vision_scores map).
 * Keeping a separate type preserves accuracy at the call sites.
 */
export interface DanbooruLabeledImage {
  id: number
  ext: string
  score: number
  rating: string
  danbooru_tags: string
  is_video: boolean
  thumb_url: string
  preview_url: string
  video_url: string | null
  verdict: string
  updated_at: string
  tags: string[]
  vision_score?: number | null
}

export type DanbooruLabelerHistoryResponse = PaginatedHistory<DanbooruLabeledImage>

export interface DanbooruRecommendedResponse extends PaginatedHistory<DanbooruLabeledImage & { preference_score: number }> {
  model_info: { auc: number; n_samples: number; model_type: string }
}
