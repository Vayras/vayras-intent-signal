<script setup lang="ts">
import { RouterLink, RouterView, useRoute } from 'vue-router'

const route = useRoute()
const links = [
  { to: '/', label: 'Leads' },
  { to: '/buckets', label: 'Buckets' },
  { to: '/stats', label: 'Tool stats' },
  { to: '/contacts', label: 'Contacts' },
  { to: '/scan', label: 'Scan' },
]
</script>

<template>
  <div class="flex min-h-screen bg-mist text-ink">
    <aside class="hidden w-56 shrink-0 flex-col border-r border-line bg-paper px-4 py-6 md:flex">
      <RouterLink to="/" class="mb-8 flex items-center gap-2.5 px-2">
        <span class="grid h-8 w-8 place-items-center rounded-full bg-leaf text-white">
          <span class="h-2 w-2 rounded-full bg-white"></span>
        </span>
        <span class="text-[15px] font-bold tracking-tight">Intent Radar</span>
      </RouterLink>
      <nav class="space-y-1 text-sm font-medium">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="flex items-center gap-3 rounded-2xl px-3 py-2.5"
          :class="route.path === link.to ? 'bg-leaf-soft text-leaf-2' : 'text-slate hover:bg-mist'"
        >
          {{ link.label }}
        </RouterLink>
      </nav>
    </aside>

    <div class="flex min-w-0 flex-1 flex-col">
      <nav class="flex flex-wrap gap-1 border-b border-line bg-paper px-4 py-3 md:hidden">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="pill"
          :class="route.path === link.to ? 'bg-leaf-soft text-leaf-2' : 'text-slate'"
        >
          {{ link.label }}
        </RouterLink>
      </nav>
      <main class="flex-1 overflow-auto px-4 py-5 sm:px-6">
        <RouterView />
      </main>
    </div>
  </div>
</template>
