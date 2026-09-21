<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { api } from '../api'
import type { Provider, ScanJob } from '../types'

const providers = ref<Provider[]>([])
const scans = ref<ScanJob[]>([])
const running = ref<ScanJob | null>(null)
const error = ref('')
const loading = ref(true)
let timer: number | undefined

async function refresh() {
  try {
    const [providerRows, scanRows] = await Promise.all([api.providers(), api.scans()])
    providers.value = providerRows
    scans.value = scanRows.filter((job) => job.status === 'queued' || job.status === 'running')
    running.value = scans.value[0] || null
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not load scan status'
  } finally {
    loading.value = false
  }
}

async function start() {
  error.value = ''
  try {
    running.value = await api.startScan()
    if (!timer) timer = window.setInterval(refresh, 1200)
    await refresh()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Scan failed to start'
  }
}

onMounted(() => {
  void refresh()
  timer = window.setInterval(refresh, 4000)
})
onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="space-y-6">
    <section class="card max-w-2xl p-6">
      <p class="text-xs font-semibold uppercase tracking-[0.16em] text-leaf">Discovery</p>
      <h1 class="mt-2 text-[28px] font-extrabold tracking-tight">Discovery runs on its own.</h1>
      <p class="mt-3 text-sm leading-relaxed text-slate">
        One continuous scan. It never stops: 250 queries at a time, next batch as soon as the queue drains, leads keep landing. Reddit is watched every 15 minutes.
        OpenAI classifies each hit, names the company, and looks up the public site. Contacts are pulled from the post and homepage — no click required.
        Outreach is never sent.
      </p>
      <button
        class="pill mt-5 bg-ink text-white disabled:opacity-50"
        :disabled="running?.status === 'queued' || running?.status === 'running'"
        @click="start"
      >
        {{ running?.status === 'running' || running?.status === 'queued' ? 'Scan in progress…' : 'Scan now' }}
      </button>
    </section>

    <p v-if="error" class="rounded-2xl bg-red-50 px-3 py-2 text-sm text-red-700">
      {{ error }}
    </p>

    <section>
      <h2 class="text-xl font-extrabold tracking-tight">Providers</h2>
      <div v-if="loading" class="mt-3 h-24 animate-pulse rounded-[1.35rem] bg-mist"></div>
      <div v-else class="mt-3 grid gap-3 md:grid-cols-2">
        <article v-for="provider in providers" :key="provider.kind" class="card p-5">
          <div class="flex items-center justify-between gap-3">
            <p class="text-sm text-slate">{{ provider.kind }}</p>
            <span
              class="pill"
              :class="provider.active ? 'bg-leaf-soft text-leaf-2' : 'bg-mist text-slate'"
            >
              {{ provider.active ? 'live' : 'fallback' }}
            </span>
          </div>
          <p class="mt-2 text-lg font-bold">{{ provider.name }}</p>
          <p class="mt-1 text-sm text-slate">{{ provider.detail }}</p>
        </article>
      </div>
    </section>

    <section>
      <h2 class="text-xl font-extrabold tracking-tight">Scan</h2>
      <div
        v-if="!scans.length"
        class="card mt-3 px-5 py-10 text-sm text-slate"
      >
        Waiting for the first automatic scan.
      </div>
      <ul v-else class="card mt-3 divide-y divide-line">
        <li v-for="job in scans" :key="job.id" class="grid gap-2 px-4 py-3 text-sm sm:grid-cols-5">
          <span class="capitalize font-semibold text-leaf-2">{{ job.status }}</span>
          <span>{{ job.query_count }} queries</span>
          <span>{{ job.pages_seen }} pages</span>
          <span>{{ job.keyword_hits }} keyword hits</span>
          <span>{{ job.leads_found }} new leads</span>
          <p v-if="job.error" class="text-red-600 sm:col-span-5">{{ job.error }}</p>
        </li>
      </ul>
    </section>
  </div>
</template>
