export function formatNum(n: number): string {
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return String(n)
}

export function processNovelText(text: string): string {
  if (!text) return ''
  text = text.replace(/\[newpage\]/g, '\n\n─────────────\n\n')
  text = text.replace(/\[chapter:(.*?)\]/g, '\n\n【$1】\n\n')
  text = text.replace(/\[pixivimage:(\d+)(?:-(\d+))?\]/g, '🖼️ [插图 pixiv/$1]')
  text = text.replace(/\[jump:(\d+)\]/g, '')
  text = text.replace(/\[\[rb:(.*?)\s*>\s*(.*?)\]\]/g, '$1($2)')
  return text
}
