export const INTENT_LABELS: Record<string, string> = {
  LOOKING_FOR_INFLUENCERS: 'Looking for influencers',
  LOOKING_FOR_CREATORS: 'Looking for creators',
  NEEDS_UGC: 'Needs UGC creators',
  NEEDS_INFLUENCER_AGENCY: 'Needs an agency',
  HIRING_INFLUENCER_MARKETING: 'Hiring influencer marketing',
  CREATOR_CAMPAIGN: 'Creator campaign',
  PRODUCT_LAUNCH: 'Product launch',
  BRAND_AMBASSADOR: 'Brand ambassadors',
  ASKING_FOR_RECOMMENDATIONS: 'Asking for recommendations',
}

export const PLATFORM_LABELS: Record<string, string> = {
  reddit: 'Reddit',
  forum: 'Forum',
  job_board: 'Job board',
  news: 'News',
  company_site: 'Company site',
  x: 'X',
  linkedin: 'LinkedIn',
  instagram: 'Instagram',
  facebook: 'Facebook',
  youtube: 'YouTube',
  tiktok: 'TikTok',
  threads: 'Threads',
}

export function pretty(value: string | null | undefined): string {
  if (!value) return '—'
  return INTENT_LABELS[value] || PLATFORM_LABELS[value] || value.replaceAll('_', ' ')
}

export function sourceLabel(url: string, platform: string | null | undefined): string {
  const reddit = url.match(/reddit\.com\/r\/([^/?#]+)/i)
  if (reddit) return `Reddit · r/${reddit[1]}`
  if (/reddit\.com|redd\.it/i.test(url) || platform === 'reddit') return 'Reddit'
  return pretty(platform)
}

export function formatDay(iso: string): string {
  return new Date(iso).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}
