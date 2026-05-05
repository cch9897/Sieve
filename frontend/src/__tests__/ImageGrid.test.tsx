import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ImageGrid from '../components/ImageGrid'
import type { ImageItem } from '../types'

const mockImage: ImageItem = {
  id: 1,
  source: 'pixiv',
  source_id: '100',
  file_path: 'downloads/test1.jpg',
  url: 'https://pixiv.net/100',
  created_at: '2024-01-01',
  date: '2024-01-01',
  subfolder: null,
  is_video: false,
  thumb_url: '/api/thumb/downloads/test1.jpg',
}

describe('ImageGrid', () => {
  it('renders images in masonry layout', () => {
    const onClick = vi.fn()
    render(<ImageGrid images={[mockImage]} onImageClick={onClick} loading={false} />)

    const container = document.querySelector('.masonry')
    expect(container).toBeInTheDocument()
    const items = container!.querySelectorAll('.masonry-item')
    expect(items.length).toBeGreaterThan(0)
  })

  it('shows skeleton placeholders while loading', () => {
    const onClick = vi.fn()
    render(<ImageGrid images={[]} onImageClick={onClick} loading={true} />)

    const skeletonItems = document.querySelectorAll('.animate-pulse')
    expect(skeletonItems.length).toBeGreaterThan(0)
  })

  it('shows EmptyState when images empty and not loading', () => {
    const onClick = vi.fn()
    render(<ImageGrid images={[]} onImageClick={onClick} loading={false} />)

    // EmptyState component renders the title text
    expect(screen.getByText('这里暂时是空的')).toBeInTheDocument()
  })
})
