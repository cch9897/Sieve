import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import FilterBar from '../components/FilterBar'

describe('FilterBar', () => {
  const defaultProps = {
    sources: ['pixiv', 'danbooru'],
    dates: ['2024-01-01', '2024-01-02'],
    selectedSource: '',
    selectedDate: '',
    selectedMedia: '' as const,
    sort: 'newest',
    onSourceChange: vi.fn(),
    onDateChange: vi.fn(),
    onMediaChange: vi.fn(),
    onSortChange: vi.fn(),
    total: 100,
    mode: 'infinite' as const,
    onModeChange: vi.fn(),
    expanded: true,
    onExpandedChange: vi.fn(),
  }

  it('renders filter panel when expanded', () => {
    render(<FilterBar {...defaultProps} />)

    const panel = document.querySelector('.editorial-panel')
    expect(panel).toBeInTheDocument()
  })

  it('shows total count with label', () => {
    render(<FilterBar {...defaultProps} />)

    expect(screen.getByText('总藏品')).toBeInTheDocument()
    expect(screen.getByText('100 项')).toBeInTheDocument()
  })

  it('renders mode switch buttons', () => {
    render(<FilterBar {...defaultProps} />)

    expect(screen.getByText('无限滚动')).toBeInTheDocument()
    expect(screen.getByText('分页')).toBeInTheDocument()
  })

  it('renders media filter buttons', () => {
    render(<FilterBar {...defaultProps} />)

    expect(screen.getByText('全部')).toBeInTheDocument()
    expect(screen.getByText('图片')).toBeInTheDocument()
    expect(screen.getByText('视频')).toBeInTheDocument()
  })
})
