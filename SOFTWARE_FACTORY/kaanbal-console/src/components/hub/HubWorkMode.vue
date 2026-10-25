<template>
  <section :class="['rounded-xl border p-4 flex flex-wrap items-center gap-4', autonomous ? 'border-emerald-400/30 bg-emerald-500/5' : 'border-white/10 bg-slate-900/40']">
    <div class="min-w-0 flex-1">
      <p class="text-sm">
        <span :class="['font-semibold', autonomous ? 'text-emerald-300' : 'text-slate-200']">{{ autonomous ? 'Modo autónomo' : 'Modo guiado' }}</span>
        <span class="text-slate-400"> · {{ autonomous ? 'los agentes toman y avanzan sin pedir aprobación' : 'los agentes proponen y esperan tu visto bueno' }} · cierra: {{ DONE_LABEL[settings.done_by] }}</span><span v-if="settings.integration === 'auto'" class="text-amber-200"> · integra a main solo</span>
      </p>
      <p v-if="objective.text || objective.total" class="text-sm text-white mt-1">
        Objetivo: {{ objective.text || scopeLabel }}
        <span class="text-slate-400">({{ objective.done }}/{{ objective.total }}{{ objective.complete ? ' · cumplido' : '' }})</span>
      </p>
      <div v-if="objective.total" class="h-1.5 bg-slate-800 rounded mt-2 max-w-md">
        <div :class="['h-1.5 rounded', objective.complete ? 'bg-emerald-400' : 'bg-cyan-400']" :style="{ width: `${objective.done / objective.total * 100}%` }"></div>
      </div>
      <p class="text-xs text-slate-400 mt-2">Alcance: {{ scopeLabel }} · {{ objective.ready || 0 }} listas · {{ objective.review || 0 }} por revisar</p>
      <p v-if="objective.external_dependencies?.length" class="text-xs text-amber-200 mt-2">Hay requisitos pendientes fuera del objetivo: {{ objective.external_dependencies.map(d => d.ref).join(', ') }}. Amplía el alcance o resuélvelos antes de continuar.</p>
      <div v-if="objective.complete" role="status" class="mt-3 rounded-lg border border-emerald-400/30 bg-emerald-400/10 p-3 text-sm text-emerald-100">
        <p class="font-medium">Objetivo cumplido: los agentes se detuvieron.</p>
        <p class="text-xs mt-1">Revisa y fusiona lo entregado; después elige el siguiente objetivo con «Cambiar modo».</p>
        <ul v-if="objective.deliveries?.length" class="text-xs mt-2 space-y-0.5">
          <li v-for="d in objective.deliveries" :key="d.task"><span class="font-mono">{{ d.task }}</span> · <a v-if="safeLink(d.pr_url)" :href="safeLink(d.pr_url)" target="_blank" rel="noopener" class="underline">PR</a><span v-else>rama {{ d.branch }}</span></li>
        </ul>
      </div>
      <p v-if="autonomous && !objective.total" class="text-xs text-amber-200 mt-2">El objetivo no incluye tareas activas. Revisa el alcance o acepta las propuestas pendientes.</p>
    </div>
    <button v-if="canManage" class="glass-button" @click="open">Cambiar modo</button>
  </section>

  <div v-if="form" class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" @click.self="close" @keydown.esc="close" @keydown.tab="trapFocus">
    <form @submit.prevent="save" class="bg-slate-900 border border-white/10 rounded-2xl p-6 w-full max-w-xl space-y-4 max-h-[90vh] overflow-auto" role="dialog" aria-modal="true" aria-label="Modo de trabajo">
      <h2 class="text-xl font-semibold text-white">Modo de trabajo del proyecto</h2>
      <div class="grid sm:grid-cols-2 gap-3">
        <label v-for="option in MODES" :key="option.value"
               :class="['rounded-xl border p-3 cursor-pointer', form.mode === option.value ? 'border-cyan-400 bg-cyan-500/10' : 'border-white/10']">
          <input type="radio" name="work-mode" :value="option.value" v-model="form.mode" @change="preset(option.value)" />
          <span class="text-white font-medium block">{{ option.title }}</span>
          <span class="text-xs text-slate-400">{{ option.text }}</span>
        </label>
      </div>

      <label class="block text-sm text-slate-300">Objetivo (qué tiene que quedar hecho)
        <input v-model="form.objective" maxlength="500" class="field w-full mt-1" placeholder="p. ej. Contratos y design system listos (W1)" />
      </label>
      <fieldset class="text-sm text-slate-300">
        <legend>Fases incluidas <span class="text-slate-500">(se suman a las tareas elegidas abajo)</span></legend>
        <div class="flex flex-wrap gap-2 mt-2">
          <label v-for="phase in phases" :key="phase" :class="['px-3 py-1 rounded-full border cursor-pointer', form.scope_phases.includes(phase) ? 'border-cyan-400 text-cyan-200' : 'border-white/10 text-slate-400']">
            <input type="checkbox" :value="phase" v-model="form.scope_phases" class="mr-2" />{{ phase }}
          </label>
          <span v-if="!phases.length" class="text-slate-500">Todavía no hay fases en las tareas.</span>
        </div>
      </fieldset>
      <label class="block text-sm text-slate-300">Tareas sueltas del objetivo (claves separadas por coma)
        <input v-model="form.tasks" class="field w-full mt-1" placeholder="T03, T04" />
      </label>
      <section class="rounded-xl border border-cyan-400/20 bg-cyan-400/5 p-4 space-y-2" aria-label="Vista previa del objetivo">
        <h3 class="text-sm text-white font-medium">{{ preview.scoped.length }} tareas incluidas <span class="text-slate-400 font-normal">· {{ preview.done }} hechas · {{ preview.ready }} listas</span></h3>
        <p class="text-xs text-slate-400">{{ !form.scope_phases.length && !scopeKeys.length ? 'Sin fases ni tareas seleccionadas: incluye todo el proyecto, también las futuras tareas.' : 'Se incluyen las tareas de cualquiera de las fases y las claves indicadas.' }}</p>
        <p v-if="preview.unknown.length" role="alert" class="text-xs text-red-300">Claves no encontradas: {{ preview.unknown.join(', ') }}</p>
        <p v-if="preview.external.length" class="text-xs text-amber-200">Dependen de trabajo fuera del objetivo: {{ preview.external.join(', ') }}. No se incluirá automáticamente.</p>
        <div class="flex flex-wrap gap-1 max-h-28 overflow-auto"><span v-for="t in preview.scoped" :key="t.id" class="rounded bg-slate-900 px-2 py-1 text-[11px] text-slate-300">{{ t.key || t.title }} · {{ STATUS[t.status]?.label }}</span></div>
      </section>
      <label class="block text-sm text-slate-300">Quién cierra las tareas
        <select v-model="form.done_by" class="field w-full mt-1" :disabled="form.mode === 'guided'">
          <option value="person">Una persona (los agentes las dejan en revisión)</option>
          <option value="peer">Otro agente (revisión cruzada: Codex revisa a Claude y viceversa)</option>
          <option value="self">El mismo agente (al abrir su PR con pruebas)</option>
        </select>
      </label>
      <label class="flex items-start gap-2 text-sm text-slate-300">
        <input type="checkbox" v-model="form.auto_accept" class="mt-1" :disabled="form.mode === 'guided'" />
        <span>Aceptar solas las tareas que propongan los agentes dentro del objetivo</span>
      </label>
      <fieldset class="rounded-xl border border-white/10 p-3 space-y-2 text-sm text-slate-300">
        <legend class="px-1">Integración a main</legend>
        <label class="flex items-start gap-2"><input type="radio" value="manual" v-model="form.integration" class="mt-1" :disabled="!canIntegrate" />
          <span>Manual: las personas revisan y fusionan cada entrega.</span></label>
        <label class="flex items-start gap-2"><input type="radio" value="auto" v-model="form.integration" class="mt-1" :disabled="!canIntegrate || form.done_by === 'self'" />
          <span>Automática: cuando otro agente o una persona cierra una tarea con rama, Kaanbal la fusiona en main si sus checks están en verde y sigue el despliegue en Argo. <strong class="text-amber-200">Despliega sin intervención humana:</strong> pensada para proyectos en prueba.</span></label>
        <div v-if="form.integration === 'auto'" class="pl-6 space-y-2">
          <label class="flex items-center gap-2"><input type="checkbox" v-model="form.require_checks" :disabled="!canIntegrate" /> Exigir checks de CI en la rama (recomendado)</label>
          <label class="block text-xs text-slate-400">App que recibe las integraciones (vacío si el grupo tiene una sola)
            <input v-model="form.integration_app" maxlength="63" class="field w-full mt-1" :disabled="!canIntegrate" /></label>
        </div>
        <p v-if="!canIntegrate" class="text-xs text-slate-500">Cambiarla exige el permiso hub.integration.manage.</p>
      </fieldset>
      <p class="text-xs text-slate-500">{{ form.integration === 'auto' ? 'Lo revisado y en verde llega a main solo; lo demás vuelve a la tarea como bloqueo con el motivo.' : 'Fusionar a main (y desplegar) queda en manos de personas; también pueden pedir «Integrar a main» desde el detalle de una tarea cerrada.' }} Los agentes se detienen al cumplir el objetivo.</p>
      <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
      <div class="flex justify-end gap-3"><button type="button" class="glass-button" :disabled="saving" @click="close">Cancelar</button><button class="glass-button" :disabled="saving || preview.unknown.length > 0">{{ saving ? 'Guardando…' : 'Guardar modo y objetivo' }}</button></div>
    </form>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from 'vue'
import api from '../../services/api'
import { detail, inScope, safeLink, STATUS } from './hubUi'

const props = defineProps({
  group: { type: String, required: true },
  settings: { type: Object, default: () => ({ mode: 'guided', done_by: 'person', auto_accept: false, scope_phases: [], scope_tasks: [] }) },
  objective: { type: Object, default: () => ({ done: 0, total: 0, complete: false, text: '' }) },
  phases: { type: Array, default: () => [] },
  tasks: { type: Array, default: () => [] },
  canManage: Boolean,
  canIntegrate: Boolean,
})
const emit = defineEmits(['saved'])

const MODES = [
  { value: 'guided', title: 'Guiado', text: 'Los agentes proponen y esperan tu visto bueno; tú cierras cada tarea.' },
  { value: 'autonomous', title: 'Autónomo hasta el objetivo', text: 'Toman, hacen y cierran tareas solos hasta cumplir el objetivo; te avisan con preguntas en la traza.' },
]
const DONE_LABEL = { person: 'una persona', peer: 'otro agente', self: 'el mismo agente' }
const form = ref(null), saving = ref(false), error = ref('')
const autonomous = computed(() => props.settings.mode === 'autonomous')
const scopeLabel = computed(() => [...(props.objective.phases || []), ...(props.objective.tasks || [])].join(', ') || 'todo el proyecto')
const scopeKeys = computed(() => (form.value?.tasks || '').split(',').map(t => t.trim()).filter(Boolean))
const preview = computed(() => {
  const settings = { scope_phases: form.value?.scope_phases || [], scope_tasks: scopeKeys.value }
  const scoped = props.tasks.filter(t => inScope(t, settings) && !['proposed', 'dropped'].includes(t.status))
  const refs = new Set(scoped.flatMap(t => [t.key, t.id]))
  const external = [...new Set(scoped.filter(t => t.status !== 'done').flatMap(t => (t.waiting_on || []).map(d => d.ref)).filter(key => !refs.has(key)))]
  return { scoped, external, done: scoped.filter(t => t.status === 'done').length,
    ready: scoped.filter(t => t.status === 'todo' && !t.waiting_on?.length).length,
    unknown: scopeKeys.value.filter(key => !props.tasks.some(t => t.key === key)) }
})
let opener
function close() { if (saving.value) return; form.value = null; nextTick(() => opener?.focus()) }
function trapFocus(event) {
  const nodes = [...event.currentTarget.querySelectorAll('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled)')]
  if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault(); nodes.at(-1)?.focus() }
  else if (!event.shiftKey && document.activeElement === nodes.at(-1)) { event.preventDefault(); nodes[0]?.focus() }
}

function open() {
  opener = document.activeElement
  const s = props.settings
  form.value = { mode: s.mode, done_by: s.done_by, auto_accept: s.auto_accept, objective: s.objective || '',
    scope_phases: [...(s.scope_phases || [])], tasks: (s.scope_tasks || []).join(', '),
    integration: s.integration || 'manual', require_checks: s.require_checks !== false, integration_app: s.integration_app || '' }
  error.value = ''
  nextTick(() => document.querySelector('[aria-label="Modo de trabajo"] input')?.focus())
}
// Valores sensatos al cambiar de modo; se pueden ajustar antes de guardar.
function preset(mode) {
  if (mode === 'autonomous') Object.assign(form.value, { done_by: form.value.done_by === 'person' ? 'peer' : form.value.done_by, auto_accept: true })
  else Object.assign(form.value, { done_by: 'person', auto_accept: false })
}
async function save() {
  saving.value = true; error.value = ''
  const { tasks, ...rest } = form.value
  try {
    await api.put(`/hub/projects/${props.group}/settings`, { ...rest, scope_tasks: tasks.split(',').map(t => t.trim()).filter(Boolean) })
    form.value = null; nextTick(() => opener?.focus()); emit('saved')
  } catch (e) { error.value = detail(e, 'No se pudo guardar el modo de trabajo.') }
  finally { saving.value = false }
}
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .55rem .75rem; }
</style>
