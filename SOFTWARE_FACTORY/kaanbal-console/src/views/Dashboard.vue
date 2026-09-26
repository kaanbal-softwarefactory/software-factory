<template>
  <div class="space-y-8 pb-12">

    <!-- ═══════════════════════════ HERO SECTION ═══════════════════════════ -->
    <div class="relative overflow-hidden rounded-2xl border border-white/10">
      <!-- Animated gradient background -->
      <div class="absolute inset-0 bg-gradient-to-br from-blue-600/20 via-purple-600/10 to-emerald-600/20 animate-gradient"></div>
      <div class="absolute inset-0 bg-[radial-gradient(ellipse_at_top_right,_var(--tw-gradient-stops))] from-blue-500/10 via-transparent to-transparent"></div>
      <!-- Grid pattern overlay -->
      <div class="absolute inset-0 opacity-[0.03]" style="background-image: url(&quot;data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'><rect width='40' height='40' fill='none' stroke='white' stroke-width='0.5'/></svg>&quot;)"></div>
      
      <div class="relative px-8 py-12 md:py-16">
        <div class="max-w-3xl">
          <!-- Badge -->
          <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-medium mb-6">
            <span class="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse"></span>
            Open Source Platform
          </div>

          <h1 class="text-4xl md:text-5xl font-extrabold leading-tight">
            <span class="bg-gradient-to-r from-white via-blue-100 to-white bg-clip-text text-transparent">Build anything.</span><br>
            <span class="bg-gradient-to-r from-blue-400 via-purple-400 to-emerald-400 bg-clip-text text-transparent">Ship everywhere.</span>
          </h1>

          <p class="mt-5 text-lg text-slate-400 leading-relaxed max-w-2xl">
            From an idea to production in minutes. Launch APIs, frontends, databases, and workflows 
            on Kubernetes — with templates, pipelines, and GitOps built in. 
            <span class="text-slate-300">Your factory. Your rules.</span>
          </p>

          <div class="mt-8 flex flex-wrap gap-3">
            <router-link to="/wizard" class="group relative inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white font-bold shadow-lg shadow-blue-600/25 hover:shadow-blue-500/40 transition-all hover:-translate-y-0.5">
              <span class="text-lg">🚀</span> Launch New App
              <svg class="w-4 h-4 group-hover:translate-x-0.5 transition-transform" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/></svg>
            </router-link>
            <router-link to="/templates" class="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-white/5 border border-white/10 hover:bg-white/10 hover:border-white/20 text-white font-medium transition-all">
              <span class="text-lg">📦</span> Browse Templates
            </router-link>
          </div>
        </div>

        <!-- Floating stats on right (desktop only) -->
        <div class="hidden lg:flex absolute right-8 top-1/2 -translate-y-1/2 flex-col gap-3">
          <div class="glass-panel px-5 py-3 rounded-xl border border-white/10 text-center min-w-[120px] backdrop-blur-xl">
            <p class="text-2xl font-bold text-white">{{ stats.total_apps ?? '—' }}</p>
            <p class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Apps Running</p>
          </div>
          <div class="glass-panel px-5 py-3 rounded-xl border border-white/10 text-center min-w-[120px] backdrop-blur-xl">
            <p class="text-2xl font-bold text-emerald-400">{{ templateCount }}</p>
            <p class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Templates</p>
          </div>
          <div class="glass-panel px-5 py-3 rounded-xl border border-white/10 text-center min-w-[120px] backdrop-blur-xl">
            <p class="text-2xl font-bold text-purple-400">∞</p>
            <p class="text-[10px] text-slate-500 uppercase tracking-wider font-medium">Possibilities</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ LIVE STATUS CARDS ═══════════════════════════ -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
      <div class="glass-panel p-4 rounded-xl border border-white/5 group hover:border-emerald-500/30 transition-all">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center text-emerald-400 group-hover:scale-110 transition-transform">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          </div>
          <div>
            <p class="text-xs text-slate-500 uppercase tracking-wider">Cluster</p>
            <p class="text-sm font-bold" :class="health.status === 'healthy' ? 'text-emerald-400' : 'text-yellow-400'">
              {{ health.status === 'healthy' ? 'Operational' : health.status || 'Loading...' }}
            </p>
          </div>
        </div>
      </div>

      <div class="glass-panel p-4 rounded-xl border border-white/5 group hover:border-blue-500/30 transition-all">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center text-blue-400 group-hover:scale-110 transition-transform">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>
          </div>
          <div>
            <p class="text-xs text-slate-500 uppercase tracking-wider">Deployments</p>
            <p class="text-sm font-bold text-white">{{ stats.total_apps ?? '—' }} Active</p>
          </div>
        </div>
      </div>

      <div class="glass-panel p-4 rounded-xl border border-white/5 group hover:border-purple-500/30 transition-all">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center text-purple-400 group-hover:scale-110 transition-transform">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
          </div>
          <div>
            <p class="text-xs text-slate-500 uppercase tracking-wider">GitOps</p>
            <p class="text-sm font-bold text-purple-400">Synced</p>
          </div>
        </div>
      </div>

      <div class="glass-panel p-4 rounded-xl border border-white/5 group hover:border-amber-500/30 transition-all">
        <div class="flex items-center gap-3">
          <div class="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center text-amber-400 group-hover:scale-110 transition-transform">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
          </div>
          <div>
            <p class="text-xs text-slate-500 uppercase tracking-wider">Last 7 Days</p>
            <p class="text-sm font-bold text-white">{{ stats.apps_created_last_7_days ?? 0 }} New Apps</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ WHAT YOU CAN BUILD ═══════════════════════════ -->
    <div>
      <div class="flex items-center justify-between mb-5">
        <div>
          <h2 class="text-xl font-bold text-white">What you can build</h2>
          <p class="text-sm text-slate-500 mt-0.5">Pick a technology and go from zero to production</p>
        </div>
        <router-link to="/templates" class="text-xs text-blue-400 hover:text-blue-300 transition-colors">View all templates →</router-link>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div v-for="tech in techShowcase" :key="tech.name" 
             @click="$router.push({ path: '/wizard', query: { template: tech.templateId } })"
             class="group cursor-pointer glass-panel rounded-xl p-4 border border-white/5 hover:border-white/20 transition-all hover:-translate-y-1 hover:shadow-lg text-center relative overflow-hidden">
          <div class="absolute top-0 left-0 right-0 h-0.5 opacity-60" :style="{ background: tech.color }"></div>
          <span class="text-3xl block mb-2 group-hover:scale-110 transition-transform" :style="{ filter: 'drop-shadow(0 0 8px ' + tech.color + '40)' }">{{ tech.icon }}</span>
          <p class="text-xs font-bold text-white">{{ tech.name }}</p>
          <p class="text-[10px] text-slate-500 mt-0.5">{{ tech.tagline }}</p>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ THE VISION ═══════════════════════════ -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
      <!-- Card 1: For Builders -->
      <div class="glass-panel rounded-2xl p-6 border border-white/5 hover:border-blue-500/20 transition-all group">
        <div class="w-12 h-12 rounded-xl bg-blue-500/10 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
          <span class="text-2xl">🧬</span>
        </div>
        <h3 class="font-bold text-white mb-2">For Researchers & Builders</h3>
        <p class="text-sm text-slate-400 leading-relaxed">
          Bioinformatics models, astronomy APIs, IoT data pipelines — focus on your science, 
          we handle infrastructure. Spin up a FastAPI + MongoDB stack in 2 minutes.
        </p>
        <div class="mt-4 flex flex-wrap gap-1">
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-blue-500/10 text-blue-400 border border-blue-500/20">Bioinformatics</span>
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20">Astronomy</span>
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">IoT / Edge</span>
        </div>
      </div>

      <!-- Card 2: Standards -->
      <div class="glass-panel rounded-2xl p-6 border border-white/5 hover:border-purple-500/20 transition-all group">
        <div class="w-12 h-12 rounded-xl bg-purple-500/10 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
          <span class="text-2xl">📐</span>
        </div>
        <h3 class="font-bold text-white mb-2">Standards Built In</h3>
        <p class="text-sm text-slate-400 leading-relaxed">
          Every app gets CI/CD pipelines, Dockerfiles, health checks, and GitOps manifests. 
          Create your own templates and enforce team standards across all projects.
        </p>
        <div class="mt-4 flex flex-wrap gap-1">
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-400 border border-purple-500/20">CI/CD</span>
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-pink-500/10 text-pink-400 border border-pink-500/20">GitOps</span>
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 border border-amber-500/20">Custom Templates</span>
        </div>
      </div>

      <!-- Card 3: AI Agents -->
      <div class="glass-panel rounded-2xl p-6 border border-white/5 hover:border-emerald-500/20 transition-all group relative overflow-hidden">
        <div class="absolute top-2 right-2">
          <span class="text-[8px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-medium">Coming Soon</span>
        </div>
        <div class="w-12 h-12 rounded-xl bg-emerald-500/10 flex items-center justify-center mb-4 group-hover:scale-110 transition-transform">
          <span class="text-2xl">🤖</span>
        </div>
        <h3 class="font-bold text-white mb-2">AI Agent Orchestration</h3>
        <p class="text-sm text-slate-400 leading-relaxed">
          Connect MCP servers to Atlassian, create epics with well-defined stories, 
          and let multiple agents work on features in parallel. The factory that builds itself.
        </p>
        <div class="mt-4 flex flex-wrap gap-1">
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">MCP Servers</span>
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">Multi-Agent</span>
          <span class="text-[9px] px-2 py-0.5 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">Jira / Atlassian</span>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ HOW IT WORKS ═══════════════════════════ -->
    <div>
      <h2 class="text-xl font-bold text-white mb-5">How it works</h2>
      <div class="relative">
        <!-- Connection line -->
        <div class="absolute top-8 left-0 right-0 h-px bg-gradient-to-r from-blue-500/30 via-purple-500/30 to-emerald-500/30 hidden md:block"></div>
        
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
          <div v-for="(step, i) in howItWorks" :key="i" class="relative glass-panel rounded-xl p-5 border border-white/5">
            <div class="w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold mb-3"
                 :class="step.numClass">
              {{ i + 1 }}
            </div>
            <h4 class="font-bold text-white text-sm mb-1">{{ step.title }}</h4>
            <p class="text-xs text-slate-500 leading-relaxed">{{ step.desc }}</p>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ QUICK ACTIONS ═══════════════════════════ -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="glass-panel rounded-xl p-5 border border-white/5 hover:border-blue-500/20 transition-all">
        <div class="flex items-start gap-4">
          <div class="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center text-blue-400 shrink-0">
            <span class="text-xl">⚡</span>
          </div>
          <div class="flex-1">
            <h3 class="font-bold text-white text-sm">Quick Deploy</h3>
            <p class="text-xs text-slate-500 mt-1">Jump into the wizard and launch a production-ready app in under 3 minutes.</p>
            <router-link to="/wizard" class="inline-flex items-center gap-1 mt-3 text-xs text-blue-400 hover:text-blue-300 font-medium transition-colors">
              Open Wizard <span>→</span>
            </router-link>
          </div>
        </div>
      </div>

      <div class="glass-panel rounded-xl p-5 border border-white/5 hover:border-purple-500/20 transition-all">
        <div class="flex items-start gap-4">
          <div class="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center text-purple-400 shrink-0">
            <span class="text-xl">🔧</span>
          </div>
          <div class="flex-1">
            <h3 class="font-bold text-white text-sm">Create a Template</h3>
            <p class="text-xs text-slate-500 mt-1">Standardize your team's stack. Package Dockerfiles, pipelines, and manifests into reusable templates.</p>
            <router-link to="/templates" class="inline-flex items-center gap-1 mt-3 text-xs text-purple-400 hover:text-purple-300 font-medium transition-colors">
              Browse Templates <span>→</span>
            </router-link>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ APPS OVERVIEW ═══════════════════════════ -->
    <div v-if="apps.length > 0">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-xl font-bold text-white">Your Applications</h2>
        <router-link to="/apps" class="text-xs text-blue-400 hover:text-blue-300 transition-colors">View all →</router-link>
      </div>
      <div class="space-y-3">
        <div v-for="group in groupedAppsPreview" :key="group.name">
          <div class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">{{ group.name }}</div>
          <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            <div v-for="app in group.apps" :key="app.name"
                 @click="$router.push('/apps')"
                 class="glass-panel rounded-xl p-4 border border-white/5 hover:border-white/15 transition-all cursor-pointer group">
              <div class="flex items-center justify-between mb-2">
                <h4 class="text-sm font-bold text-white group-hover:text-blue-400 transition-colors truncate">{{ app.name }}</h4>
                <span :class="['text-[9px] px-2 py-0.5 rounded-full font-medium', statusColors[app.status] || 'bg-slate-500/10 text-slate-400']">
                  {{ app.status }}
                </span>
              </div>
              <div class="flex items-center gap-2">
                <span class="text-[10px] text-slate-500">{{ app.template }}</span>
                <span class="text-slate-700">·</span>
                <div class="flex gap-1">
                  <span v-for="env in (app.environments || ['prod'])" :key="env"
                        :class="['text-[8px] px-1.5 py-0.5 rounded font-medium', envBadgeColors[env] || 'bg-slate-700 text-slate-400']">
                    {{ env }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ═══════════════════════════ FOOTER ═══════════════════════════ -->
    <div class="text-center pt-4 border-t border-white/5">
      <p class="text-xs text-slate-600">
        Kaanbal Engine · Created by Kaanbal BioTech · Built with 
        <span class="text-blue-400">Vue</span> + <span class="text-emerald-400">FastAPI</span> + <span class="text-purple-400">K3s</span> + <span class="text-amber-400">ArgoCD</span>
      </p>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

const stats = ref({})
const health = ref({})
const apps = ref([])
const templates = ref([])

const templateCount = computed(() => templates.value.length || '—')

const groupedAppsPreview = computed(() => {
  const buckets = new Map()
  apps.value.slice(0, 12).forEach(app => {
    const group = (app.app_group || '').trim()
    const key = group || 'ungrouped'
    const label = group || 'Ungrouped'
    if (!buckets.has(key)) buckets.set(key, { name: label, apps: [] })
    buckets.get(key).apps.push(app)
  })
  return Array.from(buckets.values())
})

const statusColors = {
  running: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
  healthy: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20',
  deploying: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
  error: 'bg-red-500/10 text-red-400 border border-red-500/20',
  degraded: 'bg-yellow-500/10 text-yellow-400 border border-yellow-500/20',
  created: 'bg-slate-500/10 text-slate-400 border border-slate-500/20'
}

const envBadgeColors = {
  dev: 'bg-yellow-500/20 text-yellow-400',
  staging: 'bg-orange-500/20 text-orange-400',
  prod: 'bg-emerald-500/20 text-emerald-400'
}

const techShowcase = [
  { name: 'Vue 3', icon: '🟢', color: '#42b883', tagline: 'Modern SPA', templateId: 'vue3-spa' },
  { name: 'FastAPI', icon: '🐍', color: '#009688', tagline: 'Python API', templateId: 'fastapi-api' },
  { name: 'MongoDB', icon: '🍃', color: '#47a248', tagline: 'NoSQL DB', templateId: 'mongodb' },
  { name: 'React', icon: '⚛️', color: '#61dafb', tagline: 'UI Library', templateId: 'react-spa' },
  { name: 'n8n', icon: '🔄', color: '#ea4b71', tagline: 'Workflows', templateId: 'n8n' },
  { name: 'Next.js', icon: '▲', color: '#ffffff', tagline: 'Fullstack', templateId: 'next-app' }
]

const howItWorks = [
  { title: 'Choose a Template', desc: 'Pick from battle-tested templates or create your own with your favorite stack.', numClass: 'bg-blue-500/20 text-blue-400' },
  { title: 'Configure & Launch', desc: 'Name it, pick environments, set exposure. The wizard handles repos, pipelines, and manifests.', numClass: 'bg-purple-500/20 text-purple-400' },
  { title: 'Auto CI/CD', desc: 'Push code → Pipeline builds → Docker image → ArgoCD syncs to cluster. Fully automated.', numClass: 'bg-emerald-500/20 text-emerald-400' },
  { title: 'Monitor & Scale', desc: 'Track health, logs, and resources. Scale replicas, add environments, or connect agents.', numClass: 'bg-amber-500/20 text-amber-400' }
]

onMounted(async () => {
  const [statsRes, healthRes, appsRes, templatesRes] = await Promise.allSettled([
    axios.get('/api/v1/system/stats'),
    axios.get('/api/v1/system/health'),
    axios.get('/api/v1/apps'),
    axios.get('/api/v1/templates')
  ])
  
  if (statsRes.status === 'fulfilled') stats.value = statsRes.value.data
  if (healthRes.status === 'fulfilled') health.value = healthRes.value.data
  if (appsRes.status === 'fulfilled') apps.value = appsRes.value.data
  if (templatesRes.status === 'fulfilled') templates.value = templatesRes.value.data
})
</script>

<style scoped>
@keyframes gradient {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.7; }
}
.animate-gradient {
  animation: gradient 8s ease-in-out infinite;
}
</style>
