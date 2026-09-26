<template>
  <div class="space-y-6">
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">Domains</h1>
        <p class="mt-2 text-slate-400">Los dominios bajo los que esta célula puede publicar apps.</p>
      </div>
      <div class="flex items-center gap-2">
        <button @click="loadDomains" :disabled="loading" class="glass-button text-sm flex items-center gap-2">
          <span :class="{'animate-spin': loading}">🔄</span>
          Refresh
        </button>
        <button @click="openAddModal" class="glass-button glass-button-primary text-sm">
          + Agregar dominio
        </button>
      </div>
    </div>

    <!-- Info Banner -->
    <div class="glass-panel p-4 border-cyan-500/30 bg-cyan-500/5">
      <div class="flex items-start gap-3">
        <span class="text-2xl">🌐</span>
        <div>
          <h3 class="font-semibold text-cyan-300">Cómo funciona el multi-dominio</h3>
          <p class="text-sm text-slate-400 mt-1">
            La instalación registra su primer dominio automáticamente. Al agregar otro, Kaanbal valida
            la zona en Cloudflare, le añade reglas al túnel existente y crea el DNS wildcard.
            Al lanzar una app en modo <span class="text-emerald-400">público</span> eliges cuál de estos
            dominios usar, y puedes mudarla después desde su exposición.
          </p>
        </div>
      </div>
    </div>

    <!-- Loading -->
    <div v-if="loading && domains.length === 0" class="text-center py-12 text-slate-400">
      Cargando dominios...
    </div>

    <!-- Domain list -->
    <div class="space-y-4">
      <div
        v-for="domain in domains"
        :key="domain._id"
        class="glass-panel p-6 rounded-xl"
      >
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div class="min-w-0">
            <div class="flex items-center gap-3 flex-wrap">
              <h3 class="text-xl font-bold text-white break-all">{{ domain.fqdn }}</h3>
              <span v-if="domain.is_default" class="text-xs bg-blue-500/20 text-blue-300 px-2 py-1 rounded">
                Default
              </span>
              <span
                class="text-xs px-2 py-1 rounded"
                :class="domain.status === 'unverified'
                  ? 'bg-amber-500/20 text-amber-300'
                  : 'bg-emerald-500/20 text-emerald-300'"
              >
                {{ domain.status === 'unverified' ? 'Sin verificar' : 'Activo' }}
              </span>
            </div>
            <div class="mt-2 text-sm text-slate-400 space-y-1">
              <p>
                <span class="text-slate-500">Apps:</span>
                {{ domain.apps_count }}
                <span v-if="domain.is_default" class="text-slate-500">
                  (incluye las apps sin dominio explícito)
                </span>
              </p>
              <p class="font-mono text-xs text-slate-500 break-all">
                zone {{ domain.cloudflare_zone_id || '—' }} · tunnel {{ domain.tunnel_id || '—' }}
              </p>
              <p v-if="domain.apex && domain.apex.routed === false" class="text-xs text-amber-300 mt-1 max-w-2xl">
                ⚠ {{ domain.apex.reason }}
              </p>
            </div>
          </div>

          <div class="flex items-center gap-2 flex-wrap">
            <button
              v-if="!domain.is_default"
              @click="setDefault(domain)"
              class="glass-button text-xs"
            >
              Hacer default
            </button>
            <button @click="reverify(domain)" :disabled="busyId === domain._id" class="glass-button text-xs">
              Re-verificar
            </button>
            <button @click="repair(domain)" :disabled="busyId === domain._id" class="glass-button text-xs">
              Recablear
            </button>
            <button
              @click="confirmDelete(domain)"
              :disabled="!canDelete(domain)"
              :title="deleteBlockReason(domain)"
              class="glass-button glass-button-danger text-xs"
            >
              Eliminar
            </button>
          </div>
        </div>

        <!-- Inline verification report -->
        <div v-if="reports[domain._id]" class="mt-4 pt-4 border-t border-white/10">
          <CheckList :checks="reports[domain._id].checks" />
        </div>
      </div>

      <div v-if="!loading && domains.length === 0" class="text-center py-12 text-slate-400">
        No hay dominios registrados todavía.
      </div>
    </div>

    <!-- Add domain modal -->
    <Transition name="modal">
      <div v-if="showAddModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" @click.self="closeAddModal">
        <div class="glass-panel rounded-xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
          <div class="p-6 border-b border-white/10">
            <h3 class="text-xl font-bold text-white">Agregar dominio</h3>
            <p class="text-sm text-slate-400 mt-1">
              Primero se valida contra Cloudflare. Solo se registra si todos los requisitos pasan:
              un dominio a medio cablear haría que las apps que lo elijan desplegaran a la nada.
            </p>
          </div>

          <div class="p-6 space-y-5">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-2">Dominio (FQDN)</label>
              <div class="flex gap-2">
                <input
                  v-model="newDomain.fqdn"
                  @input="report = null; addError = ''"
                  type="text"
                  placeholder="example.com"
                  class="glass-input flex-1"
                  autocomplete="off"
                />
                <button
                  @click="verify"
                  :disabled="!newDomain.fqdn || verifying"
                  class="glass-button text-sm whitespace-nowrap"
                >
                  {{ verifying ? 'Validando...' : 'Validar' }}
                </button>
              </div>
              <p class="text-xs text-slate-500 mt-2">
                Sin <span class="font-mono">www</span> ni protocolo. El dominio debe existir ya en la
                misma cuenta de Cloudflare que usa esta instalación.
              </p>
            </div>

            <!-- Requisitos -->
            <div v-if="!report" class="text-sm text-slate-400 bg-slate-900/40 rounded-lg p-4 space-y-2">
              <p class="font-medium text-slate-300">Antes de validar, asegúrate de que:</p>
              <ul class="list-disc list-inside space-y-1 text-slate-400">
                <li>El dominio está agregado en Cloudflare y su estado es <span class="text-emerald-400">active</span>.</li>
                <li>Los nameservers del registrador ya apuntan a Cloudflare.</li>
                <li>El token de Cloudflare de esta instalación tiene permiso sobre esa zona.</li>
                <li>Es la misma cuenta de Cloudflare donde vive el túnel.</li>
              </ul>
            </div>

            <!-- Reporte de validación -->
            <div v-if="report" class="space-y-3">
              <div
                class="rounded-lg p-4"
                :class="report.ok ? 'bg-emerald-500/10 border border-emerald-500/30' : 'bg-red-500/10 border border-red-500/30'"
              >
                <p class="font-medium" :class="report.ok ? 'text-emerald-300' : 'text-red-300'">
                  {{ report.ok ? 'Listo para registrar' : 'Todavía no se puede registrar' }}
                </p>
                <p v-if="report.ok" class="text-xs text-slate-400 mt-1">
                  Al registrar se agregarán las reglas <span class="font-mono">*.{{ report.fqdn }}</span> y
                  <span class="font-mono">{{ report.fqdn }}</span> al túnel, y el DNS wildcard apuntando a él.
                </p>
              </div>
              <CheckList :checks="report.checks" />
            </div>

            <label class="flex items-center gap-2 text-sm text-slate-300">
              <input v-model="newDomain.is_default" type="checkbox" class="rounded" />
              Hacerlo el dominio default de esta instalación
            </label>

            <div v-if="addError" class="text-sm text-red-300 bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              {{ addError }}
            </div>
          </div>

          <div class="p-6 border-t border-white/10 flex justify-end gap-3">
            <button @click="closeAddModal" class="glass-button text-sm">Cancelar</button>
            <button
              @click="createDomain"
              :disabled="!report || !report.ok || creating"
              class="glass-button glass-button-primary text-sm"
            >
              {{ creating ? 'Registrando...' : 'Registrar y cablear' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Delete confirmation -->
    <Transition name="modal">
      <div v-if="pendingDelete" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm" @click.self="pendingDelete = null">
        <div class="glass-panel rounded-xl w-full max-w-lg">
          <div class="p-6 space-y-3">
            <h3 class="text-xl font-bold text-white">Eliminar {{ pendingDelete.fqdn }}</h3>
            <p class="text-sm text-slate-400">
              Se quitarán sus reglas del túnel y los registros DNS wildcard y raíz.
              Las apps ya desplegadas en otros dominios no se tocan.
            </p>
          </div>
          <div class="p-6 border-t border-white/10 flex justify-end gap-3">
            <button @click="pendingDelete = null" class="glass-button text-sm">Cancelar</button>
            <button @click="doDelete" :disabled="deleting" class="glass-button glass-button-danger text-sm">
              {{ deleting ? 'Eliminando...' : 'Eliminar' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Toast -->
    <Transition name="toast">
      <div v-if="toast.show" class="fixed bottom-6 right-6 z-50 glass-panel px-5 py-3 rounded-lg"
           :class="toast.type === 'error' ? 'border-red-500/40' : 'border-emerald-500/40'">
        <span :class="toast.type === 'error' ? 'text-red-300' : 'text-emerald-300'">{{ toast.message }}</span>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, reactive, h, onMounted } from 'vue'
import axios from 'axios'

// Render-function component: una fila por chequeo del reporte de validación.
const CheckList = (props) => h('div', { class: 'space-y-2' },
  (props.checks || []).map((check) => h('div', { class: 'flex items-start gap-3 text-sm' }, [
    h('span', { class: 'mt-0.5' }, check.status === 'ok' ? '✅' : check.status === 'warn' ? '⚠️' : '❌'),
    h('div', { class: 'min-w-0' }, [
      h('p', {
        class: check.status === 'fail' ? 'text-red-300 font-medium' : 'text-slate-200 font-medium',
      }, check.label),
      check.detail ? h('p', { class: 'text-xs text-slate-400 mt-0.5 break-words' }, check.detail) : null,
    ]),
  ]))
)
CheckList.props = ['checks']

const domains = ref([])
const reports = ref({})
const loading = ref(false)
const busyId = ref(null)

const showAddModal = ref(false)
const newDomain = reactive({ fqdn: '', is_default: false })
const report = ref(null)
const verifying = ref(false)
const creating = ref(false)
const addError = ref('')

const pendingDelete = ref(null)
const deleting = ref(false)

const toast = reactive({ show: false, message: '', type: 'success' })
const showToast = (message, type = 'success') => {
  toast.message = message
  toast.type = type
  toast.show = true
  setTimeout(() => { toast.show = false }, 4000)
}

const errorText = (e, fallback) => {
  const detail = e.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  if (Array.isArray(detail?.blocking)) return `No pasó: ${detail.blocking.join(', ')}`
  return fallback
}

const loadDomains = async () => {
  loading.value = true
  try {
    const { data } = await axios.get('/api/v1/domains')
    domains.value = data || []
  } catch (e) {
    showToast(errorText(e, 'No se pudieron cargar los dominios'), 'error')
  } finally {
    loading.value = false
  }
}

// El default también responde por las apps que nunca fijaron dominio, así que
// su conteo ya viene sumado desde el API.
const canDelete = (domain) => domain.apps_count === 0 && !(domain.is_default && domains.value.length > 1)

const deleteBlockReason = (domain) => {
  if (domain.apps_count > 0) {
    return `${domain.apps_count} app(s) siguen usando este dominio. Múevelas a otro desde su exposición.`
  }
  if (domain.is_default && domains.value.length > 1) {
    return 'Marca otro dominio como default antes de eliminar este.'
  }
  return 'Eliminar dominio'
}

const openAddModal = () => {
  newDomain.fqdn = ''
  newDomain.is_default = false
  report.value = null
  addError.value = ''
  showAddModal.value = true
}

const closeAddModal = () => { showAddModal.value = false }

const verify = async () => {
  verifying.value = true
  addError.value = ''
  try {
    const { data } = await axios.post('/api/v1/domains/verify', {
      fqdn: newDomain.fqdn.trim().toLowerCase(),
    })
    report.value = data
  } catch (e) {
    addError.value = errorText(e, 'No se pudo validar el dominio')
  } finally {
    verifying.value = false
  }
}

const createDomain = async () => {
  creating.value = true
  addError.value = ''
  try {
    const { data } = await axios.post('/api/v1/domains', {
      fqdn: newDomain.fqdn.trim().toLowerCase(),
      is_default: newDomain.is_default,
    })
    showToast(
      data.apex?.routed === false
        ? `${data.fqdn} registrado. La raíz apunta a otro origen y se respetó.`
        : `${data.fqdn} registrado y cableado`
    )
    showAddModal.value = false
    await loadDomains()
  } catch (e) {
    addError.value = errorText(e, 'No se pudo registrar el dominio')
    if (e.response?.data?.detail?.checks) report.value = { ...e.response.data.detail, ok: false }
  } finally {
    creating.value = false
  }
}

const setDefault = async (domain) => {
  try {
    await axios.post(`/api/v1/domains/${domain._id}/set-default`)
    showToast(`${domain.fqdn} es ahora el dominio default`)
    await loadDomains()
  } catch (e) {
    showToast(errorText(e, 'No se pudo cambiar el default'), 'error')
  }
}

const reverify = async (domain) => {
  busyId.value = domain._id
  try {
    const { data } = await axios.post(`/api/v1/domains/${domain._id}/reverify`)
    reports.value = { ...reports.value, [domain._id]: data }
    showToast(data.ok ? `${domain.fqdn} verificado` : `${domain.fqdn} tiene problemas`, data.ok ? 'success' : 'error')
    await loadDomains()
  } catch (e) {
    showToast(errorText(e, 'No se pudo verificar'), 'error')
  } finally {
    busyId.value = null
  }
}

const repair = async (domain) => {
  busyId.value = domain._id
  try {
    await axios.post(`/api/v1/domains/${domain._id}/repair`)
    showToast(`${domain.fqdn} recableado`)
    await loadDomains()
  } catch (e) {
    showToast(errorText(e, 'No se pudo recablear'), 'error')
  } finally {
    busyId.value = null
  }
}

const confirmDelete = (domain) => {
  if (!canDelete(domain)) {
    showToast(deleteBlockReason(domain), 'error')
    return
  }
  pendingDelete.value = domain
}

const doDelete = async () => {
  deleting.value = true
  try {
    await axios.delete(`/api/v1/domains/${pendingDelete.value._id}`)
    showToast(`${pendingDelete.value.fqdn} eliminado`)
    pendingDelete.value = null
    await loadDomains()
  } catch (e) {
    showToast(errorText(e, 'No se pudo eliminar'), 'error')
  } finally {
    deleting.value = false
  }
}

onMounted(loadDomains)
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
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.25);
  color: white;
  font-weight: 500;
  transition: all 0.2s;
}
.glass-button:hover:not(:disabled) { background: rgba(148, 163, 184, 0.22); }
.glass-button:disabled { opacity: 0.45; cursor: not-allowed; }

.glass-button-primary {
  background: rgba(59, 130, 246, 0.2);
  border-color: rgba(59, 130, 246, 0.35);
}
.glass-button-primary:hover:not(:disabled) { background: rgba(59, 130, 246, 0.32); }

.glass-button-danger {
  background: rgba(239, 68, 68, 0.15);
  border-color: rgba(239, 68, 68, 0.3);
  color: rgb(252, 165, 165);
}
.glass-button-danger:hover:not(:disabled) { background: rgba(239, 68, 68, 0.25); }

.glass-input {
  padding: 0.6rem 0.9rem;
  border-radius: 0.5rem;
  background: rgba(15, 23, 42, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.12);
  color: white;
}
.glass-input:focus { outline: none; border-color: rgba(59, 130, 246, 0.5); }
</style>
