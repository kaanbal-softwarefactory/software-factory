<template>
  <div class="space-y-5">
    <div class="flex justify-between gap-4 flex-wrap">
      <div>
        <router-link to="/hub" class="text-sm text-slate-400 hover:text-white">← Hub de agentes</router-link>
        <h1 class="text-3xl font-bold text-white mt-1">{{ project.name || group }}</h1>
        <p class="text-slate-400 mt-1">{{ project.description || 'Proyecto coordinado por agentes.' }}</p>
      </div>
      <div class="flex gap-2 self-start flex-wrap">
        <button class="glass-button" @click="refresh" :disabled="loading">Actualizar</button>
        <button v-if="can.digest" class="glass-button" @click="runDigest" :disabled="digesting">{{ digesting ? 'Resumiendo…' : 'Pedir resumen al secretario' }}</button>
      </div>
    </div>
    <p v-if="error" role="alert" class="text-red-300">{{ error }}</p>

    <!-- Equipo -->
    <div class="flex gap-3 overflow-x-auto pb-1">
      <div v-for="s in liveSessions" :key="s.id" class="glass-panel rounded-xl p-3 min-w-60 max-w-72 space-y-1">
        <div class="flex items-center gap-2">
          <span :class="['w-2.5 h-2.5 rounded-full', PRESENCE[s.presence].dot]" :title="PRESENCE[s.presence].label"></span>
          <span class="text-white font-medium truncate">{{ s.agent }}</span>
          <span :class="['text-[10px] border rounded-full px-2 ml-auto', harnessOf(s.harness).color]">{{ harnessOf(s.harness).label }}</span>
        </div>
        <p class="text-xs text-slate-400 truncate">{{ s.specialty || 'Sin especialidad' }} · {{ s.person }}</p>
        <p class="text-xs text-slate-300 line-clamp-2">{{ s.focus || '—' }}</p>
        <p class="text-xs text-cyan-300" v-if="s.task">Tarea {{ s.task }}<span v-if="s.branch" class="text-slate-500"> · {{ s.branch }}</span></p>
        <p class="text-[11px] text-slate-500">{{ PRESENCE[s.presence].label }} · {{ ago(s.last_seen) }}</p>
      </div>
      <p v-if="!liveSessions.length" class="text-sm text-slate-500 glass-panel rounded-xl p-3">Ningún agente conectado. Usa la pestaña Conectar para arrancar el primero.</p>
    </div>

    <div class="flex gap-1 border-b border-white/10 overflow-x-auto" role="tablist">
      <button v-for="t in tabs" :key="t.id" role="tab" :aria-selected="tab === t.id" @click="tab = t.id"
              :class="['px-4 py-2 text-sm whitespace-nowrap border-b-2 -mb-px', tab === t.id ? 'border-cyan-400 text-white' : 'border-transparent text-slate-400 hover:text-white']">
        {{ t.label }}<span v-if="t.badge" class="ml-1 text-xs text-slate-500">{{ t.badge }}</span>
      </button>
    </div>

    <!-- Primer paso: sin fuente todavía -->
    <section v-if="tab === 'summary' && starter && can.files" class="space-y-2">
      <h2 class="text-white font-semibold">Empieza aquí: sube las fases del proyecto</h2>
      <p class="text-sm text-slate-400">Los ZIP se descomprimen en fuente/ y son la fuente de los agentes. Si traen un kaanbal.hub.json, se ofrece importarlo como tareas.</p>
      <HubUploader :group="group" @uploaded="refresh" @import-plan="importPlan" />
    </section>

    <!-- Resumen -->
    <div v-if="tab === 'summary'" class="grid xl:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] gap-4">
      <div class="space-y-4">
        <section class="glass-panel p-5 rounded-xl">
          <div class="flex justify-between items-center mb-2">
            <h2 class="text-white font-semibold">Tablero</h2>
            <span class="text-xs text-slate-500" v-if="project.board_updated_by">{{ project.board_updated_by }} · {{ ago(project.board_updated_at) }}</span>
            <button v-if="can.participate && board === null" class="text-sm text-slate-300 hover:text-white" @click="board = project.board || ''">Editar</button>
          </div>
          <template v-if="board !== null">
            <textarea v-model="board" rows="14" class="field w-full font-mono text-xs" aria-label="Tablero"></textarea>
            <div class="flex justify-end gap-2 mt-2"><button class="glass-button" @click="board = null">Cancelar</button><button class="glass-button" @click="saveBoard">Guardar</button></div>
          </template>
          <div v-else-if="project.board" class="text-sm text-slate-300 space-y-1" v-html="renderMarkdown(project.board)"></div>
          <p v-else class="text-sm text-slate-500">Sin tablero. Se llena al importar el plan de fases, o lo escribe el primer agente.</p>
        </section>

        <section class="glass-panel p-5 rounded-xl">
          <h2 class="text-white font-semibold mb-3">Mapa de trabajo</h2>
          <p v-if="!tasks.length" class="text-sm text-slate-500">Sin tareas todavía. Sube las fases con su {{ 'kaanbal.hub.json' }} e impórtalo, o crea tareas a mano.</p>
          <div class="flex gap-3 overflow-x-auto pb-2">
            <div v-for="lane in lanes" :key="lane.phase" class="min-w-52 space-y-2">
              <div class="flex justify-between text-xs text-slate-400"><span class="font-semibold text-slate-200">{{ lane.phase }}</span><span>{{ lane.done }}/{{ lane.total }}</span></div>
              <div class="h-1.5 bg-slate-800 rounded"><div class="h-1.5 bg-emerald-400 rounded" :style="{ width: `${lane.total ? lane.done / lane.total * 100 : 0}%` }"></div></div>
              <button v-for="t in lane.tasks" :key="t.id" @click="focusTask = t; tab = 'tasks'"
                      :class="['w-full text-left text-xs border rounded-lg p-2 bg-slate-900/60 hover:bg-slate-800/60', STATUS[t.status].tone]">
                <span class="font-mono">{{ t.key || '•' }}</span> {{ t.title }}
                <span v-if="t.assignee_agent" class="block text-[10px] text-slate-400">{{ t.assignee_agent }}</span>
                <span v-if="t.waiting_on?.length" class="block text-[10px] text-red-300">espera {{ t.waiting_on.map(w => w.ref).join(', ') }}</span>
              </button>
            </div>
          </div>
        </section>
      </div>

      <div class="space-y-4">
        <section class="glass-panel p-5 rounded-xl">
          <h2 class="text-white font-semibold mb-2">Alertas</h2>
          <ul class="space-y-2 text-sm">
            <li v-for="a in signals.alerts || []" :key="a.kind + a.task" class="text-slate-300 flex gap-2"><span :class="alertTone[a.kind]">●</span>{{ a.text }}</li>
            <li v-for="q in signals.open_questions || []" :key="'q' + q.at" class="text-slate-300 flex gap-2"><span class="text-violet-300">?</span>{{ q.agent }}: {{ q.text }}</li>
          </ul>
          <p v-if="!(signals.alerts || []).length && !(signals.open_questions || []).length" class="text-sm text-slate-500">Nada pendiente de atención.</p>
          <p v-if="(signals.ready_to_start || []).length" class="text-xs text-slate-400 mt-3">Listas para empezar: {{ signals.ready_to_start.join(' · ') }}</p>
        </section>

        <section class="glass-panel p-5 rounded-xl space-y-2">
          <div class="flex justify-between items-center"><h2 class="text-white font-semibold">Secretario</h2>
            <span class="text-xs text-slate-500" v-if="digest">{{ digest.ai ? 'con IA' : 'sin IA' }} · {{ ago(digest.at) }}</span></div>
          <label v-if="can.digest" class="flex items-center gap-2 text-xs text-slate-400"><input type="checkbox" v-model="digestTasks" /> Dejar las tareas sugeridas como propuestas</label>
          <template v-if="digest">
            <p class="text-sm text-slate-200 whitespace-pre-wrap">{{ digest.summary || 'Resumen determinista: revisa alertas y avance por fase.' }}</p>
            <ul v-if="digest.risks?.length" class="list-disc pl-5 text-sm text-amber-200"><li v-for="r in digest.risks" :key="r">{{ r }}</li></ul>
            <ul v-if="digest.for_people?.length" class="list-disc pl-5 text-sm text-cyan-200"><li v-for="r in digest.for_people" :key="r">{{ r }}</li></ul>
            <ul v-if="digest.suggested_tasks?.length" class="text-sm text-slate-300 space-y-1"><li v-for="s in digest.suggested_tasks" :key="s.title">☐ {{ s.title }} <span class="text-slate-500">({{ s.area }})</span></li></ul>
          </template>
          <p v-else class="text-sm text-slate-500">Aún no hay resumen. El secretario solo informa y propone: no decide ni programa.</p>
        </section>

        <section class="glass-panel p-5 rounded-xl">
          <h2 class="text-white font-semibold mb-2">Actividad reciente</h2>
          <ul class="space-y-1.5 text-sm max-h-80 overflow-auto">
            <li v-for="e in events.slice(0, 25)" :key="e.id" class="text-slate-300"><span class="text-slate-500 text-xs">{{ ago(e.at) }}</span> <strong class="text-white">{{ e.agent || e.person }}</strong> <span class="text-slate-400">{{ KIND[e.kind] || e.kind }}</span> {{ e.text }}</li>
          </ul>
        </section>

        <section class="glass-panel p-5 rounded-xl" v-if="lessons.length">
          <h2 class="text-white font-semibold mb-2">Lecciones</h2>
          <ul class="space-y-1.5 text-sm"><li v-for="l in lessons" :key="l.text + l.at" class="text-slate-300"><span :class="l.scope === 'platform' ? 'text-cyan-300' : 'text-slate-500'">{{ l.scope === 'platform' ? 'Kaanbal' : 'Proyecto' }}</span> · {{ l.text }}</li></ul>
        </section>
      </div>
    </div>

    <!-- Tareas -->
    <div v-if="tab === 'tasks'" class="space-y-4">
      <div class="flex flex-wrap gap-3">
        <button v-if="can.participate" class="glass-button" @click="newTask = { title: '', key: '', area: '', phase: '', description: '', depends: '' }">Nueva tarea</button>
        <button v-if="can.files && files.has_plan" class="glass-button" @click="importPlan()">Reimportar plan</button>
        <input v-model="taskFilter" placeholder="Filtrar por texto, área o agente" class="field flex-1 min-w-56" aria-label="Filtrar tareas" />
      </div>
      <div class="flex gap-3 overflow-x-auto pb-2">
        <div v-for="col in columns" :key="col" class="min-w-64 w-64 shrink-0 space-y-2">
          <p :class="['text-sm font-semibold border-b pb-1', STATUS[col].tone]">{{ STATUS[col].label }} <span class="text-slate-500">{{ byStatus[col].length }}</span></p>
          <article v-for="t in byStatus[col]" :key="t.id" :class="['glass-panel rounded-lg p-3 space-y-1 text-sm', focusTask?.id === t.id ? 'ring-1 ring-cyan-400' : '']">
            <p class="text-white"><span class="font-mono text-cyan-300 text-xs">{{ t.key }}</span> {{ t.title }}</p>
            <p class="text-xs text-slate-500">{{ [t.area, t.phase].filter(Boolean).join(' · ') || 'sin área' }}</p>
            <p v-if="t.assignee_agent" class="text-xs text-slate-300">⟶ {{ t.assignee_agent }}</p>
            <p v-if="t.waiting_on?.length" class="text-xs text-red-300">Espera: {{ t.waiting_on.map(w => `${w.ref} (${w.status}${w.holder ? ', ' + w.holder : ''})`).join(', ') }}</p>
            <a v-if="t.pr_url" :href="t.pr_url" target="_blank" rel="noopener" class="text-xs text-cyan-300 break-all">{{ t.pr_url }}</a>
            <details v-if="t.description || t.notes.length" class="text-xs text-slate-400">
              <summary class="cursor-pointer">Detalle</summary>
              <p class="whitespace-pre-wrap mt-1">{{ t.description }}</p>
              <p v-for="n in t.notes" :key="n.at" class="mt-1"><strong>{{ n.by }}</strong>: {{ n.text }}</p>
            </details>
            <div v-if="can.participate" class="flex gap-2 pt-1">
              <button v-if="t.status === 'proposed'" class="text-xs text-emerald-300" @click="setStatus(t, 'todo')">Aceptar</button>
              <select class="field text-xs py-1 flex-1" :value="t.status" @change="setStatus(t, $event.target.value)" aria-label="Cambiar estado">
                <option v-for="s in Object.keys(STATUS)" :key="s" :value="s">{{ STATUS[s].label }}</option>
              </select>
            </div>
          </article>
        </div>
      </div>
    </div>

    <!-- Traza -->
    <div v-if="tab === 'trace'" class="grid lg:grid-cols-[18rem_minmax(0,1fr)] gap-4">
      <div class="glass-panel p-4 rounded-xl space-y-3 max-h-[70vh] overflow-auto">
        <p class="text-xs text-slate-500">Proyecto → día → agente</p>
        <button class="text-sm text-left w-full" :class="!traceFilter.day ? 'text-cyan-300' : 'text-slate-300'" @click="traceFilter = { day: '', agent: '', kind: traceFilter.kind }; loadTrace()">Todo</button>
        <div v-for="d in tree" :key="d.day">
          <button class="text-sm text-white w-full text-left flex justify-between" @click="traceFilter = { ...traceFilter, day: d.day, agent: '' }; loadTrace()"><span>{{ d.day }}</span><span class="text-slate-500">{{ d.events }}</span></button>
          <button v-for="a in d.agents" :key="a.agent" class="text-xs w-full text-left flex justify-between pl-3 py-0.5"
                  :class="traceFilter.day === d.day && traceFilter.agent === a.agent ? 'text-cyan-300' : 'text-slate-400 hover:text-white'"
                  @click="traceFilter = { ...traceFilter, day: d.day, agent: a.agent }; loadTrace()">
            <span>{{ a.agent }}</span><span>{{ a.events }}</span>
          </button>
        </div>
      </div>
      <div class="glass-panel p-4 rounded-xl space-y-3">
        <div class="flex flex-wrap gap-2">
          <select v-model="traceFilter.kind" @change="loadTrace" class="field text-sm" aria-label="Tipo de evento"><option value="">Todos los tipos</option><option v-for="(label, k) in KIND" :key="k" :value="k">{{ label }}</option></select>
          <span class="text-xs text-slate-500 self-center">{{ traceFilter.day || 'todos los días' }} · {{ traceFilter.agent || 'todos los agentes' }}</span>
        </div>
        <ol class="space-y-2 max-h-[62vh] overflow-auto">
          <li v-for="e in trace" :key="e.id" class="border-l-2 border-white/10 pl-3 text-sm">
            <p class="text-xs text-slate-500">{{ new Date(e.at + 'Z').toLocaleString() }} · <span :class="harnessOf(e.harness).color.split(' ').find(c => c.startsWith('text-'))">{{ e.agent || e.person }}</span> · {{ KIND[e.kind] || e.kind }}<span v-if="e.task"> · {{ e.task }}</span></p>
            <p class="text-slate-200 whitespace-pre-wrap">{{ e.text }}</p>
            <p v-if="e.refs?.length" class="text-xs text-cyan-300 break-all">{{ e.refs.join(' · ') }}</p>
          </li>
        </ol>
        <p v-if="!trace.length" class="text-sm text-slate-500">Sin eventos con estos filtros.</p>
      </div>
    </div>

    <HubFiles v-if="tab === 'files'" :group="group" :can-manage="can.files" @changed="refresh" @import-plan="importPlan" />

    <!-- Mensajes -->
    <div v-if="tab === 'messages'" class="grid lg:grid-cols-[minmax(0,1fr)_22rem] gap-4">
      <ol class="glass-panel p-4 rounded-xl space-y-2 max-h-[70vh] overflow-auto">
        <li v-for="m in messages" :key="m.id" class="text-sm"><p class="text-xs text-slate-500">{{ ago(m.at) }} · <strong class="text-slate-200">{{ m.from }}</strong> → {{ m.to }}<span v-if="m.task"> · {{ m.task }}</span> · leído por {{ m.read }}</p><p class="text-slate-200 whitespace-pre-wrap">{{ m.text }}</p></li>
        <li v-if="!messages.length" class="text-sm text-slate-500">Sin mensajes todavía.</li>
      </ol>
      <form v-if="can.participate" class="glass-panel p-4 rounded-xl space-y-3" @submit.prevent="sendMessage">
        <label class="block text-sm text-slate-300">Para
          <select v-model="draft.to" class="field w-full mt-1"><option value="all">Todos los agentes</option><option v-for="a in agentNames" :key="a" :value="a">{{ a }}</option><option value="people">Personas</option></select></label>
        <label class="block text-sm text-slate-300">Mensaje<textarea v-model="draft.text" rows="5" class="field w-full mt-1" required maxlength="4000"></textarea></label>
        <p class="text-xs text-slate-500">El agente lo recibe en su próximo hub_sync.</p>
        <button class="glass-button w-full" :disabled="!draft.text.trim()">Enviar</button>
      </form>
    </div>

    <HubConnect v-if="tab === 'connect'" :group="group" />

    <!-- Nueva tarea -->
    <div v-if="newTask" class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" @click.self="newTask = null">
      <form @submit.prevent="createTask" class="bg-slate-900 border border-white/10 rounded-2xl p-6 w-full max-w-lg space-y-3" role="dialog" aria-modal="true" aria-label="Nueva tarea">
        <h2 class="text-xl font-semibold text-white">Nueva tarea</h2>
        <label class="block text-sm text-slate-300">Título<input v-model="newTask.title" required maxlength="160" class="field w-full mt-1" /></label>
        <div class="grid grid-cols-3 gap-2">
          <label class="text-sm text-slate-300">Clave<input v-model="newTask.key" placeholder="T09" class="field w-full mt-1" /></label>
          <label class="text-sm text-slate-300">Área<input v-model="newTask.area" placeholder="frontend" class="field w-full mt-1" /></label>
          <label class="text-sm text-slate-300">Fase<input v-model="newTask.phase" placeholder="W2" class="field w-full mt-1" /></label>
        </div>
        <label class="block text-sm text-slate-300">Depende de (claves separadas por coma)<input v-model="newTask.depends" class="field w-full mt-1" /></label>
        <label class="block text-sm text-slate-300">Descripción y criterio de terminado<textarea v-model="newTask.description" rows="4" class="field w-full mt-1"></textarea></label>
        <p v-if="taskError" role="alert" class="text-red-300 text-sm">{{ taskError }}</p>
        <div class="flex justify-end gap-3"><button type="button" class="glass-button" @click="newTask = null">Cancelar</button><button class="glass-button">Crear</button></div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import api from '../services/api'
import HubFiles from '../components/hub/HubFiles.vue'
import HubConnect from '../components/hub/HubConnect.vue'
import HubUploader from '../components/hub/HubUploader.vue'
import { PRESENCE, STATUS, KIND, harnessOf, ago, detail, renderMarkdown } from '../components/hub/hubUi'

const route = useRoute()
const group = computed(() => route.params.group)
const project = ref({}), sessions = ref([]), tasks = ref([]), events = ref([]), signals = ref({}), files = ref({}), lessons = ref([])
const loading = ref(false), error = ref(''), tab = ref('summary'), board = ref(null)
const trace = ref([]), tree = ref([]), traceFilter = ref({ day: '', agent: '', kind: '' })
const messages = ref([]), draft = ref({ to: 'all', text: '' })
const newTask = ref(null), taskError = ref(''), taskFilter = ref(''), focusTask = ref(null)
const digesting = ref(false), digestTasks = ref(false)
const can = ref({ participate: false, files: false, digest: false })
// Se decide al abrir el proyecto: si se ocultara al llegar el primer archivo, cortaría la cola de subida.
const starter = ref(false)

const columns = ['proposed', 'todo', 'in_progress', 'blocked', 'review', 'done']
const alertTone = { orphan: 'text-amber-300', stale: 'text-amber-300', blocked: 'text-red-300', review: 'text-cyan-300', proposed: 'text-violet-300' }
const digest = computed(() => project.value.last_digest)
const liveSessions = computed(() => sessions.value.filter(s => s.presence !== 'left' && s.presence !== 'offline'))
const agentNames = computed(() => [...new Set(sessions.value.map(s => s.agent))])
const tabs = computed(() => [
  { id: 'summary', label: 'Resumen' },
  { id: 'tasks', label: 'Tareas', badge: tasks.value.filter(t => !['done', 'dropped'].includes(t.status)).length || '' },
  { id: 'trace', label: 'Traza' },
  { id: 'files', label: 'Archivos', badge: files.value.total || '' },
  { id: 'messages', label: 'Mensajes' },
  { id: 'connect', label: 'Conectar' },
])
const lanes = computed(() => {
  const map = new Map()
  for (const t of tasks.value.filter(t => !['dropped', 'proposed'].includes(t.status))) {
    const phase = t.phase || 'Sin fase'
    if (!map.has(phase)) map.set(phase, { phase, tasks: [], done: 0, total: 0 })
    const lane = map.get(phase); lane.tasks.push(t); lane.total++; if (t.status === 'done') lane.done++
  }
  return [...map.values()].sort((a, b) => a.phase.localeCompare(b.phase, undefined, { numeric: true }))
})
const byStatus = computed(() => {
  const needle = taskFilter.value.toLowerCase()
  const out = Object.fromEntries(columns.map(c => [c, []]))
  for (const t of tasks.value) {
    if (!out[t.status]) continue
    if (needle && !`${t.key} ${t.title} ${t.area} ${t.phase} ${t.assignee_agent || ''}`.toLowerCase().includes(needle)) continue
    out[t.status].push(t)
  }
  return out
})

async function refresh() {
  loading.value = true; error.value = ''
  try {
    const { data } = await api.get(`/hub/projects/${group.value}`)
    project.value = data.project; sessions.value = data.sessions; tasks.value = data.tasks
    events.value = data.events; signals.value = data.signals; files.value = data.files; lessons.value = data.lessons
    if (!loadedOnce) { starter.value = !data.files.total; loadedOnce = true }
  } catch (e) { error.value = detail(e, 'No se pudo cargar el proyecto.') }
  finally { loading.value = false }
  if (tab.value === 'messages') loadMessages()
}

async function loadTrace() {
  const params = { limit: 300, ...Object.fromEntries(Object.entries(traceFilter.value).filter(([, v]) => v)) }
  try {
    const [list, treeView] = await Promise.all([
      api.get(`/hub/projects/${group.value}/trace`, { params }),
      api.get(`/hub/projects/${group.value}/trace`, { params: { view: 'tree' } })])
    trace.value = list.data.events; tree.value = treeView.data.tree
  } catch (e) { error.value = detail(e, 'No se pudo cargar la traza.') }
}

async function loadMessages() {
  try { messages.value = (await api.get(`/hub/projects/${group.value}/messages`)).data.messages }
  catch (e) { error.value = detail(e, 'No se pudieron cargar los mensajes.') }
}

async function saveBoard() {
  try { await api.put(`/hub/projects/${group.value}/board`, { content: board.value }); board.value = null; await refresh() }
  catch (e) { error.value = detail(e, 'No se pudo guardar el tablero.') }
}

async function setStatus(t, status) {
  try { await api.patch(`/hub/tasks/${t.id}`, { status }); await refresh() }
  catch (e) { error.value = detail(e, 'No se pudo cambiar la tarea.') }
}

async function createTask() {
  taskError.value = ''
  const { depends, ...rest } = newTask.value
  const body = { ...rest, key: rest.key.trim() || null, depends_on: depends.split(',').map(s => s.trim()).filter(Boolean) }
  try { await api.post(`/hub/projects/${group.value}/tasks`, body); newTask.value = null; await refresh() }
  catch (e) { taskError.value = detail(e, 'No se pudo crear la tarea.') }
}

async function importPlan(path) {
  try {
    const { data } = await api.post(`/hub/projects/${group.value}/plan/import`, { path: path || null })
    alert(`Plan ${data.path}: ${data.created} tareas nuevas, ${data.updated} actualizadas${data.board_set ? ', tablero cargado' : ''}.`)
    await refresh(); tab.value = 'summary'
  } catch (e) { error.value = detail(e, 'No se pudo importar el plan.') }
}

async function runDigest() {
  digesting.value = true
  try { await api.post(`/hub/projects/${group.value}/digest`, { use_ai: true, create_tasks: digestTasks.value }); await refresh() }
  catch (e) { error.value = detail(e, 'El secretario no pudo resumir.') }
  finally { digesting.value = false }
}

async function sendMessage() {
  try { await api.post(`/hub/projects/${group.value}/messages`, draft.value); draft.value = { to: draft.value.to, text: '' }; await loadMessages() }
  catch (e) { error.value = detail(e, 'No se pudo enviar el mensaje.') }
}

async function loadPermissions() {
  try {
    const perms = new Set((await api.get('/security/me')).data.permissions || [])
    can.value = { participate: perms.has('hub.sessions.participate'), files: perms.has('hub.files.manage'), digest: perms.has('hub.digest.run') }
  } catch { can.value = { participate: false, files: false, digest: false } }
}

watch(tab, value => { if (value === 'trace') loadTrace(); if (value === 'messages') loadMessages() })
watch(group, () => { tab.value = 'summary'; loadedOnce = false; refresh() })
let timer = null, loadedOnce = false
onMounted(() => { refresh(); loadPermissions(); timer = setInterval(refresh, 15000) })
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .55rem .75rem; }
</style>
