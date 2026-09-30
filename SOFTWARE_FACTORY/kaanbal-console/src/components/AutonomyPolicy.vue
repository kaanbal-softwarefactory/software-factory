<template>
  <section class="space-y-4">
    <div class="rounded-2xl border border-white/10 bg-slate-900/60 p-5 space-y-4">
      <h2 class="text-lg font-semibold text-white">Autonomía de agentes</h2>
      <p class="text-sm text-slate-400">Cada acción requiere permiso en el rol, alcance en el token y una concesión vigente sobre el recurso. Los comandos de apps y nodos exigen además un token crítico confirmado con contraseña.</p>
      <label class="flex gap-2 text-white"><input v-model="policy.enabled" type="checkbox" /> Habilitar autonomía</label>
      <div class="grid gap-3 sm:grid-cols-2 text-sm text-slate-300">
        <label class="flex gap-2"><input v-model="policy.workspace_enabled" type="checkbox" /> Editar código en workspaces</label>
        <label class="flex gap-2"><input v-model="policy.runtime_enabled" type="checkbox" /> Comandos en apps autorizadas</label>
        <label class="flex gap-2 text-amber-300"><input v-model="policy.host_enabled" type="checkbox" /> Comandos root en nodos autorizados</label>
        <label class="flex gap-2"><input v-model="policy.merge_enabled" type="checkbox" /> Merge de PRs de apps</label>
      </div>
      <p v-if="policy.host_enabled || policy.runtime_enabled" class="text-sm text-amber-200 border border-amber-500/30 rounded-lg p-3">Los comandos pueden modificar o borrar datos y acceder a credenciales. El acceso a nodos equivale a root. La activación requiere también los permisos Kubernetes correspondientes en GitOps.</p>
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="text-xs text-slate-400">Imagen versionada del workbench<input v-model="policy.workbench_image" placeholder="registro/kaanbal-workbench:version" class="field" /></label>
        <label class="text-xs text-slate-400">Fork de Kaanbal, si upstream no permite ramas<input v-model="policy.core_fork" placeholder="organizacion/software-factory" class="field" /></label>
      </div>
      <label class="block text-xs text-slate-400">Duración del workspace (segundos, hasta 4 horas)<input v-model.number="policy.workspace_lifetime_seconds" type="number" min="300" max="14400" class="field max-w-xs" /></label>
    </div>
    <div v-for="(grant, index) in grants" :key="index" class="rounded-2xl border border-white/10 p-5 space-y-3">
      <div class="flex justify-between"><h3 class="text-white">Concesión {{ index + 1 }}</h3><button @click="grants.splice(index, 1)" class="text-xs text-red-300">Quitar</button></div>
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="text-xs text-slate-400">Usuario<select v-model="grant.username" class="field"><option value="">Selecciona una cuenta</option><option v-for="user in users" :key="user.username" :value="user.username">{{ user.username }}</option><option v-if="!users.some(u => u.username === grant.username) && grant.username" :value="grant.username">{{ grant.username }}</option></select></label>
        <label class="text-xs text-slate-400">ID del token (opcional; vacío permite sus tokens autorizados)<input v-model="grant.token_id" class="field" /></label>
        <label class="text-xs text-slate-400">Apps, separadas por comas<input v-model="grant.appsText" placeholder="demo-api" class="field" /></label>
        <label class="text-xs text-slate-400">Ambientes, separados por comas<input v-model="grant.envsText" placeholder="dev, prod" class="field" /></label>
        <label class="text-xs text-slate-400">Nodos exactos, separados por comas<input v-model="grant.nodesText" class="field" /></label>
        <label class="text-xs text-slate-400">Fin de la concesión (hora local, opcional)<input v-model="grant.expiresLocal" type="datetime-local" class="field" /></label>
      </div>
      <label class="flex gap-2 text-sm text-slate-300"><input v-model="grant.core" type="checkbox" /> Puede preparar contribuciones a Kaanbal para revisión del owner</label>
    </div>
    <button @click="addGrant" class="text-sm text-cyan-300">+ Agregar concesión</button>
    <div class="rounded-2xl border border-white/10 p-5 space-y-3">
      <p class="text-sm text-slate-300">Confirma tu identidad para guardar los alcances.</p>
      <div class="grid gap-3 sm:grid-cols-2">
        <label class="text-xs text-slate-400">Usuario de tu sesión<input v-model="adminUsername" autocomplete="username" class="field" /></label>
        <label class="text-xs text-slate-400">Contraseña<input v-model="password" type="password" autocomplete="current-password" class="field" /></label>
      </div>
      <p v-if="message" role="status" class="text-sm" :class="failed ? 'text-red-300' : 'text-emerald-300'">{{ message }}</p>
      <button @click="save" :disabled="saving || !loaded || !password" class="px-4 py-2 rounded-lg bg-blue-500/20 border border-blue-500/30 text-blue-200 disabled:opacity-40">{{ saving ? 'Guardando…' : 'Guardar política' }}</button>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import axios from 'axios'

const props = defineProps({ username: String, users: { type: Array, default: () => [] } })
const policy = ref({ enabled: false, workspace_enabled: false, runtime_enabled: false, host_enabled: false, merge_enabled: false, workbench_image: '', core_fork: '', workspace_lifetime_seconds: 3600 })
const grants = ref([])
const adminUsername = ref(props.username)
const password = ref('')
const saving = ref(false)
const loaded = ref(false)
const message = ref('')
const failed = ref(false)
const localDate = value => { const date = new Date(value); return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16) }
const split = value => [...new Set(value.split(',').map(v => v.trim()).filter(Boolean))]
const addGrant = () => grants.value.push({ username: '', token_id: '', appsText: '', envsText: 'prod', nodesText: '', core: false, expiresLocal: '' })
const explain = error => typeof error.response?.data?.detail === 'string' ? error.response.data.detail : 'Revisa los nombres, fechas y campos de la política.'

onMounted(async () => {
  try {
    const { data } = await axios.get('/api/v1/autonomy/policy')
    const { grants: rows, ...settings } = data
    policy.value = settings
    grants.value = rows.map(row => ({ username: row.username, token_id: row.token_id || '', core: row.core,
      appsText: row.apps.join(', '), envsText: row.environments.join(', '), nodesText: row.nodes.join(', '),
      expiresLocal: row.expires_at ? localDate(row.expires_at) : '' }))
    loaded.value = true
  } catch (error) { failed.value = true; message.value = explain(error) }
})

const save = async () => {
  saving.value = true
  try {
    const rows = grants.value.map(row => ({ username: row.username, token_id: row.token_id || null, core: row.core,
      apps: split(row.appsText), environments: split(row.envsText), nodes: split(row.nodesText),
      expires_at: row.expiresLocal ? new Date(row.expiresLocal).toISOString() : null }))
    await axios.put('/api/v1/autonomy/policy', { policy: { ...policy.value, grants: rows }, admin_username: adminUsername.value, admin_password: password.value })
    failed.value = false
    message.value = 'Política guardada. Los cambios se comprueban en cada nueva operación.'
  } catch (error) { failed.value = true; message.value = explain(error) }
  finally { saving.value = false; password.value = '' }
}
</script>

<style scoped>
.field { display: block; width: 100%; margin-top: 0.35rem; border: 1px solid rgb(255 255 255 / 0.1); border-radius: 0.5rem; background: rgb(30 41 59); padding: 0.5rem 0.75rem; color: white; font-size: 0.875rem; }
</style>
