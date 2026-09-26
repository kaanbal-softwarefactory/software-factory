<template>
  <div class="space-y-6">
    <div class="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h1 class="text-3xl font-bold bg-gradient-to-r from-cyan-400 to-blue-500 bg-clip-text text-transparent">Acceso</h1>
        <p class="mt-2 text-slate-400">Quién entra, qué puede hacer y con qué credenciales se conecta.</p>
      </div>
      <div class="inline-flex rounded-xl border border-white/10 bg-white/[0.03] p-1">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          @click="activeTab = tab.id"
          class="px-3 py-1.5 rounded-lg text-xs font-medium transition-colors"
          :class="activeTab === tab.id ? 'bg-blue-500/20 text-blue-200 border border-blue-500/30' : 'text-slate-400 hover:text-white border border-transparent'"
        >{{ tab.label }}</button>
      </div>
    </div>

    <!-- ── Personas ── -->
    <section v-if="activeTab === 'users'" class="space-y-4">
      <div class="flex justify-between items-center gap-3 flex-wrap">
        <p class="text-xs text-slate-500">{{ users.length }} cuenta(s). Los permisos salen de sus roles, más las excepciones de cada quien.</p>
        <button v-if="can('security.users.manage')" @click="openUserModal()" class="glass-button text-sm">+ Nueva persona</button>
      </div>

      <div class="glass-panel rounded-2xl overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-white/[0.03] text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th class="text-left px-4 py-3">Cuenta</th>
              <th class="text-left px-4 py-3">Roles</th>
              <th class="text-left px-4 py-3">Permisos</th>
              <th class="text-left px-4 py-3">Estado</th>
              <th class="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in users" :key="user.id" class="border-t border-white/5">
              <td class="px-4 py-3">
                <p class="text-white font-medium">{{ user.username }}</p>
                <p class="text-xs text-slate-500">{{ user.email || 'sin correo' }}</p>
              </td>
              <td class="px-4 py-3">
                <span v-for="slug in user.roles" :key="slug" class="inline-block mr-1 mb-1 text-[10px] px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-300 border border-cyan-500/30">
                  {{ roleName(slug) }}
                </span>
                <span v-if="!user.roles.length" class="text-xs text-slate-600">sin rol</span>
              </td>
              <td class="px-4 py-3 text-slate-400">
                {{ user.permissions.length }}
                <span v-if="Object.keys(user.permission_overrides || {}).length" class="text-[10px] text-amber-300">
                  · {{ Object.keys(user.permission_overrides).length }} excepción(es)
                </span>
              </td>
              <td class="px-4 py-3">
                <span :class="user.disabled ? 'text-red-300' : 'text-emerald-300'">{{ user.disabled ? 'Suspendida' : 'Activa' }}</span>
              </td>
              <td class="px-4 py-3 text-right whitespace-nowrap">
                <button v-if="can('security.users.manage')" @click="openUserModal(user)" class="text-xs text-slate-400 hover:text-white">Editar</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- ── Roles ── -->
    <section v-else-if="activeTab === 'roles'" class="space-y-4">
      <div class="flex justify-between items-center gap-3 flex-wrap">
        <p class="text-xs text-slate-500">Los roles del sistema vienen con Kaanbal y no se editan; puedes crear los tuyos.</p>
        <button v-if="can('security.roles.manage')" @click="openRoleModal()" class="glass-button text-sm">+ Nuevo rol</button>
      </div>

      <div class="grid gap-4 md:grid-cols-2">
        <div v-for="role in roles" :key="role.slug" class="glass-panel rounded-2xl p-5">
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <h3 class="text-white font-bold flex items-center gap-2">
                {{ role.name }}
                <span v-if="role.system" class="text-[10px] px-2 py-0.5 rounded bg-slate-500/20 text-slate-300">del sistema</span>
                <span v-if="role.superadmin" class="text-[10px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300">todo</span>
              </h3>
              <p class="text-xs text-slate-500 mt-1">{{ role.description }}</p>
            </div>
            <button
              v-if="can('security.roles.manage') && !role.system"
              @click="openRoleModal(role)"
              class="text-xs text-slate-400 hover:text-white shrink-0"
            >Editar</button>
          </div>
          <p class="text-xs text-slate-400 mt-3">
            {{ role.superadmin ? 'Todos los permisos' : `${(role.permissions || []).length} permiso(s)` }}
            · {{ role.users }} persona(s)
          </p>
        </div>
      </div>
    </section>

    <!-- ── Tokens ── -->
    <section v-else class="space-y-4">
      <div class="flex justify-between items-center gap-3 flex-wrap">
        <p class="text-xs text-slate-500">
          Un token por uso (un agente, un MCP, un script). Nunca puede más que tú, y se ve una sola vez.
        </p>
        <div class="flex items-center gap-2">
          <label v-if="can('security.tokens.admin')" class="flex items-center gap-1.5 text-xs text-slate-400">
            <input type="checkbox" v-model="allTokens" @change="loadTokens" /> de todo el equipo
          </label>
          <button @click="openTokenModal()" class="glass-button text-sm">+ Nuevo token</button>
        </div>
      </div>

      <!-- El valor recién creado: única vez que se muestra -->
      <div v-if="created.token" class="glass-panel rounded-2xl p-5 border-emerald-500/40">
        <p class="text-sm text-emerald-300 font-semibold mb-2">Token «{{ created.name }}» creado</p>
        <div class="flex items-center gap-2 flex-wrap">
          <code class="font-mono text-xs bg-black/40 border border-white/10 rounded-lg px-3 py-2 break-all flex-1 min-w-0">{{ created.token }}</code>
          <button @click="copyToken" class="glass-button text-xs shrink-0">{{ copied ? '✓ Copiado' : 'Copiar' }}</button>
          <button @click="created = {}" class="text-xs text-slate-400 hover:text-white shrink-0">Ya lo guardé</button>
        </div>
        <p class="text-xs text-amber-300/90 mt-2">No se vuelve a mostrar. Si se pierde, revócalo y crea otro.</p>
      </div>

      <div class="glass-panel rounded-2xl overflow-hidden">
        <table class="w-full text-sm">
          <thead class="bg-white/[0.03] text-[10px] uppercase tracking-wider text-slate-500">
            <tr>
              <th class="text-left px-4 py-3">Nombre</th>
              <th v-if="allTokens" class="text-left px-4 py-3">Dueño</th>
              <th class="text-left px-4 py-3">Alcance</th>
              <th class="text-left px-4 py-3">Último uso</th>
              <th class="text-left px-4 py-3">Estado</th>
              <th class="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="token in tokens" :key="token.id" class="border-t border-white/5">
              <td class="px-4 py-3">
                <p class="text-white">{{ token.name }}</p>
                <p class="text-[10px] text-slate-600 font-mono">kbl_{{ token.prefix }}…</p>
              </td>
              <td v-if="allTokens" class="px-4 py-3 text-slate-400">{{ token.username }}</td>
              <td class="px-4 py-3 text-slate-400">
                {{ token.scopes.length ? `${token.scopes.length} permiso(s)` : 'todo lo de su dueño' }}
              </td>
              <td class="px-4 py-3 text-slate-500 text-xs">{{ token.last_used_at ? formatDate(token.last_used_at) : 'nunca' }}</td>
              <td class="px-4 py-3">
                <span :class="token.state === 'activo' ? 'text-emerald-300' : 'text-slate-500'">{{ token.state }}</span>
              </td>
              <td class="px-4 py-3 text-right">
                <button v-if="token.state === 'activo'" @click="revokeToken(token)" class="text-xs text-red-400 hover:text-red-300">Revocar</button>
              </td>
            </tr>
            <tr v-if="!tokens.length"><td colspan="6" class="px-4 py-8 text-center text-slate-500 text-sm">Todavía no hay tokens.</td></tr>
          </tbody>
        </table>
      </div>
    </section>

    <!-- Modal: persona -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="userModal.show" class="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" @click.self="userModal.show = false">
          <div class="w-full max-w-lg bg-slate-900 border border-white/10 rounded-2xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-white/10">
              <h3 class="text-xl font-bold text-white">{{ userModal.editing ? `Editar ${userModal.form.username}` : 'Nueva persona' }}</h3>
            </div>
            <div class="p-6 space-y-4">
              <div v-if="!userModal.editing">
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Usuario</label>
                <input v-model="userModal.form.username" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <div v-if="!userModal.editing">
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Contraseña</label>
                <input v-model="userModal.form.password" type="password" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
                <p class="text-[11px] text-slate-500 mt-1">Mínimo 10 caracteres.</p>
              </div>
              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Correo</label>
                <input v-model="userModal.form.email" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-2">Roles</label>
                <label v-for="role in roles" :key="role.slug" class="flex items-start gap-2 text-sm text-slate-300 py-1 cursor-pointer">
                  <input type="checkbox" :value="role.slug" v-model="userModal.form.roles" class="mt-1" />
                  <span>
                    {{ role.name }}
                    <span class="block text-[11px] text-slate-500">{{ role.description }}</span>
                  </span>
                </label>
              </div>
              <label v-if="userModal.editing" class="flex items-center gap-2 text-sm text-slate-300 cursor-pointer">
                <input type="checkbox" v-model="userModal.form.disabled" />
                <span>Cuenta suspendida</span>
              </label>
              <div v-if="userModal.editing">
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Contraseña nueva (opcional)</label>
                <input v-model="userModal.form.password" type="password" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <p v-if="userModal.error" class="text-sm text-red-300">{{ userModal.error }}</p>
            </div>
            <div class="p-6 border-t border-white/10 flex justify-end gap-3">
              <button @click="userModal.show = false" class="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancelar</button>
              <button @click="saveUser" :disabled="userModal.saving" class="glass-button disabled:opacity-50">Guardar</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Modal: rol -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="roleModal.show" class="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" @click.self="roleModal.show = false">
          <div class="w-full max-w-2xl bg-slate-900 border border-white/10 rounded-2xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-white/10">
              <h3 class="text-xl font-bold text-white">{{ roleModal.editing ? 'Editar rol' : 'Nuevo rol' }}</h3>
              <p class="text-sm text-slate-400 mt-1">Marca lo que puede hacer quien tenga este rol.</p>
            </div>
            <div class="p-6 space-y-4">
              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Nombre</label>
                <input v-model="roleModal.form.name" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Descripción</label>
                <input v-model="roleModal.form.description" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <div v-for="(group, module) in permissionsByModule" :key="module" class="rounded-xl border border-white/5 bg-black/20 p-3">
                <p class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">{{ module }}</p>
                <label v-for="item in group" :key="item.key" class="flex items-start gap-2 text-sm py-1 cursor-pointer">
                  <input type="checkbox" :value="item.key" v-model="roleModal.form.permissions" class="mt-1" />
                  <span class="min-w-0">
                    <span class="text-slate-200">{{ item.description }}</span>
                    <span v-if="item.risk !== 'normal'" class="ml-1.5 text-[10px] px-1.5 py-0.5 rounded" :class="item.risk === 'critico' ? 'bg-red-500/15 text-red-300' : 'bg-amber-500/15 text-amber-300'">{{ item.risk }}</span>
                    <span class="block text-[10px] text-slate-600 font-mono">{{ item.key }}</span>
                  </span>
                </label>
              </div>
              <p v-if="roleModal.error" class="text-sm text-red-300">{{ roleModal.error }}</p>
            </div>
            <div class="p-6 border-t border-white/10 flex justify-between gap-3">
              <button
                v-if="roleModal.editing"
                @click="deleteRole"
                class="px-4 py-2 text-sm text-red-400 hover:text-red-300"
              >Eliminar rol</button>
              <div class="ml-auto flex gap-3">
                <button @click="roleModal.show = false" class="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancelar</button>
                <button @click="saveRole" :disabled="roleModal.saving" class="glass-button disabled:opacity-50">Guardar</button>
              </div>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Modal: token -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="tokenModal.show" class="fixed inset-0 z-[90] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm" @click.self="tokenModal.show = false">
          <div class="w-full max-w-2xl bg-slate-900 border border-white/10 rounded-2xl max-h-[90vh] overflow-y-auto">
            <div class="p-6 border-b border-white/10">
              <h3 class="text-xl font-bold text-white">Nuevo token personal</h3>
              <p class="text-sm text-slate-400 mt-1">Para conectar un agente, un MCP o un script a esta plataforma.</p>
            </div>
            <div class="p-6 space-y-4">
              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Para qué es</label>
                <input v-model="tokenModal.form.name" placeholder="MCP de mi equipo" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <div>
                <label class="block text-xs uppercase tracking-wider text-slate-500 mb-1.5">Caduca en (días)</label>
                <input v-model.number="tokenModal.form.expires_in_days" type="number" min="1" max="365" class="w-full bg-slate-800/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm" />
              </div>
              <div>
                <div class="flex items-center justify-between mb-2">
                  <label class="text-xs uppercase tracking-wider text-slate-500">Alcance</label>
                  <button @click="tokenModal.form.scopes = [...readOnlyScopes]" class="text-[11px] text-cyan-300 hover:underline">Solo lectura (recomendado)</button>
                </div>
                <p class="text-[11px] text-slate-500 mb-2">Sin marcar nada, el token hereda todo lo que tú puedes. Marca lo mínimo que necesite.</p>
                <div v-for="(group, module) in myPermissionsByModule" :key="module" class="rounded-xl border border-white/5 bg-black/20 p-3 mb-2">
                  <p class="text-[10px] uppercase tracking-wider text-slate-500 mb-2">{{ module }}</p>
                  <label v-for="item in group" :key="item.key" class="flex items-start gap-2 text-sm py-1 cursor-pointer">
                    <input type="checkbox" :value="item.key" v-model="tokenModal.form.scopes" class="mt-1" />
                    <span class="min-w-0">
                      <span class="text-slate-200">{{ item.description }}</span>
                      <span class="block text-[10px] text-slate-600 font-mono">{{ item.key }}</span>
                    </span>
                  </label>
                </div>
              </div>
              <p v-if="tokenModal.error" class="text-sm text-red-300">{{ tokenModal.error }}</p>
            </div>
            <div class="p-6 border-t border-white/10 flex justify-end gap-3">
              <button @click="tokenModal.show = false" class="px-4 py-2 text-sm text-slate-400 hover:text-white">Cancelar</button>
              <button @click="createToken" :disabled="tokenModal.saving || !tokenModal.form.name" class="glass-button disabled:opacity-50">Crear</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Toast -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="toast.show" :class="['fixed bottom-6 right-6 z-[100] px-6 py-4 rounded-xl shadow-2xl backdrop-blur-xl border', toast.type === 'success' ? 'bg-emerald-900/90 border-emerald-500/50 text-emerald-100' : 'bg-red-900/90 border-red-500/50 text-red-100']">
          <p class="font-medium">{{ toast.message }}</p>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import axios from 'axios'

const tabs = [
  { id: 'users', label: '👥 Personas' },
  { id: 'roles', label: '🎭 Roles' },
  { id: 'tokens', label: '🔑 Tokens' },
]

const activeTab = ref('users')
const me = ref({ permissions: [] })
const users = ref([])
const roles = ref([])
const tokens = ref([])
const catalog = ref([])
const allTokens = ref(false)
const created = ref({})
const copied = ref(false)

const toast = reactive({ show: false, message: '', type: 'success' })
const userModal = reactive({ show: false, editing: null, saving: false, error: '', form: {} })
const roleModal = reactive({ show: false, editing: null, saving: false, error: '', form: {} })
const tokenModal = reactive({ show: false, saving: false, error: '', form: {} })

const showToast = (message, type = 'success') => {
  Object.assign(toast, { show: true, message, type })
  setTimeout(() => { toast.show = false }, 4000)
}

const can = (permission) => me.value.superadmin || (me.value.permissions || []).includes(permission)
const roleName = (slug) => roles.value.find(r => r.slug === slug)?.name || slug
const formatDate = (value) => new Date(value).toLocaleString('es-MX', { dateStyle: 'short', timeStyle: 'short' })

const groupByModule = (items) => items.reduce((acc, item) => {
  (acc[item.module] ||= []).push(item)
  return acc
}, {})

const permissionsByModule = computed(() => groupByModule(catalog.value))
// Un token no puede dar lo que su dueño no tiene: solo se ofrece lo propio.
const myPermissionsByModule = computed(() =>
  groupByModule(catalog.value.filter(item => can(item.key)))
)
const readOnlyScopes = computed(() =>
  catalog.value.filter(item => ['view', 'diagnose'].includes(item.action) && can(item.key)).map(item => item.key)
)

const load = async () => {
  try {
    const [meRes, permsRes, rolesRes] = await Promise.all([
      axios.get('/api/v1/security/me'),
      axios.get('/api/v1/security/permissions'),
      axios.get('/api/v1/security/roles'),
    ])
    me.value = meRes.data
    catalog.value = permsRes.data.permissions
    roles.value = rolesRes.data.roles
    if (can('security.users.view')) users.value = (await axios.get('/api/v1/security/users')).data.users
    await loadTokens()
  } catch (e) {
    showToast(e.response?.data?.detail || 'No se pudo cargar la sección de acceso', 'error')
  }
}

const loadTokens = async () => {
  const url = allTokens.value ? '/api/v1/security/tokens/all' : '/api/v1/security/tokens'
  tokens.value = (await axios.get(url)).data.tokens
}

// ── Personas ──
const openUserModal = (user = null) => {
  userModal.editing = user
  userModal.error = ''
  userModal.form = user
    ? { username: user.username, email: user.email || '', roles: [...user.roles], disabled: user.disabled, password: '' }
    : { username: '', email: '', roles: ['lector'], disabled: false, password: '' }
  userModal.show = true
}

const saveUser = async () => {
  userModal.saving = true
  userModal.error = ''
  try {
    const { username, email, roles: userRoles, disabled, password } = userModal.form
    if (userModal.editing) {
      await axios.patch(`/api/v1/security/users/${username}`, { email, roles: userRoles, disabled })
      if (password) await axios.post(`/api/v1/security/users/${username}/password`, { password })
    } else {
      await axios.post('/api/v1/security/users', { username, password, email, roles: userRoles })
    }
    userModal.show = false
    showToast(userModal.editing ? 'Cuenta actualizada' : `Cuenta ${username} creada`)
    await load()
  } catch (e) {
    userModal.error = e.response?.data?.detail || 'No se pudo guardar'
  } finally {
    userModal.saving = false
  }
}

// ── Roles ──
const openRoleModal = (role = null) => {
  roleModal.editing = role
  roleModal.error = ''
  roleModal.form = role
    ? { name: role.name, description: role.description || '', permissions: [...(role.permissions || [])] }
    : { name: '', description: '', permissions: [] }
  roleModal.show = true
}

const saveRole = async () => {
  roleModal.saving = true
  roleModal.error = ''
  try {
    if (roleModal.editing) await axios.patch(`/api/v1/security/roles/${roleModal.editing.slug}`, roleModal.form)
    else await axios.post('/api/v1/security/roles', roleModal.form)
    roleModal.show = false
    showToast('Rol guardado')
    await load()
  } catch (e) {
    roleModal.error = e.response?.data?.detail || 'No se pudo guardar el rol'
  } finally {
    roleModal.saving = false
  }
}

const deleteRole = async () => {
  if (!window.confirm(`¿Eliminar el rol ${roleModal.editing.name}?`)) return
  try {
    await axios.delete(`/api/v1/security/roles/${roleModal.editing.slug}`)
    roleModal.show = false
    showToast('Rol eliminado')
    await load()
  } catch (e) {
    roleModal.error = e.response?.data?.detail || 'No se pudo eliminar'
  }
}

// ── Tokens ──
const openTokenModal = () => {
  tokenModal.error = ''
  tokenModal.form = { name: '', scopes: [], expires_in_days: 90 }
  tokenModal.show = true
}

const createToken = async () => {
  tokenModal.saving = true
  tokenModal.error = ''
  try {
    const { data } = await axios.post('/api/v1/security/tokens', tokenModal.form)
    created.value = data
    copied.value = false
    tokenModal.show = false
    await loadTokens()
  } catch (e) {
    tokenModal.error = e.response?.data?.detail || 'No se pudo crear el token'
  } finally {
    tokenModal.saving = false
  }
}

const copyToken = async () => {
  try {
    await navigator.clipboard.writeText(created.value.token)
    copied.value = true
  } catch {
    showToast('Cópialo a mano: el navegador no dio permiso al portapapeles', 'error')
  }
}

const revokeToken = async (token) => {
  if (!window.confirm(`¿Revocar «${token.name}»? Lo que lo use dejará de conectarse.`)) return
  try {
    await axios.delete(`/api/v1/security/tokens/${token.id}`)
    showToast('Token revocado')
    await loadTokens()
  } catch (e) {
    showToast(e.response?.data?.detail || 'No se pudo revocar', 'error')
  }
}

onMounted(load)
</script>

<style scoped>
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

.glass-panel {
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.glass-button {
  padding: 0.6rem 1.2rem;
  border-radius: 0.5rem;
  background: rgba(59, 130, 246, 0.2);
  border: 1px solid rgba(59, 130, 246, 0.3);
  color: white;
  font-weight: 500;
  transition: all 0.2s;
}

.glass-button:hover { background: rgba(59, 130, 246, 0.3); }
</style>
