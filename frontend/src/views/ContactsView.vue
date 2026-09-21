<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { api } from '../api'
import type { Stats } from '../types'

const stats = ref<Stats | null>(null)
const error = ref('')

onMounted(async () => {
  try {
    stats.value = await api.stats()
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Could not load contact stats'
  }
})
</script>

<template>
  <div class="space-y-5">
    <div>
      <h1 class="text-[28px] font-extrabold tracking-tight">Contact stats</h1>
      <p class="mt-1 text-sm text-slate">Public emails and people found on source posts and sites.</p>
    </div>
    <p v-if="error" class="rounded-2xl bg-red-50 px-3 py-2 text-sm text-red-700">{{ error }}</p>
    <section class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Contacts</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none text-leaf-2">{{ stats?.contacts ?? '—' }}</p>
        <p class="mt-2 text-[11px] text-slate">People found</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">With email</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.with_email ?? '—' }}</p>
        <p class="mt-2 text-[11px] text-slate">Public mailbox</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Contact discovery</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.contact_rate ?? 0 }}%</p>
        <p class="mt-2 text-[11px] text-slate">Leads with an email</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">No contact</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.no_contact ?? 0 }}</p>
        <p class="mt-2 text-[11px] text-slate">Marked by you</p>
      </article>
      <article class="card px-5 py-4">
        <p class="text-xs font-medium text-slate">Companies</p>
        <p class="mt-2 text-[32px] font-extrabold leading-none">{{ stats?.companies ?? '—' }}</p>
        <p class="mt-2 text-[11px] text-slate">Named brands</p>
      </article>
    </section>
  </div>
</template>
