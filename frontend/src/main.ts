import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import './style.css'
import ContactsView from './views/ContactsView.vue'
import RadarView from './views/RadarView.vue'
import ScanView from './views/ScanView.vue'
import StatsView from './views/StatsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', component: RadarView },
    { path: '/buckets', component: RadarView },
    { path: '/stats', component: StatsView },
    { path: '/contacts', component: ContactsView },
    { path: '/scan', component: ScanView },
  ],
})

createApp(App).use(router).mount('#app')
