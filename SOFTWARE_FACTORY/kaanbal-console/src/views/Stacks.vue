<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h1 class="text-3xl font-bold bg-gradient-to-r from-purple-400 to-pink-500 bg-clip-text text-transparent">Stacks</h1>
        <p class="mt-2 text-slate-400">Base de datos, API y sitio en una sola operación, ya conectados entre sí.</p>
      </div>
      <button @click="loadAll" :disabled="loading" class="glass-button text-sm flex items-center gap-2">
        <span :class="{ 'animate-spin': loading }">🔄</span> Actualizar
      </button>
    </div>

    <!-- Lanzamiento en curso o último resultado -->
    <div
      v-if="run"
      class="glass-panel p-5 rounded-2xl"
      :class="run.state === 'failed' ? 'border-red-500/40' : run.state === 'succeeded' ? 'border-emerald-500/40' : 'border-sky-500/40'"
    >
      <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
        <div class="min-w-0">
          <p class="text-xs uppercase tracking-wider text-slate-500">{{ runHeadline }}</p>
          <h2 class="text-lg font-bold text-white truncate">
            {{ run.stack_name }} · <span class="font-mono text-slate-300">{{ run.base }}</span>
          </h2>
          <p class="text-xs text-slate-500 mt-0.5">
            En {{ run.domain }}<span v-if="run.homepage"> · el sitio ocupa la raíz del dominio</span>
          </p>
        </div>
        <router-link v-if="run.state === 'succeeded'" to="/apps" class="glass-button text-sm">Ver en Applications →</router-link>
      </div>

      <div class="grid gap-2 md:grid-cols-3">
        <div
          v-for="component in run.components"
          :key="component.name"
          class="rounded-xl border p-3 min-w-0"
          :class="componentClass(component.state)"
        >
          <div class="flex items-center gap-2 mb-1">
            <span>{{ roleIcon(component.role) }}</span>
            <span class="font-mono text-sm text-slate-200 truncate">{{ component.name }}</span>
            <span class="ml-auto text-xs shrink-0">{{ stateLabel(component.state) }}</span>
          </div>
          <a v-if="component.url && component.state === 'ready'" :href="component.url" target="_blank" rel="noopener"
             class="text-xs text-cyan-300 hover:underline break-all">{{ component.url }}</a>
          <p v-else-if="component.error" class="text-xs text-red-300 break-words">{{ component.error }}</p>
          <p v-else class="text-xs text-slate-500">{{ component.template }}</p>
        </div>
      </div>

      <p v-if="run.error" class="mt-3 text-sm text-red-300">
        {{ run.error }}
        <span class="text-slate-500">— lo ya creado quedó en Applications; puedes reintentar o borrarlo desde ahí.</span>
      </p>
    </div>

    <!-- Catálogo -->
    <div v-if="loading && stacks.length === 0" class="text-center py-12 text-slate-400">Cargando stacks…</div>

    <div v-else class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div
        v-for="stack in stacks"
        :key="stack.id"
        class="glass-panel p-0 rounded-2xl overflow-hidden hover:border-purple-500/50 transition-all duration-300"
      >
        <div class="p-6 border-b border-white/10" :style="`background: linear-gradient(135deg, ${stack.color || '#8b5cf6'}15, transparent)`">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="flex items-center gap-2 mb-2">
                <span class="text-2xl">{{ stack.icon || '📦' }}</span>
                <h3 class="text-xl font-bold text-white">{{ stack.name }}</h3>
              </div>
              <p class="text-slate-400 text-sm">{{ stack.description }}</p>
            </div>
            <span v-if="stack.popular" class="text-xs bg-yellow-500/20 text-yellow-400 px-2 py-1 rounded shrink-0">⭐ Popular</span>
          </div>
        </div>

        <div class="p-6 space-y-4">
          <div class="space-y-2">
            <div
              v-for="component in orderedComponents(stack)"
              :key="component.role"
              class="flex items-center gap-3 text-sm bg-white/[0.03] border border-white/5 rounded-lg px-3 py-2"
            >
              <span>{{ roleIcon(component.role) }}</span>
              <span class="text-slate-200">{{ component.template_name || component.template }}</span>
              <span class="ml-auto text-[11px] px-2 py-0.5 rounded" :class="exposureClass(component.exposure)">
                {{ exposureLabel(component.exposure) }}
              </span>
            </div>
          </div>
          <p class="text-xs text-slate-500">
            Se despliegan en ese orden: la API se vincula a la base y el sitio se construye con la URL de la API.
          </p>
          <button @click="openLaunch(stack)" :disabled="launching" class="glass-button w-full">Lanzar stack</button>
        </div>
      </div>
    </div>

    <!-- Modal de lanzamiento -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="modal.show" class="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" @click.self="modal.show = false">
          <div class="w-full max-w-lg bg-slate-900 border border-white/10 rounded-2xl shadow-2xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-white/10">
              <h3 class="text-xl font-bold text-white">{{ modal.stack?.icon }} {{ modal.stack?.name }}</h3>
              <p class="text-sm text-slate-400 mt-1">Tres apps, un grupo, un dominio.</p>
            </div>

            <div class="p-6 space-y-5">
              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Nombre base</label>
                <input
                  v-model="form.name"
                  placeholder="north-star-bay"
                  class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm"
                />
                <p class="text-[11px] text-slate-500 mt-1">De aquí salen los nombres de las tres apps y el del grupo.</p>
              </div>

              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Dominio</label>
                <select v-model="form.domain_id" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm">
                  <option v-for="domain in domains" :key="domain._id" :value="domain._id">
                    {{ domain.fqdn }}{{ domain.is_default ? ' (default)' : '' }}
                  </option>
                </select>
              </div>

              <label class="flex items-start gap-2 text-sm text-slate-300 cursor-pointer">
                <input type="checkbox" v-model="form.homepage" class="mt-0.5" />
                <span>
                  El sitio ocupa la raíz del dominio (homepage)
                  <span class="block text-[11px] text-slate-500">
                    Prod queda en <code>https://{{ selectedDomain?.fqdn }}</code> en vez de un subdominio.
                  </span>
                </span>
              </label>

              <label class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                <input type="checkbox" v-model="form.withDev" />
                <span>Crear también el ambiente <code>dev</code></span>
              </label>

              <!-- Vista previa: lo que va a existir cuando termine -->
              <div class="rounded-xl border border-white/5 bg-black/20 p-3">
                <p class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">Se van a crear</p>
                <div v-for="item in preview" :key="item.name" class="flex items-center gap-2 text-xs py-1 min-w-0">
                  <span>{{ roleIcon(item.role) }}</span>
                  <span class="font-mono text-slate-200 truncate">{{ item.name }}</span>
                  <span class="ml-auto text-slate-500 truncate">{{ item.url || 'privada · solo clúster' }}</span>
                </div>
              </div>

              <p v-if="modal.error" class="text-sm text-red-300">{{ modal.error }}</p>
            </div>

            <div class="p-6 border-t border-white/10 flex justify-end gap-3">
              <button @click="modal.show = false" class="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancelar</button>
              <button @click="launch" :disabled="!canLaunch" class="glass-button disabled:opacity-50">
                {{ launching ? 'Lanzando…' : 'Lanzar' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Toast -->
    <Teleport to="body">
      <Transition name="toast">
        <div v-if="toast.show" :class="['fixed bottom-6 right-6 z-[100] px-6 py-4 rounded-xl shadow-2xl backdrop-blur-xl border', toast.type === 'success' ? 'bg-emerald-900/90 border-emerald-500/50 text-emerald-100' : 'bg-red-900/90 border-red-500/50 text-red-100']">
          <div class="flex items-center gap-3">
            <span class="text-2xl">{{ toast.type === 'success' ? '✅' : '❌' }}</span>
            <p class="font-medium">{{ toast.message }}</p>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import axios from 'axios'
import { publicHost } from '@/services/sites'

const ROLE_ICONS = { database: '🗄️', backend: '⚡', frontend: '🖥️' }
const ROLE_ORDER = ['database', 'backend', 'frontend']
const RUN_POLL_MS = 4000

const loading = ref(false)
const launching = ref(false)
const stacks = ref([])
const domains = ref([])
const run = ref(null)

const modal = reactive({ show: false, stack: null, error: '' })
const form = reactive({ name: '', domain_id: '', homepage: false, withDev: false })
const toast = reactive({ show: false, message: '', type: 'success' })

const showToast = (message, type = 'success') => {
  Object.assign(toast, { show: true, message, type })
  setTimeout(() => { toast.show = false }, 5000)
}

const roleIcon = (role) => ROLE_ICONS[role] || '📦'
const orderedComponents = (stack) => [...(stack.components || [])]
  .sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role))

const exposureLabel = (mode) => (mode === 'public' ? '🌐 pública' : mode === 'tailscale' ? '🔒 VPN' : '🏠 solo clúster')
const exposureClass = (mode) => (mode === 'public'
  ? 'bg-emerald-500/15 text-emerald-300'
  : mode === 'tailscale' ? 'bg-blue-500/15 text-blue-300' : 'bg-slate-500/15 text-slate-400')

const stateLabel = (state) => ({ pending: 'en cola', deploying: 'desplegando…', ready: 'lista', failed: 'falló' }[state] || state)
const componentClass = (state) => ({
  ready: 'border-emerald-500/30 bg-emerald-500/5',
  deploying: 'border-sky-500/30 bg-sky-500/5 animate-pulse',
  failed: 'border-red-500/30 bg-red-500/5',
}[state] || 'border-white/5 bg-white/[0.02]')

const runHeadline = computed(() => ({
  running: '⏳ Lanzando ahora',
  succeeded: '✅ Stack listo',
  failed: '❌ El stack se detuvo',
  interrupted: '⚠️ Lanzamiento interrumpido',
}[run.value?.state] || 'Último lanzamiento'))

const selectedDomain = computed(() => domains.value.find(d => d._id === form.domain_id) || null)

// Los nombres y las URLs se calculan con la misma regla que la API, para que la
// vista previa diga exactamente lo que va a existir.
const preview = computed(() => {
  const stack = modal.stack
  const fqdn = selectedDomain.value?.fqdn || 'dominio'
  const base = (form.name || '').trim().toLowerCase().replace(/[^a-z0-9-]/g, '').replace(/-+/g, '-').replace(/^-|-$/g, '')
    || (fqdn.split('.')[0] || 'sitio')
  return orderedComponents(stack || {}).map(component => {
    const name = `${base}${component.suffix || ''}`
    const isRoot = !!(form.homepage && component.role === 'frontend' && component.can_be_homepage)
    const isPublic = component.exposure === 'public' || isRoot
    return {
      role: component.role,
      name,
      url: isPublic ? `https://${publicHost(name, 'prod', fqdn, { isRoot })}` : null,
    }
  })
})

const canLaunch = computed(() => !launching.value && !!form.domain_id && preview.value.length > 0)

const loadAll = async () => {
  loading.value = true
  try {
    const [catalog, domainList, runs] = await Promise.all([
      axios.get('/api/v1/stacks/catalog'),
      axios.get('/api/v1/domains'),
      axios.get('/api/v1/stacks/runs?limit=1'),
    ])
    stacks.value = catalog.data.stacks || []
    domains.value = domainList.data || []
    run.value = (runs.data.runs || [])[0] || null
    if (run.value?.state === 'running') pollRun(run.value._id)
  } catch (e) {
    showToast(e.response?.data?.detail || 'No se pudo cargar el catálogo de stacks', 'error')
  } finally {
    loading.value = false
  }
}

const openLaunch = (stack) => {
  modal.stack = stack
  modal.error = ''
  modal.show = true
  form.name = ''
  form.homepage = false
  form.withDev = false
  if (!form.domain_id) form.domain_id = (domains.value.find(d => d.is_default) || domains.value[0])?._id || ''
}

let runTimer = null
const stopPoll = () => { clearInterval(runTimer); runTimer = null }

const pollRun = (runId) => {
  stopPoll()
  runTimer = setInterval(async () => {
    try {
      const { data } = await axios.get(`/api/v1/stacks/runs/${runId}`)
      run.value = data
      if (data.state === 'running') return
      stopPoll()
      if (data.state === 'succeeded') {
        showToast(`${data.stack_name} listo en ${data.domain}`)
      } else {
        showToast(data.error || 'El stack no terminó', 'error')
      }
    } catch (e) {
      // Un error de red puntual no cancela el lanzamiento, que corre en el servidor.
    }
  }, RUN_POLL_MS)
}

const launch = async () => {
  launching.value = true
  modal.error = ''
  try {
    const { data } = await axios.post('/api/v1/stacks', {
      stack_id: modal.stack.id,
      name: form.name,
      domain_id: form.domain_id,
      environments: form.withDev ? ['dev', 'prod'] : ['prod'],
      homepage: form.homepage,
    })
    run.value = data
    modal.show = false
    showToast('Lanzando el stack: base, API y sitio, en ese orden')
    pollRun(data.run_id)
  } catch (e) {
    modal.error = e.response?.data?.detail || 'No se pudo lanzar el stack'
  } finally {
    launching.value = false
  }
}

watch(() => modal.show, (open) => { if (!open) modal.error = '' })

onMounted(loadAll)
onUnmounted(stopPoll)
</script>

<style scoped>
.modal-enter-active, .modal-leave-active { transition: all 0.3s ease; }
.modal-enter-from, .modal-leave-to { opacity: 0; }

.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(100%); }

.glass-panel {
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.glass-button {
  padding: 0.75rem 1.5rem;
  border-radius: 0.5rem;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid rgba(59, 130, 246, 0.3);
  color: white;
  font-weight: 500;
  transition: all 0.2s;
}

.glass-button:hover { background: rgba(59, 130, 246, 0.3); }
</style>
