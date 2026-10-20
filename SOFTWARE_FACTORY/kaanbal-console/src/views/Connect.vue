<template>
  <section class="space-y-6">
    <header class="space-y-2">
      <h1 class="text-2xl font-semibold text-white">Conectar un agente</h1>
      <p class="text-slate-400 max-w-3xl">
        Un asistente (Claude, Cursor, Codex…) opera esta célula con dos datos: la URL de abajo y un
        token personal. No hay que instalar nada ni adivinar el dominio: la URL es la de
        <em>esta</em> instalación.
      </p>
    </header>

    <p v-if="error" role="alert" class="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
      {{ error }}
    </p>

    <div v-if="loading" class="text-sm text-slate-500">Leyendo la configuración de esta instalación…</div>

    <template v-else-if="info">
      <!-- La URL -->
      <div class="rounded-2xl border border-cyan-500/30 bg-cyan-500/5 p-6 space-y-4">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div class="space-y-1">
            <p class="text-xs font-semibold uppercase tracking-wider text-cyan-300">URL del MCP</p>
            <p class="font-mono text-lg sm:text-xl text-white break-all">{{ info.mcp_url || 'sin determinar' }}</p>
          </div>
          <button :class="copyClass" @click="copy(info.mcp_url, 'url')">
            {{ copied === 'url' ? '¡Copiada!' : 'Copiar' }}
          </button>
        </div>

        <div class="flex flex-wrap gap-2 text-xs">
          <span :class="['inline-block rounded-full border px-3 py-1', reachClass]">{{ reachTitle }}</span>
          <span class="inline-block rounded-full border border-white/15 px-3 py-1 text-slate-300">Kaanbal {{ info.version }}</span>
          <span v-if="info.domain" class="inline-block rounded-full border border-white/15 px-3 py-1 text-slate-300">{{ info.domain }}</span>
        </div>

        <p class="text-sm text-slate-400">{{ info.reach_label }} La URL sale {{ info.source_label }}.</p>

        <p v-if="info.reach === 'vpn'" class="text-sm text-amber-200 border border-amber-500/30 rounded-xl p-3">
          La API no está publicada en internet. Un agente fuera del tailnet no va a poder conectarse:
          publícala al instalar o conecta el equipo a la VPN.
        </p>
      </div>

      <!-- El token -->
      <div class="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-3">
        <h2 class="text-lg font-semibold text-white">1 · Consigue un token</h2>
        <p class="text-sm text-slate-400">{{ info.auth.note }}</p>
        <p class="text-sm text-slate-300">
          Se crea en <router-link to="/security" class="text-cyan-300 hover:underline">{{ info.auth.where }}</router-link>.
          Viaja en cada petición como <code class="font-mono text-slate-200">{{ info.auth.header }}</code>.
        </p>
      </div>

      <!-- Los clientes -->
      <div class="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-4">
        <h2 class="text-lg font-semibold text-white">2 · Pégalo en tu cliente</h2>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="client in info.clients"
            :key="client.id"
            @click="active = client.id"
            :class="[
              'rounded-lg border px-3 py-1.5 text-sm transition-colors',
              active === client.id
                ? 'border-cyan-500/40 bg-cyan-500/10 text-cyan-200'
                : 'border-white/10 text-slate-400 hover:text-slate-200'
            ]"
          >{{ client.name }}</button>
        </div>

        <div v-if="current" class="space-y-2">
          <p class="text-sm text-slate-400">{{ current.note }}</p>
          <div class="relative">
            <pre class="rounded-xl bg-black/50 border border-white/10 p-4 pr-24 text-xs text-slate-200 overflow-x-auto"><code>{{ current.snippet }}</code></pre>
            <button :class="[copyClass, 'absolute top-3 right-3']" @click="copy(current.snippet, current.id)">
              {{ copied === current.id ? '¡Copiado!' : 'Copiar' }}
            </button>
          </div>
          <p class="text-xs text-slate-500">
            Cambia <code class="font-mono">kbl_TU_TOKEN</code> por el token que acabas de crear. No lo compartas:
            quien lo tenga puede hacer lo que el token permita.
          </p>
        </div>
      </div>

      <!-- Qué puede hacer -->
      <div class="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-3">
        <h2 class="text-lg font-semibold text-white">3 · Qué va a poder hacer</h2>
        <p class="text-sm text-slate-400">
          {{ info.tools.total }} herramientas, agrupadas por lo que resuelven. Cada una exige su propio permiso:
          manda el token, no el agente.
        </p>
        <div class="flex flex-wrap gap-2 text-xs">
          <span
            v-for="(count, group) in info.tools.by_group"
            :key="group"
            class="inline-block rounded-full border border-white/15 px-3 py-1 text-slate-300"
          >{{ group }} · {{ count }}</span>
        </div>
        <ul class="text-sm text-slate-400 space-y-1">
          <li>· <strong class="text-slate-200">{{ info.tools.plan_first }}</strong> devuelven primero un plan y no tocan nada hasta que lo apruebas.</li>
          <li>· <strong class="text-slate-200">{{ info.tools.elevated }}</strong> exigen token crítico, y las irreversibles además tu aprobación en
            <router-link to="/security" class="text-cyan-300 hover:underline">Acceso → Solicitudes</router-link>.</li>
          <li>· Ninguna te va a mostrar el valor de un secreto.</li>
        </ul>
      </div>

      <!-- La API -->
      <div class="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-3">
        <h2 class="text-lg font-semibold text-white">La API, por si la llamas directo</h2>
        <p class="text-sm text-slate-400">
          El mismo token sirve para la API REST. La documentación se genera de la API que está corriendo
          ahora mismo, así que siempre coincide con esta versión.
        </p>
        <div class="flex flex-wrap gap-3 text-sm">
          <a v-for="doc in docLinks" :key="doc.label" :href="doc.url" target="_blank" rel="noopener"
             class="rounded-lg border border-white/15 px-3 py-1.5 text-slate-200 hover:border-cyan-500/40 hover:text-cyan-200 transition-colors">
            {{ doc.label }}
          </a>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'

import api from '@/services/api'

const copyClass =
  'rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-500/20 transition-colors'

const info = ref(null)
const loading = ref(true)
const error = ref('')
const active = ref('claude-code')
const copied = ref('')

const current = computed(() => info.value?.clients.find((client) => client.id === active.value))

const docLinks = computed(() => {
  const docs = info.value?.docs || {}
  return [
    { label: 'Swagger UI', url: docs.api },
    { label: 'ReDoc', url: docs.api_alternative },
    { label: 'openapi.json', url: docs.openapi },
  ].filter((doc) => doc.url)
})

const reachTitle = computed(() => ({
  internet: 'Alcanzable desde internet',
  vpn: 'Solo por la VPN',
  unknown: 'Alcance sin confirmar',
}[info.value?.reach] || 'Alcance sin confirmar'))

const reachClass = computed(() => ({
  internet: 'border-emerald-500/30 text-emerald-300',
  vpn: 'border-amber-500/30 text-amber-200',
  unknown: 'border-white/15 text-slate-300',
}[info.value?.reach] || 'border-white/15 text-slate-300'))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await api.get('/mcp/connection')
    info.value = data
    active.value = data.clients?.[0]?.id || 'claude-code'
  } catch (err) {
    error.value = err.response?.data?.detail || 'No se pudo leer la configuración de conexión.'
  } finally {
    loading.value = false
  }
}

async function copy(text, key) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
    copied.value = key
    setTimeout(() => { if (copied.value === key) copied.value = '' }, 2000)
  } catch {
    error.value = 'El navegador no dejó copiar: selecciona el texto a mano.'
  }
}

onMounted(load)
</script>
