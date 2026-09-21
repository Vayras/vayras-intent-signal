<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '../api'
import { formatDay, pretty, sourceLabel } from '../labels'
import type { Filters, Lead, Meta } from '../types'

const emptyFilters = (): Filters => ({
  intent_type: '',
  country: 'India',
  industry: '',
  intent_strength: '',
  campaign_type: '',
  source: '',
  status: '',
  q: '',
  since: '',
  live_only: 'true',
  quality: '',
  buyer: 'brands',
})

const leads = ref<Lead[]>([])
const meta = ref<Meta | null>(null)
const filters = ref<Filters>(emptyFilters())
const selectedId = ref<number | null>(null)
const loading = ref(true)
const error = ref('')
const busy = ref('')
const searchedContact = ref(false)
const editing = ref(false)
const feedbackReason = ref('')
const feedbackLabels = [
  ['correct_lead', 'Correct lead'],
  ['false_positive', 'False positive'],
  ['wrong_intent_type', 'Wrong intent'],
  ['wrong_company', 'Wrong company'],
  ['wrong_urgency', 'Wrong urgency'],
  ['duplicate', 'Duplicate'],
]

const route = useRoute()
const onBuckets = computed(() => route.path === '/buckets')
const buckets = ['genuine', 'shortlist', 'false_positive', 'no_contact']
const selected = computed(() => leads.value.find((lead) => lead.id === selectedId.value) || null)

function primaryContact(lead: Lead) {
  return lead.contacts.find((person) => person.email) || lead.contacts[0] || null
}

async function load(silent = false) {
  if (!silent) loading.value = true
  error.value = ''
  try {
    const [leadRows, metaRow] = await Promise.all([
      api.leads(filters.value),
      meta.value ? Promise.resolve(meta.value) : api.meta(),
    ])
    leads.value = leadRows
    meta.value = metaRow
    if (selectedId.value && !leadRows.some((lead) => lead.id === selectedId.value)) {
      selectedId.value = null
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not load leads'
  } finally {
    loading.value = false
  }
}

function replaceLead(next: Lead) {
  leads.value = leads.value.map((lead) => (lead.id === next.id ? next : lead))
}

async function setStatus(lead: Lead, status: string) {
  busy.value = 'status'
  try {
    replaceLead(await api.updateStatus(lead.id, status))
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Status update failed'
  } finally {
    busy.value = ''
  }
}

async function findContact(lead: Lead) {
  busy.value = 'contact'
  try {
    replaceLead(await api.findContacts(lead.id))
    searchedContact.value = true
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Contact lookup failed'
  } finally {
    busy.value = ''
  }
}

function selectLead(lead: Lead) {
  selectedId.value = lead.id
  searchedContact.value = lead.contacts.length > 0
  if (!lead.contacts.length) void findContact(lead)
}

async function dismissLead(lead: Lead, event?: Event) {
  event?.stopPropagation()
  busy.value = 'dismiss'
  try {
    await api.dismissLead(lead.id)
    leads.value = leads.value.filter((row) => row.id !== lead.id)
    if (selectedId.value === lead.id) selectedId.value = null
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not delete suggestion'
  } finally {
    busy.value = ''
  }
}

async function setQuality(lead: Lead, quality: string) {
  busy.value = 'quality'
  try {
    replaceLead(await api.updateQuality(lead.id, quality))
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Quality update failed'
  } finally {
    busy.value = ''
  }
}

async function sendFeedback(lead: Lead, label: string) {
  busy.value = 'feedback'
  try {
    const next = await api.leaveFeedback(lead.id, label, feedbackReason.value)
    feedbackReason.value = ''
    if (label === 'duplicate') {
      leads.value = leads.value.filter((row) => row.id !== lead.id)
      selectedId.value = null
    } else {
      replaceLead(next)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Feedback failed'
  } finally {
    busy.value = ''
  }
}

async function draft(lead: Lead) {
  busy.value = 'draft'
  try {
    replaceLead(await api.draftOutreach(lead.id))
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Draft failed'
  } finally {
    busy.value = ''
  }
}

function sourceHref(url: string) {
  return url.startsWith('fixture://') ? '#' : url
}

function closeLead() {
  selectedId.value = null
}

function onKey(event: KeyboardEvent) {
  if (event.key === 'Escape') closeLead()
}

function applyBucketRoute() {
  if (onBuckets.value) {
    if (!buckets.includes(filters.value.quality)) filters.value.quality = 'shortlist'
  } else {
    filters.value.quality = ''
  }
}

let poll: number | undefined
onMounted(() => {
  applyBucketRoute()
  void load()
  window.addEventListener('keydown', onKey)
  poll = window.setInterval(() => {
    if (!busy.value) void load(true)
  }, 15000)
})
watch(
  () => route.path,
  () => {
    applyBucketRoute()
    void load()
  },
)
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  if (poll) window.clearInterval(poll)
})
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-[28px] font-extrabold tracking-tight">{{ onBuckets ? 'Buckets' : 'Leads' }}</h1>
        <p class="mt-1 text-sm text-slate">
          {{ onBuckets ? 'Leads you have already sorted.' : 'Plan, prioritize, and act on brands asking in India.' }}
        </p>
      </div>
      <RouterLink to="/scan" class="pill bg-ink text-white">Scan now</RouterLink>
    </div>

    <form class="card grid gap-2 p-3 sm:grid-cols-4 lg:grid-cols-8" @change="load">
      <input
        v-model="filters.q"
        class="field sm:col-span-2"
        placeholder="Search company or evidence"
        @keydown.enter.prevent="load"
      />
      <select v-model="filters.intent_type" class="field">
        <option value="">Intent type</option>
        <option v-for="item in meta?.intent_types" :key="item" :value="item">{{ pretty(item) }}</option>
      </select>
      <select v-model="filters.intent_strength" class="field">
        <option value="">Strength</option>
        <option v-for="item in meta?.strengths" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="filters.campaign_type" class="field">
        <option value="">Campaign</option>
        <option v-for="item in meta?.campaign_types" :key="item" :value="item">{{ pretty(item) }}</option>
      </select>
      <select v-model="filters.industry" class="field">
        <option value="">Industry</option>
        <option v-for="item in meta?.industries" :key="item" :value="item">{{ item }}</option>
      </select>
      <select v-model="filters.source" class="field">
        <option value="">Source</option>
        <option v-for="item in meta?.platforms" :key="item" :value="item">{{ pretty(item) }}</option>
      </select>
      <select v-model="filters.status" class="field">
        <option value="">Status</option>
        <option v-for="item in meta?.statuses" :key="item" :value="item">{{ item }}</option>
      </select>
      <label class="field flex items-center gap-2 text-sm text-slate sm:col-span-2">
        <span class="shrink-0">Since</span>
        <input v-model="filters.since" type="date" class="w-full bg-transparent" />
      </label>
      <select v-if="!onBuckets" v-model="filters.quality" class="field">
        <option value="">Quality</option>
        <option v-for="item in meta?.qualities" :key="item" :value="item">{{ pretty(item) }}</option>
      </select>
      <label class="field flex items-center gap-2 bg-leaf-soft text-sm text-leaf-2 sm:col-span-2">
        <input v-model="filters.buyer" type="checkbox" true-value="brands" false-value="" class="accent-leaf" />
        D2C + large B2C only
      </label>
    </form>

    <div v-if="onBuckets" class="flex flex-wrap gap-2">
      <button
        v-for="bucket in buckets"
        :key="bucket"
        class="pill"
        :class="filters.quality === bucket ? 'bg-ink text-white' : 'bg-mist text-slate'"
        type="button"
        @click="filters.quality = bucket; load()"
      >
        {{ pretty(bucket) }}
      </button>
    </div>

    <p v-if="error" class="rounded-2xl bg-red-50 px-3 py-2 text-sm text-red-700">
      {{ error }}
    </p>

    <div v-if="loading" class="h-64 animate-pulse bg-mist"></div>

    <div
      v-else-if="!leads.length"
      class="card px-6 py-16 text-center"
    >
      <p class="text-2xl font-extrabold tracking-tight">No opportunities in this slice</p>
      <p class="mt-2 text-sm text-slate">
        Discovery is running. New leads show up here when OpenAI confirms a brand is asking.
      </p>
    </div>

    <div v-else>
        <div class="mb-2 flex items-center justify-end gap-3">
          <p v-if="editing" class="text-xs text-slate">Deletes stay gone and train the next scan.</p>
          <button
            class="pill"
            :class="editing ? 'bg-leaf-soft text-leaf-2' : 'bg-mist text-slate'"
            type="button"
            @click="editing = !editing"
          >
            {{ editing ? 'Done' : 'Edit table' }}
          </button>
        </div>
      <div class="max-h-[min(78vh,calc(100dvh-12rem))] overflow-auto bg-paper outline outline-1 outline-[#d7dbe2]">
        <table class="w-full min-w-[720px] border-collapse text-left text-sm">
          <thead class="sticky top-0 z-10 bg-ink text-[11px] font-semibold uppercase tracking-[0.12em] text-white">
            <tr>
              <th v-if="editing" class="px-3 py-3"> </th>
              <th class="px-3 py-3">Company</th>
              <th class="px-3 py-3">Contact</th>
              <th class="px-3 py-3">Email</th>
              <th class="px-3 py-3">Intent</th>
              <th class="px-3 py-3">Score</th>
              <th class="px-3 py-3">Source</th>
              <th class="px-3 py-3">Where</th>
              <th class="px-3 py-3">When</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="lead in leads"
              :key="lead.id"
              class="cursor-pointer border-b border-line transition"
              :class="selectedId === lead.id ? 'bg-leaf-soft' : 'hover:bg-mist'"
              tabindex="0"
              role="button"
              :aria-pressed="selectedId === lead.id"
              @click="selectLead(lead)"
              @keydown.enter.prevent="selectLead(lead)"
            >
              <td v-if="editing" class="px-3 py-3">
                <button
                  class="pill bg-red-50 text-red-600 disabled:opacity-50"
                  type="button"
                  :disabled="busy === 'dismiss'"
                  @click="dismissLead(lead, $event)"
                >
                  Delete
                </button>
              </td>
              <td class="max-w-[180px] truncate px-3 py-3 font-semibold">
                {{ lead.company?.name || 'Unknown company' }}
                <span
                  v-if="lead.source_url.startsWith('fixture://')"
                  class="ml-1 rounded-full bg-mist px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.12em] text-slate"
                >sample</span>
              </td>
              <td class="max-w-[160px] truncate px-3 py-3">
                <template v-if="primaryContact(lead)">
                  {{ primaryContact(lead)?.name || primaryContact(lead)?.job_title || 'Named on source' }}
                </template>
                <span v-else-if="busy === 'contact' && selectedId === lead.id" class="text-slate">Looking…</span>
                <span v-else class="text-slate">—</span>
              </td>
              <td class="max-w-[200px] truncate px-3 py-3 text-slate">
                {{ primaryContact(lead)?.email || '—' }}
              </td>
              <td class="whitespace-nowrap px-3 py-3 font-medium text-leaf-2">
                {{ lead.intent_strength }} · {{ pretty(lead.intent_type) }}
              </td>
              <td class="px-3 py-3 text-slate">{{ lead.score }}</td>
              <td class="whitespace-nowrap px-3 py-3 text-slate">
                {{ sourceLabel(lead.source_url, lead.source_platform) }}
              </td>
              <td class="whitespace-nowrap px-3 py-3 text-slate">{{ lead.geography || '—' }}</td>
              <td class="whitespace-nowrap px-3 py-3 text-slate">{{ formatDay(lead.discovered_at) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="selected" class="fixed inset-0 z-40 flex items-center justify-center p-4">
        <button class="absolute inset-0 bg-ink/40" type="button" aria-label="Close lead" @click="closeLead"></button>
        <aside class="card relative z-10 max-h-[88vh] w-full max-w-lg overflow-y-auto p-5" role="dialog" aria-modal="true">
        <div class="mb-2 flex items-start justify-between gap-3">
          <p class="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate">Why now</p>
          <button class="pill bg-mist text-slate" type="button" @click="closeLead">Close</button>
        </div>
        <h3 class="mt-1 text-2xl font-extrabold tracking-tight">{{ selected.company?.name || 'Unknown company' }}</h3>
        <p class="mt-2 text-sm">They publicly stated they need {{ pretty(selected.intent_type).toLowerCase() }}.</p>
        <blockquote class="mt-4 rounded-2xl bg-mist px-3 py-3 text-sm italic">“{{ selected.evidence }}”</blockquote>
        <dl class="mt-4 space-y-2 text-sm">
          <div class="flex justify-between gap-4">
            <dt class="text-slate">Confidence</dt>
            <dd class="font-semibold">{{ selected.confidence || '—' }}%</dd>
          </div>
          <div v-if="selected.reasoning">
            <dt class="text-slate">Why</dt>
            <dd class="mt-1">{{ selected.reasoning }}</dd>
          </div>
          <div v-if="selected.critique">
            <dt class="text-slate">Critique</dt>
            <dd class="mt-1">{{ selected.critique }}</dd>
          </div>
        </dl>
        <div v-if="selected.similar_cases?.length" class="mt-4 space-y-1 text-xs text-slate">
          <p class="font-semibold uppercase tracking-[0.14em]">Similar historical cases</p>
          <p v-for="(item, index) in selected.similar_cases" :key="index">
            {{ item.verdict }} · {{ item.company || item.label }} — {{ item.evidence }}
          </p>
        </div>

        <dl v-if="selected.company" class="mt-4 space-y-2 text-sm">
          <div v-if="selected.company.website" class="flex justify-between gap-4">
            <dt class="text-slate">Website</dt>
            <dd><a class="font-medium text-leaf-2 underline decoration-leaf/30" :href="selected.company.website" target="_blank" rel="noreferrer">{{ selected.company.domain || selected.company.website }}</a></dd>
          </div>
          <div v-if="selected.company.city" class="flex justify-between gap-4">
            <dt class="text-slate">City</dt>
            <dd>{{ selected.company.city }}</dd>
          </div>
          <div v-if="selected.company.linkedin_url" class="flex justify-between gap-4">
            <dt class="text-slate">LinkedIn</dt>
            <dd><a class="font-medium text-leaf-2 underline decoration-leaf/30" :href="selected.company.linkedin_url" target="_blank" rel="noreferrer">Company page</a></dd>
          </div>
          <div v-if="selected.company.instagram_url" class="flex justify-between gap-4">
            <dt class="text-slate">Instagram</dt>
            <dd><a class="font-medium text-leaf-2 underline decoration-leaf/30" :href="selected.company.instagram_url" target="_blank" rel="noreferrer">Profile</a></dd>
          </div>
        </dl>

        <div class="mt-4 space-y-2 text-sm">
          <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate">Contacts</p>
          <ul v-if="selected.contacts.length" class="space-y-2">
            <li v-for="person in selected.contacts" :key="person.id">
              <p>{{ person.job_title || 'Unknown role' }}<span v-if="person.name"> · {{ person.name }}</span></p>
              <p class="text-slate">{{ person.email || 'No public email' }}</p>
              <p class="text-[11px] text-slate">{{ person.email_status }} · {{ person.source_url.startsWith('http') ? 'public page' : 'source post' }}</p>
            </li>
          </ul>
          <p v-else-if="searchedContact" class="text-slate">
            No public business email on the source post or company site. We do not guess mailboxes.
          </p>
          <p v-else class="text-slate">No public business email on the source or company site. We do not guess mailboxes.</p>
        </div>

        <dl class="mt-4 space-y-2 text-sm">
          <div class="flex justify-between gap-4">
            <dt class="text-slate">Source</dt>
            <dd>{{ sourceLabel(selected.source_url, selected.source_platform) }}</dd>
          </div>
          <div class="flex justify-between gap-4">
            <dt class="text-slate">When</dt>
            <dd>{{ formatDay(selected.discovered_at) }}</dd>
          </div>
          <div class="flex justify-between gap-4">
            <dt class="text-slate">Status</dt>
            <dd>
              <select
                class="field h-9"
                :value="selected.status"
                :disabled="busy === 'status'"
                @change="setStatus(selected, ($event.target as HTMLSelectElement).value)"
              >
                <option v-for="item in meta?.statuses" :key="item" :value="item">{{ item }}</option>
              </select>
            </dd>
          </div>
        </dl>

        <div class="mt-4 space-y-1 text-xs text-slate">
          <p class="font-semibold uppercase tracking-[0.14em]">Score breakdown</p>
          <p v-for="reason in selected.score_breakdown" :key="reason">{{ reason }}</p>
        </div>

        <div class="mt-5 flex flex-wrap gap-2">
          <a
            class="pill bg-mist"
            :href="sourceHref(selected.source_url)"
            :target="selected.source_url.startsWith('http') ? '_blank' : undefined"
            rel="noreferrer"
          >
            View source
          </a>
          <button
            class="pill bg-red-50 text-red-600 disabled:opacity-50"
            :disabled="busy === 'dismiss'"
            @click="dismissLead(selected)"
          >
            Delete
          </button>
          <button
            class="pill bg-mist disabled:opacity-50"
            :disabled="busy === 'contact'"
            @click="findContact(selected)"
          >
            {{ busy === 'contact' ? 'Searching…' : 'Search again' }}
          </button>
          <button
            class="pill bg-ink text-white disabled:opacity-50"
            :disabled="busy === 'draft'"
            @click="draft(selected)"
          >
            {{ busy === 'draft' ? 'Drafting…' : 'Draft outreach' }}
          </button>
        </div>
        <div class="mt-5 space-y-2">
          <p class="text-[11px] font-semibold uppercase tracking-[0.14em] text-slate">Was this right?</p>
          <textarea
            v-model="feedbackReason"
            class="field h-20 w-full py-2"
            placeholder="Why was this wrong? Historical campaign, generic article, creator looking for sponsors…"
          />
          <div class="flex flex-wrap gap-2">
            <button
              v-for="[label, name] in feedbackLabels"
              :key="label"
              class="pill bg-mist text-slate disabled:opacity-50"
              :disabled="busy === 'feedback'"
              type="button"
              @click="sendFeedback(selected, label)"
            >
              {{ name }}
            </button>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap gap-2">
          <button
            v-for="label in ['genuine', 'shortlist', 'false_positive', 'no_contact']"
            :key="label"
            class="pill disabled:opacity-50"
            :class="selected.quality === label ? 'bg-leaf-soft text-leaf-2' : 'bg-mist text-slate'"
            :disabled="busy === 'quality'"
            @click="setQuality(selected, label)"
          >
            {{ pretty(label) }}
          </button>
        </div>

        <pre
          v-if="selected.outreach_draft"
          class="mt-4 overflow-x-auto whitespace-pre-wrap rounded-2xl bg-mist p-3 text-xs leading-relaxed"
        >{{ selected.outreach_draft }}</pre>
        </aside>
      </div>
    </Teleport>
  </div>
</template>
