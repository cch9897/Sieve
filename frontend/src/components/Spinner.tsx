interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg'
  className?: string
}

const sizes = { sm: 'h-5 w-5', md: 'h-8 w-8', lg: 'h-10 w-10' }

export default function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  return (
    <div
      className={[
        'animate-spin rounded-full border-2',
        'border-[var(--spinner-base)] border-t-[var(--spinner-accent)]',
        sizes[size],
        className,
      ].join(' ')}
      role="status"
      aria-label="加载中"
    />
  )
}
