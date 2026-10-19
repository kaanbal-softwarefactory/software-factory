<template>
  <section class="space-y-4">
    <div class="rounded-2xl border border-white/10 bg-slate-900/60 p-5 space-y-2">
      <div class="flex justify-between items-center gap-3 flex-wrap">
        <h2 class="text-lg font-semibold text-white">Solicitudes de agentes</h2>
        <button @click="load" :disabled="loading" class="text-sm text-cyan-300 disabled:opacity-40">{{ loading ? 'Actualizando…' : 'Actualizar' }}</button>
      </div>
      <p class="text-sm text-slate-400">Un agente conectado por MCP no ejecuta lo irreversible por su cuenta: lo deja aquí para que una persona lo revise. También pide aquí los secretos que solo tú tienes, para no verlos nunca.</p>
      <p v-if="message" role="status" class="text-sm" :class="failed ? 'text-red-300' : 'text-emerald-300'">{{ message }}</p>
    </div>

    <div v-if="canApprove" class="rounded-2xl border border-white/10 p-5 space-y-3">
      <h3 class="text-white font-medium">Acciones que esperan aprobación</h3>
      <p v-if="!pending.length" class="text-sm text-slate-500">No hay acciones pendientes.</p>
      <div v-for="item in pending" :key="item.id" class="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-2">
        <div class="flex justify-between gap-3 flex-wrap">
          <p class="text-amber-200 font-medium">{{ item.label }} · <span class="font-mono text-sm">{{ item.target }}</span></p>
          <p class="text-xs text-slate-400">Vence {{ when(item.expires_at) }}</p>
        </div>
        <pre class="text-xs text-slate-200 bg-black/40 rounded-lg p-3 whitespace-pre-wrap break-all">{{ item.summary }}</pre>
        <p v-if="item.reason" class="text-sm text-slate-300">Motivo del agente: {{ item.reason }}</p>
        <p class="text-xs text-slate-500">Pedida por {{ item.actor }} con el token «{{ item.token_name }}» · {{ when(item.created_at) }} · id {{ item.id }}</p>
        <label class="block text-xs text-slate-400">Nota (opcional)<input v-model="notes[item.id]" class="field" maxlength="500" /></label>
        <div class="flex gap-2">
          <button @click="decide(item, true)" :disabled="busy || !password" class="px-3 py-1.5 rounded-lg bg-emerald-500/20 border border-emerald-500/30 text-emerald-200 text-sm disabled:opacity-40">Aprobar</button>
          <button @click="decide(item, false)" :disabled="busy || !password" class="px-3 py-1.5 rounded-lg bg-red-500/20 border border-red-500/30 text-red-200 text-sm disabled:opacity-40">Rechazar</button>
        </div>
      </div>
      <div v-if="pending.length" class="grid gap-3 sm:grid-cols-2">
        <label class="text-xs text-slate-400">Usuario de tu sesión<input v-model="adminUsername" autocomplete="username" class="field" /></label>
        <label class="text-xs text-slate-400">Contraseña (confirma cada decisión)<input v-model="password" type="password" autocomplete="current-password" class="field" /></label>
      </div>
      <details v-if="decided.length" class="text-sm text-slate-400">
        <summary class="cursor-pointer">Historial reciente ({{ decided.length }})</summary>
        <ul class="mt-2 space-y-1">
          <li v-for="item in decided" :key="item.id" class="text-xs">
            <span :class="stateClass(item.state)">{{ stateLabel(item.state) }}</span> · {{ item.label }} · <span class="font-mono">{{ item.target }}</span>
            <span v-if="item.decided_by"> · {{ item.decided_by }}</span> · {{ when(item.decided_at || item.created_at) }}
          </li>
        </ul>
      </details>
    </div>

    <div v-if="canFulfill" class="rounded-2xl border border-white/10 p-5 space-y-3">
      <h3 class="text-white font-medium">Secretos pedidos</h3>
      <p v-if="!secrets.length" class="text-sm text-slate-500">No hay secretos pendientes.</p>
      <div v-for="item in secrets" :key="item.id" class="rounded-xl border border-white/10 p-4 space-y-2">
        <p class="text-white"><span class="font-mono">{{ item.variable }}</span> para <span class="font-mono">{{ item.app }}</span> <span class="text-xs text-slate-400">({{ (item.environments || []).join(', ') }})</span></p>
        <p class="text-sm text-slate-300">{{ item.reason }}</p>
        <p class="text-xs text-slate-500">Pedido por {{ item.requested_by }} · {{ when(item.created_at) }}</p>
        <label class="block text-xs text-slate-400">Valor (no se vuelve a mostrar)<input v-model="values[item.id]" type="password" autocomplete="off" class="field" /></label>
        <label class="flex gap-2 text-xs text-slate-400"><input v-model="overwrite[item.id]" type="checkbox" /> Reemplazar si la variable ya existe</label>
        <div class="flex gap-2">
          <button @click="fulfill(item)" :disabled="busy || !values[item.id]" class="px-3 py-1.5 rounded-lg bg-blue-500/20 border border-blue-500/30 text-blue-200 text-sm disabled:opacity-40">Guardar en la app</button>
          <button @click="cancel(item)" :disabled="busy" class="px-3 py-1.5 rounded-lg border border-white/10 text-slate-300 text-sm disabled:opacity-40">Descartar</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'

const props = defineProps({ username: String, canApprove: Boolean, canFulfill: Boolean })
const approvals = ref([])
const secrets = ref([])
const notes = reactive({})
const values = reactive({})
const overwrite = reactive({})
const adminUsername = ref(props.username)
const password = ref('')
const loading = ref(false)
const busy = ref(false)
const message = ref('')
const failed = ref(false)

const pending = computed(() => approvals.value.filter(item => item.state === 'pending'))
const decided = computed(() => approvals.value.filter(item => item.state !== 'pending').slice(0, 20))
const when = value => value ? new Date(value).toLocaleString() : ''
const explain = error => typeof error.response?.data?.detail === 'string' ? error.response.data.detail : 'No se pudo completar la acción.'
const labels = { approved: 'Aprobada', rejected: 'Rechazada', used: 'Usada', expired: 'Vencida' }
const stateLabel = state => labels[state] || state
const stateClass = state => state === 'rejected' ? 'text-red-300' : state === 'expired' ? 'text-slate-500' : 'text-emerald-300'
const report = (text, error = false) => { message.value = text; failed.value = error }

const load = async () => {
  loading.value = true
  try {
    const [a, s] = await Promise.all([
      props.canApprove ? axios.get('/api/v1/autonomy/approvals') : Promise.resolve({ data: { approvals: [] } }),
      props.canFulfill ? axios.get('/api/v1/secret-requests', { params: { state: 'pending' } }) : Promise.resolve({ data: { requests: [] } }),
    ])
    approvals.value = a.data.approvals || []
    secrets.value = s.data.requests || []
  } catch (error) { report(explain(error), true) } finally { loading.value = false }
}

const decide = async (item, approve) => {
  busy.value = true
  try {
    await axios.post(`/api/v1/autonomy/approvals/${item.id}/${approve ? 'approve' : 'reject'}`, {
      admin_username: adminUsername.value, admin_password: password.value, note: notes[item.id] || '',
    })
    report(approve ? 'Aprobada. El agente puede repetir la llamada con su approval_id durante 30 minutos.' : 'Rechazada. El agente verá el motivo.')
    await load()
  } catch (error) { report(explain(error), true) } finally { busy.value = false }
}

const fulfill = async item => {
  busy.value = true
  try {
    const { data } = await axios.post(`/api/v1/secret-requests/${item.id}/fulfill`, { value: values[item.id], overwrite: !!overwrite[item.id] })
    values[item.id] = ''
    report(data.variable?.message || 'Guardado. La app se reinicia con la variable nueva.')
    await load()
  } catch (error) { report(explain(error), true) } finally { busy.value = false }
}

const cancel = async item => {
  busy.value = true
  try {
    await axios.post(`/api/v1/secret-requests/${item.id}/cancel`)
    report('Solicitud descartada.')
    await load()
  } catch (error) { report(explain(error), true) } finally { busy.value = false }
}

onMounted(load)
</script>

<style scoped>
.field { display: block; width: 100%; margin-top: 0.35rem; border: 1px solid rgb(255 255 255 / 0.1); border-radius: 0.5rem; background: rgb(30 41 59); padding: 0.5rem 0.75rem; color: white; font-size: 0.875rem; }
</style>
