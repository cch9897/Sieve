export interface SourceMeta {
  label: string
  dotClass: string
  chipClass: string
  softClass: string
  color: string
}

export const SOURCE_META: Record<string, SourceMeta> = {
  danbooru: {
    label: 'Danbooru',
    dotClass: 'bg-blue-400',
    chipClass: 'bg-blue-500/15 text-blue-200 border-blue-500/30',
    softClass: 'bg-blue-500/10 text-blue-200',
    color: '#60a5fa',
  },
  gelbooru: {
    label: 'Gelbooru',
    dotClass: 'bg-emerald-400',
    chipClass: 'bg-emerald-500/15 text-emerald-200 border-emerald-500/30',
    softClass: 'bg-emerald-500/10 text-emerald-200',
    color: '#34d399',
  },
  konachan: {
    label: 'Konachan',
    dotClass: 'bg-violet-400',
    chipClass: 'bg-violet-500/15 text-violet-200 border-violet-500/30',
    softClass: 'bg-violet-500/10 text-violet-200',
    color: '#a78bfa',
  },
  pixiv: {
    label: 'Pixiv',
    dotClass: 'bg-pink-400',
    chipClass: 'bg-pink-500/15 text-pink-200 border-pink-500/30',
    softClass: 'bg-pink-500/10 text-pink-200',
    color: '#f472b6',
  },
  yandere: {
    label: 'Yande.re',
    dotClass: 'bg-amber-400',
    chipClass: 'bg-amber-500/15 text-amber-200 border-amber-500/30',
    softClass: 'bg-amber-500/10 text-amber-200',
    color: '#fbbf24',
  },
}

export function getSourceMeta(source: string): SourceMeta {
  return SOURCE_META[source] || {
    label: source,
    dotClass: 'bg-slate-400',
    chipClass: 'bg-slate-500/15 text-slate-200 border-slate-500/30',
    softClass: 'bg-slate-500/10 text-slate-200',
    color: '#94a3b8',
  }
}
