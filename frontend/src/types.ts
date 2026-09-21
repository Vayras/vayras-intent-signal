export interface Company {
  id: number
  name: string
  domain: string | null
  industry: string | null
  country: string | null
  city: string | null
  website: string | null
  linkedin_url: string | null
  instagram_url: string | null
}

export interface Contact {
  id: number
  name: string | null
  job_title: string | null
  email: string | null
  email_status: string
  source_url: string
  discovered_at: string
}

export interface Lead {
  id: number
  company: Company | null
  intent_type: string
  intent_strength: string
  campaign_type: string | null
  geography: string | null
  industry: string | null
  urgency: string | null
  source_url: string
  source_platform: string
  evidence: string
  summary: string
  score: number
  score_breakdown: string[]
  status: string
  outreach_draft: string | null
  quality: string
  reviewed_at: string | null
  discovered_at: string
  contacts: Contact[]
  confidence: number
  reasoning: string
  critique: string
  similar_cases: SimilarCase[]
}

export interface SimilarCase {
  verdict: string
  company: string
  evidence: string
  label: string
}

export interface Stats {
  leads: number
  high_intent: number
  new_leads: number
  companies: number
  contacts: number
  last_scan_at: string | null
  reviewed: number
  genuine: number
  shortlist: number
  false_positive: number
  no_contact: number
  with_email: number
  genuine_rate: number
  false_positive_rate: number
  contact_rate: number
}

export interface Meta {
  intent_types: string[]
  strengths: string[]
  campaign_types: string[]
  statuses: string[]
  platforms: string[]
  industries: string[]
  countries: string[]
  qualities: string[]
  feedback_labels: string[]
}

export interface ScanJob {
  id: number
  status: string
  query_count: number
  pages_seen: number
  keyword_hits: number
  leads_found: number
  error: string | null
  started_at: string | null
  finished_at: string | null
  created_at: string
}

export interface Provider {
  name: string
  kind: string
  active: boolean
  detail: string
}

export interface Filters {
  intent_type: string
  country: string
  industry: string
  intent_strength: string
  campaign_type: string
  source: string
  status: string
  q: string
  since: string
  live_only: string
  quality: string
  buyer: string
}
