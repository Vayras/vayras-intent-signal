import type { Lead, Meta, Provider, ScanJob, Stats } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  return response.json() as Promise<T>
}

export const api = {
  leads: (params: Record<string, string>) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(params)) {
      if (value) query.set(key, value)
    }
    const suffix = query.toString()
    return request<Lead[]>(`/api/leads${suffix ? `?${suffix}` : ''}`)
  },
  stats: () => request<Stats>('/api/stats'),
  meta: () => request<Meta>('/api/meta'),
  updateStatus: (id: number, status: string) =>
    request<Lead>(`/api/leads/${id}`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  dismissLead: (id: number) => request<{ ok: boolean }>(`/api/leads/${id}`, { method: 'DELETE' }),
  findContacts: (id: number) => request<Lead>(`/api/leads/${id}/contacts`, { method: 'POST' }),
  updateQuality: (id: number, quality: string) =>
    request<Lead>(`/api/leads/${id}/quality`, { method: 'PATCH', body: JSON.stringify({ quality }) }),
  leaveFeedback: (id: number, label: string, reason: string) =>
    request<Lead>(`/api/leads/${id}/feedback`, { method: 'POST', body: JSON.stringify({ label, reason }) }),
  draftOutreach: (id: number) => request<Lead>(`/api/leads/${id}/outreach`, { method: 'POST' }),
  startScan: () => request<ScanJob>('/api/scans', { method: 'POST' }),
  scans: () => request<ScanJob[]>('/api/scans'),
  scan: (id: number) => request<ScanJob>(`/api/scans/${id}`),
  providers: () => request<Provider[]>('/api/providers'),
}
