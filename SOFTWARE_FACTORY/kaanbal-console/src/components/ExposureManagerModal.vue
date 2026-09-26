<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="show && app"
        class="fixed inset-0 z-[60] flex items-center justify-center p-4"
      >
        <div class="absolute inset-0 bg-black/75 backdrop-blur-sm" @click="emitClose" />

        <div
          class="relative bg-gradient-to-b from-slate-800 to-slate-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-5xl max-h-[90vh] overflow-hidden flex flex-col"
        >
          <div class="h-1 bg-gradient-to-r from-cyan-500 via-blue-500 to-emerald-500" />

          <!-- Header -->
          <div class="px-6 py-4 border-b border-white/10 flex items-start justify-between gap-4 shrink-0">
            <div class="min-w-0">
              <h3 class="text-xl font-bold text-white truncate">
                {{ app.name }} — Exposure &amp; Environments
              </h3>
              <p class="text-sm text-slate-400 mt-0.5">
                Change mode per env at runtime. Ops console validates each step.
              </p>
            </div>
            <button
              type="button"
              class="p-2 hover:bg-white/10 rounded-lg transition-colors shrink-0"
              @click="emitClose"
            >
              <span class="text-2xl text-slate-400">×</span>
            </button>
          </div>

          <div class="flex-1 min-h-0 grid grid-cols-1 lg:grid-cols-5 overflow-hidden">
            <!-- Matrix -->
            <div class="lg:col-span-3 p-5 overflow-y-auto space-y-4 border-b lg:border-b-0 lg:border-r border-white/10">
              <!-- Dominio padre -->
              <div v-if="domains.length > 1" class="rounded-xl border border-cyan-500/25 bg-cyan-500/5 p-4">
                <div class="flex items-center justify-between gap-3 flex-wrap">
                  <div class="min-w-0">
                    <p class="text-xs font-semibold text-cyan-300 uppercase tracking-wide">Dominio padre</p>
                    <p class="text-[11px] text-slate-400 mt-1">
                      Mudar de dominio republica el DNS de todos los ambientes públicos y retira
                      el anterior solo cuando el nuevo ya responde.
                    </p>
                  </div>
                  <div class="flex items-center gap-2 shrink-0">
                    <select
                      v-model="draftDomainId"
                      class="bg-slate-900/80 border border-white/10 rounded-lg px-3 py-1.5 text-white text-sm"
                    >
                      <option v-for="d in domains" :key="d._id" :value="d._id">
                        {{ d.fqdn }}{{ d.is_default ? ' (default)' : '' }}
                      </option>
                    </select>
                    <button
                      type="button"
                      class="px-3 py-1.5 rounded-lg text-sm font-medium bg-cyan-500/20 border border-cyan-500/30 text-cyan-200 disabled:opacity-40 disabled:cursor-not-allowed"
                      :disabled="!domainChanged || busy"
                      @click="onSwitchDomain"
                    >
                      Mudar
                    </button>
                  </div>
                </div>
              </div>

              <div
                v-for="env in ALL_ENVS"
                :key="env"
                class="rounded-xl border overflow-hidden"
                :class="isActive(env) ? envBorder[env] : 'border-white/5 opacity-80'"
              >
                <div class="px-4 py-3 flex items-center justify-between gap-3" :class="envHeader[env]">
                  <div class="flex items-center gap-3 min-w-0">
                    <span class="text-xl">{{ envIcon[env] }}</span>
                    <div class="min-w-0">
                      <p class="font-bold text-white capitalize">{{ env }}</p>
                      <p class="text-[11px] text-slate-400 truncate">
                        {{ currentDns(env) || '—' }}
                      </p>
                    </div>
                  </div>
                  <div class="flex items-center gap-2 shrink-0">
                    <span
                      v-if="isActive(env) && inventoryStatus(env)"
                      class="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase"
                      :class="statusBadgeClass(inventoryStatus(env))"
                    >{{ inventoryStatus(env) }}</span>
                    <span
                      class="text-[10px] px-2 py-0.5 rounded-full font-bold uppercase"
                      :class="isActive(env) ? 'bg-emerald-500/20 text-emerald-300' : 'bg-slate-500/20 text-slate-400'"
                    >
                      {{ isActive(env) ? 'Active' : 'Off' }}
                    </span>
                  </div>
                </div>

                <div class="p-4 space-y-3 bg-black/20">
                  <!-- Inactive: enable -->
                  <template v-if="!isActive(env)">
                    <p class="text-xs text-slate-500">
                      Environment not registered. Enabling clones overlay from an existing env and applies exposure.
                    </p>
                    <div class="flex flex-wrap gap-1.5">
                      <button
                        v-for="mode in modesForApp"
                        :key="'en-' + env + mode.value"
                        type="button"
                        class="px-2 py-1 rounded text-[11px] border transition-all"
                        :class="draftEnable[env] === mode.value
                          ? 'bg-blue-600 border-blue-500 text-white'
                          : 'bg-slate-900/50 border-slate-700/50 text-slate-500 hover:border-slate-500'"
                        @click="draftEnable[env] = mode.value"
                      >
                        {{ mode.icon }} {{ mode.label }}
                      </button>
                    </div>
                    <button
                      type="button"
                      class="w-full py-2 rounded-lg text-xs font-medium bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border border-emerald-500/30 disabled:opacity-50"
                      :disabled="busy"
                      @click="onEnable(env)"
                    >
                      + Enable {{ env }}
                    </button>
                  </template>

                  <!-- Active: exposure + lifecycle -->
                  <template v-else>
                    <div>
                      <p class="text-[10px] uppercase tracking-wide text-slate-500 mb-1.5 font-bold">Exposure</p>
                      <div class="flex flex-wrap gap-1">
                        <button
                          v-for="mode in modesForApp"
                          :key="env + mode.value"
                          type="button"
                          class="px-2 py-1 rounded text-[11px] border transition-all flex-1 min-w-[4.5rem] text-center"
                          :class="draftModes[env] === mode.value
                            ? modeActiveClass(mode.value)
                            : 'bg-slate-900/50 border-slate-700/50 text-slate-500 hover:border-slate-500 hover:text-slate-300'"
                          :disabled="busy || (app.is_root_domain && env === 'prod' && mode.value !== 'public')"
                          @click="draftModes[env] = mode.value"
                        >
                          {{ mode.icon }} {{ mode.label }}
                        </button>
                      </div>
                      <p
                        v-if="draftModes[env] !== savedMode(env)"
                        class="text-[10px] text-amber-400 mt-1"
                      >
                        Pending change: {{ savedMode(env) }} → {{ draftModes[env] }}
                      </p>
                    </div>

                    <!-- Surfaces -->
                    <div v-if="surfaceEntries(env).length || canonicalHosts(env).public || canonicalHosts(env).ts" class="rounded-lg bg-black/30 border border-white/5 p-2.5 space-y-1">
                      <p class="text-[10px] uppercase text-slate-500 font-bold">Surfaces</p>
                      <div
                        v-if="canonicalHosts(env).public"
                        class="flex items-center justify-between gap-2 text-[11px]"
                      >
                        <span class="text-slate-500 shrink-0">Public host</span>
                        <code
                          class="truncate text-emerald-300 cursor-pointer hover:text-emerald-200"
                          :title="canonicalHosts(env).public"
                          @click="copy('https://' + canonicalHosts(env).public)"
                        >{{ canonicalHosts(env).public }}</code>
                      </div>
                      <div
                        v-if="canonicalHosts(env).ts"
                        class="flex items-center justify-between gap-2 text-[11px]"
                      >
                        <span class="text-slate-500 shrink-0">VPN host</span>
                        <code
                          class="truncate text-violet-300 cursor-pointer hover:text-violet-200"
                          :title="canonicalHosts(env).ts"
                          @click="copy('http://' + canonicalHosts(env).ts)"
                        >{{ canonicalHosts(env).ts }}</code>
                      </div>
                      <p
                        v-if="env === 'prod' && savedMode(env) === 'public'"
                        class="text-[10px] text-amber-400/90 pt-1"
                      >
                        Prod public = {{ canonicalHosts(env).public || 'app.domain' }} (sin prefijo prod-)
                      </p>
                      <div
                        v-for="s in surfaceEntries(env)"
                        :key="env + s.name"
                        class="flex items-center justify-between gap-2 text-[11px]"
                      >
                        <span class="text-slate-500 shrink-0">{{ s.label }}</span>
                        <code
                          class="truncate text-cyan-300 cursor-pointer hover:text-cyan-200"
                          :title="s.url || ''"
                          @click="copy(s.url)"
                        >{{ s.url || '—' }}</code>
                      </div>
                    </div>

                    <div class="flex flex-wrap gap-2">
                      <button
                        type="button"
                        class="px-3 py-1.5 rounded-lg text-[11px] bg-white/5 hover:bg-white/10 text-slate-300 border border-white/10 disabled:opacity-50"
                        :disabled="busy"
                        @click="onStart(env)"
                      >▶ Start</button>
                      <button
                        type="button"
                        class="px-3 py-1.5 rounded-lg text-[11px] bg-white/5 hover:bg-white/10 text-slate-300 border border-white/10 disabled:opacity-50"
                        :disabled="busy"
                        @click="onStop(env)"
                      >⏹ Stop</button>
                      <div class="flex items-center gap-1 ml-auto">
                        <input
                          v-model.number="draftReplicas[env]"
                          type="number"
                          min="0"
                          max="10"
                          class="w-14 px-2 py-1 rounded bg-slate-950 border border-white/10 text-xs text-white text-center"
                          :disabled="busy"
                        />
                        <button
                          type="button"
                          class="px-3 py-1.5 rounded-lg text-[11px] bg-blue-500/15 hover:bg-blue-500/25 text-blue-300 border border-blue-500/30 disabled:opacity-50"
                          :disabled="busy"
                          @click="onScale(env)"
                        >Scale</button>
                      </div>
                    </div>

                    <button
                      v-if="activeEnvs.length > 1"
                      type="button"
                      class="w-full py-1.5 rounded-lg text-[11px] text-rose-300/90 hover:bg-rose-500/10 border border-rose-500/20 disabled:opacity-50"
                      :disabled="busy"
                      @click="onRemove(env)"
                    >
                      Remove {{ env }} (stop + off)
                    </button>
                  </template>
                </div>
              </div>

              <div class="sticky bottom-0 pt-2 space-y-2 bg-gradient-to-t from-slate-900 via-slate-900/95 to-transparent">
                <button
                  type="button"
                  class="w-full py-2 rounded-xl text-xs font-medium bg-white/5 hover:bg-white/10 text-slate-300 border border-white/10 disabled:opacity-40"
                  :disabled="busy || validating"
                  @click="onRefreshStatus"
                >
                  {{ validating ? 'Validating…' : 'Refresh status' }}
                </button>
                <button
                  type="button"
                  class="w-full py-3 rounded-xl text-sm font-semibold bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed shadow-lg shadow-blue-900/40"
                  :disabled="busy || validating || !hasPendingExposure"
                  @click="onApplyExposure"
                >
                  {{ busy || validating
                    ? (validating ? 'Validating surfaces…' : 'Applying…')
                    : hasPendingExposure ? `Apply exposure changes (${pendingCount})` : 'No exposure changes' }}
                </button>
              </div>
            </div>

            <!-- Ops console -->
            <div class="lg:col-span-2 flex flex-col min-h-[240px] bg-[#0d1117]">
              <div class="px-4 py-2.5 border-b border-white/5 flex items-center justify-between shrink-0">
                <div class="flex items-center gap-2">
                  <span class="w-2.5 h-2.5 rounded-full bg-red-500/80" />
                  <span class="w-2.5 h-2.5 rounded-full bg-amber-400/80" />
                  <span class="w-2.5 h-2.5 rounded-full bg-emerald-500/80" />
                  <span class="ml-2 text-[11px] text-slate-400 font-mono">ops console</span>
                </div>
                <button
                  type="button"
                  class="text-[10px] text-slate-500 hover:text-slate-300"
                  @click="logs = []"
                >Clear</button>
              </div>
              <div ref="logEl" class="flex-1 overflow-y-auto p-3 font-mono text-[11px] space-y-1">
                <p v-if="!logs.length" class="text-slate-600">
                  Ready. Apply exposure or lifecycle actions to see validation here.
                </p>
                <div v-for="(line, i) in logs" :key="i" class="flex gap-2">
                  <span class="text-slate-600 shrink-0">{{ line.time }}</span>
                  <span :class="line.color">{{ line.message }}</span>
                </div>
              </div>
              <div class="px-3 py-2 border-t border-white/5 text-[10px] text-slate-500 shrink-0">
                {{ validating ? 'Validating…' : busy ? 'Running…' : 'Idle' }}
                <span v-if="lastStatus" class="ml-2" :class="lastStatus.ok ? 'text-emerald-400' : 'text-amber-400'">
                  · last: {{ lastStatus.label || (lastStatus.ok ? 'OK' : 'PENDING') }}
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, nextTick, reactive, ref, watch } from 'vue'
import {
  enableAppEnv,
  fetchAppExposureStatus,
  patchAppExposure,
  removeAppEnv,
  scaleAppEnv,
  startAppEnv,
  stopAppEnv,
} from '../services/appsApi'
import axios from 'axios'

const props = defineProps({
  show: { type: Boolean, default: false },
  app: { type: Object, default: null },
})

const emit = defineEmits(['close', 'updated', 'toast'])

const ALL_ENVS = ['dev', 'staging', 'prod']
const ALL_MODES = {
  public: { value: 'public', label: 'Public', icon: '🌐' },
  tailscale: { value: 'tailscale', label: 'VPN', icon: '🔒' },
  lan: { value: 'lan', label: 'LAN', icon: '📡' },
  internal: { value: 'internal', label: 'Cluster', icon: '🏠' },
  off: { value: 'off', label: 'Off', icon: '⏹' },
  both: { value: 'both', label: 'Mixed', icon: '🔀' },
}

const CATEGORY_MODES = {
  database: ['internal', 'tailscale', 'lan', 'off'],
  monitoring: ['tailscale', 'lan', 'off'],
  workflow: ['public', 'tailscale'],
  frontend: ['public', 'tailscale', 'lan', 'off'],
  backend: ['internal', 'tailscale', 'public', 'lan', 'off'],
  iot: ['internal', 'tailscale', 'public', 'lan', 'off'],
}

const envIcon = { dev: '🧪', staging: '🚧', prod: '🚀' }
const envHeader = {
  dev: 'bg-sky-500/10 border-b border-sky-500/20',
  staging: 'bg-amber-500/10 border-b border-amber-500/20',
  prod: 'bg-emerald-500/10 border-b border-emerald-500/20',
}
const envBorder = {
  dev: 'border-sky-500/30',
  staging: 'border-amber-500/30',
  prod: 'border-emerald-500/30',
}

const busy = ref(false)
const validating = ref(false)
const logs = ref([])
const logEl = ref(null)
const lastStatus = ref(null)
const draftModes = reactive({})
const draftEnable = reactive({ dev: 'tailscale', staging: 'tailscale', prod: 'public' })
const draftReplicas = reactive({ dev: 1, staging: 1, prod: 1 })

const modesForApp = computed(() => {
  const cat = props.app?.category || ''
  const allowed = CATEGORY_MODES[cat] || ['internal', 'public', 'tailscale', 'lan', 'off', 'both']
  return allowed.map((m) => ALL_MODES[m]).filter(Boolean)
})

const activeEnvs = computed(() => props.app?.environments || [])

const isActive = (env) => activeEnvs.value.includes(env)

const savedMode = (env) => {
  const pe = props.app?.connection_info?.per_env_exposure?.[env]
  if (pe?.mode) return pe.mode
  if (pe?.type) return pe.type
  if (props.app?.exposure?.per_env?.[env]) return props.app.exposure.per_env[env]
  return props.app?.exposure?.type || 'internal'
}

const hasPendingExposure = computed(() =>
  ALL_ENVS.some((env) => isActive(env) && draftModes[env] && draftModes[env] !== savedMode(env))
)

const pendingCount = computed(() =>
  ALL_ENVS.filter((env) => isActive(env) && draftModes[env] !== savedMode(env)).length
)

function inventoryStatus(env) {
  const row = props.app?.connection_inventory?.by_env?.[env]
  return row?.status || props.app?.connection_info?.per_env_exposure?.[env]?.status || ''
}

function statusBadgeClass(st) {
  if (st === 'validated') return 'bg-emerald-500/20 text-emerald-300'
  if (st === 'pending') return 'bg-amber-500/20 text-amber-300'
  if (st === 'drift') return 'bg-rose-500/20 text-rose-300'
  if (st === 'failed') return 'bg-rose-500/20 text-rose-300'
  return 'bg-slate-500/20 text-slate-400'
}

function canonicalHosts(env) {
  const pe = props.app?.connection_info?.per_env_exposure?.[env] || {}
  const row = props.app?.connection_inventory?.by_env?.[env]
  const desired = row?.desired || {}
  return {
    public: pe.canonical_public_host || desired.public_hostname || '',
    ts: pe.canonical_ts_host || desired.ts_hostname || '',
  }
}

function modeActiveClass(mode) {
  if (mode === 'public') return 'bg-emerald-600 border-emerald-500 text-white'
  if (mode === 'tailscale') return 'bg-violet-600 border-violet-500 text-white'
  if (mode === 'both') return 'bg-indigo-600 border-indigo-500 text-white'
  if (mode === 'lan') return 'bg-sky-600 border-sky-500 text-white'
  if (mode === 'off') return 'bg-rose-900 border-rose-700 text-white'
  return 'bg-slate-600 border-slate-500 text-white'
}

function currentDns(env) {
  const hosts = canonicalHosts(env)
  const mode = savedMode(env)
  if (mode === 'public' || mode === 'both') {
    if (hosts.public) return hosts.public
  }
  if (mode === 'tailscale' || mode === 'both') {
    if (hosts.ts) return hosts.ts
  }
  const pe = props.app?.connection_info?.per_env_exposure?.[env]
  if (pe?.public_url) return pe.public_url.replace(/^https?:\/\//, '')
  if (pe?.tailscale_url) return pe.tailscale_url.replace(/^https?:\/\//, '')
  if (pe?.editor_url) return pe.editor_url.replace(/^https?:\/\//, '')
  if (pe?.cluster_url) return pe.cluster_url.replace(/^https?:\/\//, '')
  return ''
}

function surfaceEntries(env) {
  const pe = props.app?.connection_info?.per_env_exposure?.[env]
  const surfaces = pe?.surfaces || {}
  return Object.entries(surfaces).map(([name, meta]) => ({
    name,
    label: meta.label || name,
    url: meta.url,
  })).filter((s) => s.url)
}

function addLog(message, color = 'text-slate-300') {
  const time = new Date().toLocaleTimeString()
  logs.value.push({ time, message, color })
  nextTick(() => {
    if (logEl.value) logEl.value.scrollTop = logEl.value.scrollHeight
  })
}

function logPublishers(publishers) {
  if (!publishers) return
  // merge_results shape: { ok, publishers: { name: {ok,status,detail} }, urls }
  const map = publishers.publishers
  if (map && typeof map === 'object' && !Array.isArray(map)) {
    for (const [name, r] of Object.entries(map)) {
      const ok = r.ok !== false && r.status !== 'failed'
      addLog(
        `[${name}] ${r.status || (ok ? 'ok' : 'failed')}${r.detail ? ' — ' + r.detail : ''}`,
        ok ? 'text-emerald-400' : 'text-rose-400'
      )
    }
    addLog(
      publishers.ok === false ? 'summary: FAILED' : 'summary: OK',
      publishers.ok === false ? 'text-rose-400' : 'text-emerald-400'
    )
    return
  }
  const results = publishers.results || publishers.items || []
  if (Array.isArray(results) && results.length) {
    for (const r of results) {
      const ok = r.ok !== false && r.status !== 'failed'
      addLog(
        `[${r.name || 'step'}] ${r.status || (ok ? 'ok' : 'failed')}${r.detail ? ' — ' + r.detail : ''}`,
        ok ? 'text-emerald-400' : 'text-rose-400'
      )
    }
    return
  }
  addLog(`publishers: ${JSON.stringify(publishers).slice(0, 280)}`, 'text-slate-400')
}

function syncDraftFromApp() {
  for (const env of ALL_ENVS) {
    draftModes[env] = savedMode(env)
    const specs = props.app?.specs_by_env?.[env]?.replicas
    draftReplicas[env] = typeof specs === 'number' ? specs : (props.app?.specs?.replicas || 1)
  }
}

// ── Multi-dominio ─────────────────────────────────────────────────────────
const domains = ref([])
const draftDomainId = ref(null)

const defaultDomainId = computed(() => domains.value.find(d => d.is_default)?._id || null)

// Una app sin domain_id vive en el default, así que ese es el punto de partida
// contra el cual se compara la mudanza.
const currentDomainId = computed(() => props.app?.domain_id || defaultDomainId.value)

const domainChanged = computed(
  () => !!draftDomainId.value && draftDomainId.value !== currentDomainId.value
)

async function loadDomains() {
  try {
    const { data } = await axios.get('/api/v1/domains')
    domains.value = data || []
  } catch (e) {
    domains.value = []
  }
  draftDomainId.value = currentDomainId.value
}

// La mudanza corre en segundo plano en la API (POST /apps/{name}/domain): puede
// tardar más de los 100 s que Cloudflare espera una respuesta síncrona.
async function onSwitchDomain() {
  const target = domains.value.find(d => d._id === draftDomainId.value)
  busy.value = true
  addLog(`→ Mudar a ${target?.fqdn || draftDomainId.value}`, 'text-blue-400')
  try {
    await axios.post(`/api/v1/apps/${props.app.name}/domain`, { domain_id: draftDomainId.value })
    addLog('✓ Mudanza iniciada. La tarjeta de la app muestra su progreso y el resultado.', 'text-emerald-400')
    emit('toast', { type: 'info', title: 'Mudanza iniciada', message: `${props.app.name} → ${target?.fqdn}` })
    patchLocalApp({ domain_move: { state: 'running', to: target?.fqdn } })
  } catch (e) {
    const detail = e.response?.data?.detail || e.message || 'unknown error'
    addLog(`✗ ${detail}`, 'text-rose-400 font-bold')
    emit('toast', { type: 'error', title: 'No se pudo mudar', message: String(detail).slice(0, 160) })
  } finally {
    busy.value = false
  }
}

watch(
  () => [props.show, props.app?.name, props.app?.exposure, props.app?.environments],
  ([show]) => {
    if (show && props.app) {
      loadDomains()
      syncDraftFromApp()
      if (!logs.value.length) {
        addLog(`Opened manager for ${props.app.name}`, 'text-blue-400')
        addLog(`Active envs: ${(props.app.environments || []).join(', ') || 'none'}`, 'text-slate-400')
      }
    }
  },
  { immediate: true, deep: true }
)

function emitClose() {
  if (busy.value) return
  validating.value = false
  emit('close')
}

function copy(text) {
  if (!text) return
  navigator.clipboard?.writeText(text)
  emit('toast', { type: 'info', title: 'Copied', message: text })
}

function patchLocalApp(partial) {
  emit('updated', { name: props.app.name, ...partial })
}

function applyInventoryFromResult(data) {
  if (!data) return
  patchLocalApp({
    exposure: data.exposure || props.app.exposure,
    connection_info: {
      ...(props.app.connection_info || {}),
      per_env_exposure: data.connection_info || props.app.connection_info?.per_env_exposure || {},
    },
    connection_inventory: data.connection_inventory || props.app.connection_inventory,
  })
}

function logInventoryHints(data) {
  if (!data) return
  const by = data.connection_inventory?.by_env || {}
  for (const [env, row] of Object.entries(by)) {
    const d = row?.desired || {}
    if (d.public_hostname) {
      addLog(`[${env}] canonical public: ${d.public_hostname}`, 'text-slate-400')
    }
    if (d.ts_hostname && (d.mode === 'tailscale' || d.mode === 'both')) {
      addLog(`[${env}] canonical VPN: ${d.ts_hostname}`, 'text-slate-400')
    }
    if (row?.status) {
      addLog(`[${env}] inventory: ${row.status}${row.last_error ? ' — ' + row.last_error : ''}`,
        row.status === 'validated' ? 'text-emerald-400' : 'text-amber-400')
    }
    const http = row?.observed?.http
    if (http?.status_code != null) {
      addLog(`[${env}] public_http=${http.status_code} ${http.url || ''}`, 'text-slate-400')
    }
  }
  if (data.pending?.length) {
    addLog(`pending envs: ${data.pending.join(', ')}`, 'text-amber-400')
  }
  if (data.drift?.length) {
    addLog(`drift envs: ${data.drift.join(', ')}`, 'text-rose-400')
  }
}

async function pollUntilValidated(maxRounds = 8) {
  validating.value = true
  try {
    for (let i = 0; i < maxRounds; i++) {
      addLog(`↻ refresh status (${i + 1}/${maxRounds})…`, 'text-blue-400')
      const data = await fetchAppExposureStatus(props.app.name)
      applyInventoryFromResult(data)
      logInventoryHints(data)
      if (data?.validated) {
        lastStatus.value = { ok: true, label: 'VALIDATED' }
        emit('toast', { type: 'success', title: 'Validated', message: 'Surfaces ready' })
        return data
      }
      await new Promise((r) => setTimeout(r, 4000))
    }
    lastStatus.value = { ok: false, label: 'PENDING' }
    emit('toast', {
      type: 'warning',
      title: 'Still validating',
      message: 'Argo/CF/cert can take 1–2 min — usa Refresh status',
    })
  } catch (e) {
    const detail = e.response?.data?.detail || e.message || 'status failed'
    addLog(`✗ refresh status: ${detail}`, 'text-rose-400')
  } finally {
    validating.value = false
  }
}

async function onRefreshStatus() {
  if (!props.app?.name) return
  validating.value = true
  addLog('→ GET exposure/status', 'text-blue-400')
  try {
    const data = await fetchAppExposureStatus(props.app.name)
    applyInventoryFromResult(data)
    logInventoryHints(data)
    lastStatus.value = {
      ok: !!data.validated,
      label: data.validated ? 'VALIDATED' : (data.pending?.length ? 'PENDING' : 'CHECK'),
    }
    emit('toast', {
      type: data.validated ? 'success' : 'info',
      title: data.validated ? 'Validated' : 'Status refreshed',
      message: data.validated ? 'All surfaces ready' : `pending: ${(data.pending || []).join(', ') || 'none'}`,
    })
  } catch (e) {
    const detail = e.response?.data?.detail || e.message || 'unknown'
    addLog(`✗ status: ${detail}`, 'text-rose-400')
    emit('toast', { type: 'error', title: 'Status failed', message: String(detail).slice(0, 160) })
  } finally {
    validating.value = false
  }
}

async function runOp(label, fn) {
  busy.value = true
  lastStatus.value = null
  addLog(`→ ${label}`, 'text-blue-400')
  try {
    const data = await fn()
    addLog(`✓ ${label}`, 'text-emerald-400')
    logPublishers(data?.publishers)
    logInventoryHints(data)
    if (data?.validated === false) {
      addLog('⚠ Applied — waiting Argo/DNS/HTTP (console will keep validating)', 'text-amber-400')
      lastStatus.value = { ok: false, label: 'PENDING' }
      emit('toast', { type: 'warning', title: 'Validating…', message: 'Espera proyección + probe' })
    } else {
      lastStatus.value = { ok: true, label: 'VALIDATED' }
      emit('toast', { type: 'success', title: 'Validated', message: label })
    }
    if (data?.environments) {
      addLog(`environments → [${data.environments.join(', ')}]`, 'text-slate-400')
    }
    if (data?.exposure?.per_env) {
      addLog(`exposure → ${JSON.stringify(data.exposure.per_env)}`, 'text-slate-400')
    }
    return data
  } catch (e) {
    const detail = e.response?.data?.detail || e.message || 'unknown error'
    addLog(`✗ ${label}: ${detail}`, 'text-rose-400 font-bold')
    lastStatus.value = { ok: false, label: 'FAILED' }
    emit('toast', { type: 'error', title: 'Failed', message: String(detail).slice(0, 160) })
    throw e
  } finally {
    busy.value = false
  }
}

async function onApplyExposure() {
  const per_env = {}
  for (const env of ALL_ENVS) {
    if (isActive(env) && draftModes[env] !== savedMode(env)) {
      per_env[env] = draftModes[env]
    }
  }
  if (!Object.keys(per_env).length) return

  const data = await runOp(
    `PATCH exposure ${JSON.stringify(per_env)}`,
    () => patchAppExposure(props.app.name, { per_env })
  )
  applyInventoryFromResult(data)
  syncDraftFromApp()
  if (data && data.validated === false) {
    await pollUntilValidated()
    syncDraftFromApp()
  }
}

async function onEnable(env) {
  const mode = draftEnable[env] || 'tailscale'
  const data = await runOp(
    `Enable ${env} as ${mode}`,
    () => enableAppEnv(props.app.name, env, mode)
  )
  patchLocalApp({
    environments: data.environments,
    exposure: data.exposure,
    connection_info: {
      ...(props.app.connection_info || {}),
      per_env_exposure: data.connection_info || {},
    },
  })
  syncDraftFromApp()
}

async function onRemove(env) {
  if (!confirm(`Remove environment "${env}"? It will stop (replicas=0) and set exposure off.`)) return
  const data = await runOp(
    `Remove ${env}`,
    () => removeAppEnv(props.app.name, env)
  )
  patchLocalApp({
    environments: data.environments,
    exposure: data.exposure,
    connection_info: {
      ...(props.app.connection_info || {}),
      per_env_exposure: data.connection_info || {},
    },
  })
  syncDraftFromApp()
}

async function onStop(env) {
  const data = await runOp(`Stop ${env}`, () => stopAppEnv(props.app.name, env))
  draftReplicas[env] = 0
  patchLocalApp({ status: data.status })
}

async function onStart(env) {
  const data = await runOp(`Start ${env}`, () => startAppEnv(props.app.name, env, draftReplicas[env] || 1))
  draftReplicas[env] = data.replicas || 1
  patchLocalApp({ status: data.status })
}

async function onScale(env) {
  const n = Number(draftReplicas[env])
  if (!Number.isInteger(n) || n < 0) {
    addLog('replicas must be an integer ≥ 0', 'text-amber-400')
    return
  }
  const data = await runOp(
    `Scale ${env} → ${n}`,
    () => scaleAppEnv(props.app.name, env, n)
  )
  patchLocalApp({ status: data.status })
}
</script>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
