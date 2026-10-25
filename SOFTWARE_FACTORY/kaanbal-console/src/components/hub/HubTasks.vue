<template>
  <section class="space-y-4" aria-label="Gestión de tareas">
    <div class="glass-panel rounded-xl p-4 space-y-3">
      <div class="flex flex-wrap items-center gap-3">
        <input v-model="search" class="field flex-1 min-w-48" aria-label="Buscar tareas" placeholder="Buscar por clave, título, área o agente…" />
        <select v-model="phase" class="field" aria-label="Filtrar por fase"><option value="">Todas las fases</option><option v-for="p in phases" :key="p">{{ p }}</option></select>
        <select v-model="agent" class="field" aria-label="Filtrar por agente"><option value="">Todos los agentes</option><option value="unassigned">Sin asignar</option><option v-for="a in agents" :key="a">{{ a }}</option></select>
        <label v-if="settings.mode === 'autonomous'" class="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" v-model="scopeOnly" /> Solo el objetivo</label>
      </div>
      <div class="flex flex-wrap gap-2" aria-label="Filtrar por estado">
        <button v-for="f in filters" :key="f.key" @click="filter = f.key" :aria-pressed="filter === f.key"
          :class="['rounded-lg px-3 py-2 text-xs border transition', filter === f.key ? 'border-cyan-400 bg-cyan-400/10 text-cyan-200' : 'border-white/10 text-slate-400 hover:text-white']">{{ f.label }} <span class="ml-1 tabular-nums">{{ count(f.key) }}</span></button>
      </div>
    </div>
    <p class="text-xs text-slate-400">{{ filtered.length }} de {{ tasks.length }} tareas · Selecciona una tarea para revisar su entrega o ver qué la bloquea.</p>
    <div class="grid xl:grid-cols-[minmax(0,1fr)_minmax(20rem,.85fr)] gap-4 items-start">
      <div class="space-y-2">
        <button v-for="t in filtered" :key="t.id" @click="select(t)" :aria-pressed="selected?.id === t.id"
          :class="['w-full text-left rounded-xl border p-4 transition', selected?.id === t.id ? 'border-cyan-400/70 bg-cyan-400/5' : 'border-white/10 bg-slate-900/40 hover:border-slate-500']">
          <div class="flex flex-wrap justify-between gap-2 items-start">
            <span class="text-white text-sm font-medium"><span class="font-mono text-xs text-cyan-300 mr-2">{{ t.key || 'Sin clave' }}</span>{{ t.title }}</span>
            <span :class="['text-[11px] rounded-full border px-2 py-0.5', STATUS[t.status]?.tone]">{{ STATUS[t.status]?.label }}</span>
          </div>
          <p class="text-xs text-slate-400 mt-2">{{ [t.phase, t.area, t.assignee_agent || 'Sin asignar'].filter(Boolean).join(' · ') }}</p>
          <p v-if="waiting(t)" class="text-xs text-amber-200 mt-2">Espera {{ t.waiting_on.map(w => w.ref).join(', ') }}</p>
          <p v-else-if="t.status === 'todo'" class="text-xs text-emerald-300 mt-2">Lista para empezar</p>
          <p v-if="!inScope(t, settings) && settings.mode === 'autonomous'" class="text-xs text-slate-500 mt-1">Fuera del objetivo actual</p>
        </button>
        <div v-if="!filtered.length" class="glass-panel rounded-xl p-8 text-center">
          <p class="text-white">No hay tareas con estos filtros.</p>
          <button class="text-cyan-300 text-sm mt-3" @click="reset">Limpiar filtros</button>
        </div>
      </div>
      <section v-if="selected" class="glass-panel rounded-xl p-5 space-y-4 xl:sticky xl:top-4" aria-label="Detalle de tarea" ref="detailPanel" tabindex="-1">
        <div class="flex justify-between gap-3"><div><p class="text-xs text-cyan-300 font-mono">{{ selected.key || 'Tarea' }} · {{ selected.phase || 'Sin fase' }}</p><h2 class="text-lg text-white font-semibold mt-1">{{ selected.title }}</h2></div><button @click="selectedId = null" class="text-slate-400 self-start" aria-label="Cerrar detalle">✕</button></div>
        <p class="text-sm text-slate-300 whitespace-pre-wrap">{{ selected.description || 'Sin descripción ni criterios de aceptación.' }}</p>
        <dl class="grid grid-cols-2 gap-3 text-xs"><div><dt class="text-slate-500">Responsable</dt><dd class="text-white mt-1">{{ selected.assignee_agent || 'Sin asignar' }}</dd></div><div><dt class="text-slate-500">Último cambio</dt><dd class="text-white mt-1">{{ ago(selected.updated_at) }}</dd></div></dl>
        <div v-if="selected.depends_on?.length" class="rounded-lg bg-slate-950/50 p-3">
          <h3 class="text-xs text-slate-400 mb-2">Depende de</h3>
          <button v-for="key in selected.depends_on" :key="key" @click="openDependency(key)" class="block text-left text-sm text-cyan-200 py-1">{{ key }} · {{ dependencyLabel(key) }}</button>
        </div>
        <p v-if="selected.branch" class="text-xs text-slate-400 break-all">Rama: <code>{{ selected.branch }}</code></p>
        <a v-if="safeLink(selected.pr_url)" :href="safeLink(selected.pr_url)" target="_blank" rel="noopener" class="inline-block text-sm text-cyan-300 underline">Abrir pull request ↗</a>
        <p v-if="selected.reviewed_by" class="text-xs text-emerald-300">Cerrada por {{ selected.reviewed_by }} · {{ ago(selected.reviewed_at) }}</p>
        <div v-if="selected.sources?.length" class="text-xs text-slate-400"><p class="mb-1">Documentos de referencia</p><p v-for="s in selected.sources" :key="s" class="font-mono break-all">{{ s }}</p></div>
        <div v-if="canEdit" class="border-t border-white/10 pt-4 space-y-3">
          <p v-if="selected.status === 'review'" class="text-sm text-amber-200">Revisa el PR y las pruebas antes de cerrar. Puedes devolverla con una nota si necesita cambios.</p>
          <label class="block text-xs text-slate-400">Nota de revisión o seguimiento<textarea v-model="note" rows="3" maxlength="2000" class="field w-full mt-1" placeholder="Qué se verificó, qué falta o cómo continuar…"></textarea></label>
          <div class="flex gap-2 flex-wrap">
            <button v-if="selected.status === 'proposed'" class="glass-button" :disabled="busy" @click="update('todo')">Aceptar propuesta</button>
            <template v-if="selected.status === 'review'"><button class="glass-button text-emerald-300" :disabled="busy || waiting(selected)" @click="update('done')">Aprobar y cerrar</button><button class="glass-button" :disabled="busy || !note.trim()" @click="update('todo')">Pedir cambios</button></template>
            <button class="glass-button" :disabled="busy || !note.trim()" @click="update(null)">Guardar nota</button>
          </div>
          <label class="block text-xs text-slate-400">Cambiar estado<select class="field w-full mt-1" :value="selected.status" :disabled="busy" @change="update($event.target.value)"><option v-for="(s, key) in STATUS" :key="key" :value="key" :disabled="waiting(selected) && ['done', 'review', 'in_progress'].includes(key)">{{ s.label }}</option></select></label>
          <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
          <p v-if="saved" role="status" class="text-xs text-emerald-300">{{ saved }}</p>
        </div>
        <div v-if="selected.notes?.length" class="space-y-2 border-t border-white/10 pt-3"><h3 class="text-xs text-slate-400">Seguimiento</h3><div v-for="(n, i) in [...selected.notes].reverse()" :key="i" class="text-xs rounded-lg bg-slate-950/50 p-3"><p class="text-slate-500">{{ n.by }} · {{ ago(n.at) }}</p><p class="text-slate-200 whitespace-pre-wrap mt-1">{{ n.text }}</p></div></div>
      </section>
      <div v-else class="hidden xl:block border border-dashed border-white/10 rounded-xl p-10 text-center text-sm text-slate-500">Selecciona una tarea.<br />Aquí verás sus dependencias, entrega y seguimiento.</div>
    </div>
  </section>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import api from '../../services/api'
import { STATUS, ago, detail, inScope, safeLink } from './hubUi'
const props = defineProps({ tasks: { type: Array, default: () => [] }, settings: { type: Object, default: () => ({}) }, focusTask: Object, initialFilter: String, canEdit: Boolean })
const emit = defineEmits(['changed'])
const search = ref(''), phase = ref(''), agent = ref(''), filter = ref(props.initialFilter || 'open'), scopeOnly = ref(false)
const selectedId = ref(props.focusTask?.id || null), note = ref(''), error = ref(''), busy = ref(false), saved = ref(''), detailPanel = ref(null)
const selected = computed(() => props.tasks.find(t => t.id === selectedId.value))
const phases = computed(() => [...new Set(props.tasks.map(t => t.phase).filter(Boolean))].sort())
const agents = computed(() => [...new Set(props.tasks.map(t => t.assignee_agent).filter(Boolean))].sort())
const waiting = t => !['done', 'dropped'].includes(t.status) && !!t.waiting_on?.length
const filters = [{ key: 'open', label: 'Abiertas' }, { key: 'ready', label: 'Listas' }, { key: 'waiting', label: 'Bloqueadas' }, { key: 'in_progress', label: 'En curso' }, { key: 'review', label: 'Por revisar' }, { key: 'proposed', label: 'Propuestas' }, { key: 'done', label: 'Hechas' }, { key: 'all', label: 'Todas' }]
const matches = (t, key) => key === 'all' || (key === 'open' ? !['done', 'dropped'].includes(t.status) : key === 'ready' ? t.status === 'todo' && !waiting(t) : key === 'waiting' ? t.status === 'blocked' || waiting(t) : t.status === key)
const base = computed(() => props.tasks.filter(t => (!phase.value || t.phase === phase.value) && (!agent.value || (agent.value === 'unassigned' ? !t.assignee_agent : t.assignee_agent === agent.value)) && (props.settings.mode !== 'autonomous' || !scopeOnly.value || inScope(t, props.settings)) && `${t.key || ''} ${t.title} ${t.area} ${t.assignee_agent || ''}`.toLocaleLowerCase().includes(search.value.toLocaleLowerCase())))
const filtered = computed(() => base.value.filter(t => matches(t, filter.value)))
const count = key => base.value.filter(t => matches(t, key)).length
function reset() { search.value = ''; phase.value = ''; agent.value = ''; scopeOnly.value = false; filter.value = 'all' }
async function select(t) { selectedId.value = t.id; await nextTick(); detailPanel.value?.focus({ preventScroll: true }); if (window.innerWidth < 1280) detailPanel.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }
function openDependency(key) { const t = props.tasks.find(t => t.key === key || t.id === key); if (t) select(t) }
function dependencyLabel(key) { const t = props.tasks.find(t => t.key === key || t.id === key); return t ? `${STATUS[t.status]?.label} · ${t.title}` : 'No encontrada' }
watch(() => props.focusTask, t => { if (t) { reset(); select(t) } })
watch(() => props.initialFilter, value => { if (value) filter.value = value })
watch(selectedId, () => { note.value = ''; error.value = ''; saved.value = '' })
async function update(status) {
  if (busy.value) return
  busy.value = true; error.value = ''; saved.value = ''
  try { await api.patch(`/hub/tasks/${selected.value.id}`, { ...(status ? { status } : {}), note: note.value }); note.value = ''; saved.value = 'Cambio guardado.'; emit('changed') }
  catch (e) { error.value = detail(e, 'No se pudo guardar. Actualiza e inténtalo de nuevo.') }
  finally { busy.value = false }
}
</script>
<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .55rem .75rem; }
button:focus-visible, select:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid #22d3ee; outline-offset: 3px; }
</style>

