<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import { formatDay } from '../labels'
import type { Stats } from '../types'

const stats = ref<Stats | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    stats.value = await api.stats()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not load stats'
  }
})
</script>

<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-[28px] font-extrabold tracking-tight">Tool stats</h1>
      <p class="mt-1 text-sm text-slate">How the radar is performing across scans and reviews.</p>
    </div>
    <p v-if="error" class="rounded-2xl bg-red-50 px-3 py-2 text-sm text-red-700">{{ error }}</p>
    <section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Leads</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none text-leaf-2">{{ stats?.leads ?? '—' }}</p>
        <p class="mt-2 text-[11px] text-slate">India only</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">High intent</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.high_intent ?? '—' }}</p>
        <p class="mt-2 text-[11px] text-slate">Ready to reach</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Unread</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.new_leads ?? '—' }}</p>
        <p class="mt-2 text-[11px] text-slate">New since last scan</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Genuine / reviewed</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.genuine ?? 0 }}/{{ stats?.reviewed ?? 0 }}</p>
        <p class="mt-2 text-[11px] text-slate">Human labelled</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Genuine rate</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.genuine_rate ?? 0 }}%</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Shortlist</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none text-leaf-2">{{ stats?.shortlist ?? 0 }}</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">False positive rate</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.false_positive_rate ?? 0 }}%</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Last scan</p>
        <p class="mt-2 text-2xl font-extrabold leading-none">{{ stats?.last_scan_at ? formatDay(stats.last_scan_at) : '—' }}</p>
      </article>
    </section>
  </div>
</template>
