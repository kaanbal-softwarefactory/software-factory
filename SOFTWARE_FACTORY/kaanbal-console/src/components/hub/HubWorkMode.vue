<template>
  <section :class="['rounded-xl border p-4 flex flex-wrap items-center gap-4', autonomous ? 'border-emerald-400/30 bg-emerald-500/5' : 'border-white/10 bg-slate-900/40']">
    <div class="min-w-0 flex-1">
      <p class="text-sm">
        <span :class="['font-semibold', autonomous ? 'text-emerald-300' : 'text-slate-200']">{{ autonomous ? 'Modo autónomo' : 'Modo guiado' }}</span>
        <span class="text-slate-400"> · {{ autonomous ? 'los agentes toman y avanzan sin pedir aprobación' : 'los agentes proponen y esperan tu visto bueno' }} · cierra: {{ DONE_LABEL[settings.done_by] }}</span>
      </p>
      <p v-if="objective.text || objective.total" class="text-sm text-white mt-1 truncate">
        Objetivo: {{ objective.text || scopeLabel }}
        <span class="text-slate-400">({{ objective.done }}/{{ objective.total }}{{ objective.complete ? ' · cumplido' : '' }})</span>
      </p>
      <div v-if="objective.total" class="h-1.5 bg-slate-800 rounded mt-2 max-w-md">
        <div :class="['h-1.5 rounded', objective.complete ? 'bg-emerald-400' : 'bg-cyan-400']" :style="{ width: `${objective.done / objective.total * 100}%` }"></div>
      </div>
    </div>
    <button v-if="canManage" class="glass-button" @click="open">Cambiar modo</button>
  </section>

  <div v-if="form" class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" @click.self="form = null">
    <form @submit.prevent="save" class="bg-slate-900 border border-white/10 rounded-2xl p-6 w-full max-w-xl space-y-4 max-h-[90vh] overflow-auto" role="dialog" aria-modal="true" aria-label="Modo de trabajo">
      <h2 class="text-xl font-semibold text-white">Modo de trabajo del proyecto</h2>
      <div class="grid sm:grid-cols-2 gap-3">
        <label v-for="option in MODES" :key="option.value"
               :class="['rounded-xl border p-3 cursor-pointer', form.mode === option.value ? 'border-cyan-400 bg-cyan-500/10' : 'border-white/10']">
          <input type="radio" class="sr-only" :value="option.value" v-model="form.mode" @change="preset(option.value)" />
          <span class="text-white font-medium block">{{ option.title }}</span>
          <span class="text-xs text-slate-400">{{ option.text }}</span>
        </label>
      </div>

      <label class="block text-sm text-slate-300">Objetivo (qué tiene que quedar hecho)
        <input v-model="form.objective" maxlength="500" class="field w-full mt-1" placeholder="p. ej. Contratos y design system listos (W1)" />
      </label>
      <fieldset class="text-sm text-slate-300">
        <legend>Alcance: fases del objetivo <span class="text-slate-500">(ninguna = todo el proyecto)</span></legend>
        <div class="flex flex-wrap gap-2 mt-2">
          <label v-for="phase in phases" :key="phase" :class="['px-3 py-1 rounded-full border cursor-pointer', form.scope_phases.includes(phase) ? 'border-cyan-400 text-cyan-200' : 'border-white/10 text-slate-400']">
            <input type="checkbox" class="sr-only" :value="phase" v-model="form.scope_phases" />{{ phase }}
          </label>
          <span v-if="!phases.length" class="text-slate-500">Todavía no hay fases en las tareas.</span>
        </div>
      </fieldset>
      <label class="block text-sm text-slate-300">Tareas sueltas del objetivo (claves separadas por coma)
        <input v-model="form.tasks" class="field w-full mt-1" placeholder="T03, T04" />
      </label>
      <label class="block text-sm text-slate-300">Quién cierra las tareas
        <select v-model="form.done_by" class="field w-full mt-1">
          <option value="person">Una persona (los agentes las dejan en revisión)</option>
          <option value="peer">Otro agente (revisión cruzada: Codex revisa a Claude y viceversa)</option>
          <option value="self">El mismo agente (al abrir su PR con pruebas)</option>
        </select>
      </label>
      <label class="flex items-start gap-2 text-sm text-slate-300">
        <input type="checkbox" v-model="form.auto_accept" class="mt-1" />
        <span>Aceptar solas las tareas que propongan los agentes dentro del objetivo</span>
      </label>
      <p class="text-xs text-slate-500">En cualquier modo, fusionar a main (y desplegar) sigue siendo de personas. Los agentes abren un PR por tarea y se detienen al cumplir el objetivo.</p>
      <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
      <div class="flex justify-end gap-3"><button type="button" class="glass-button" @click="form = null">Cancelar</button><button class="glass-button" :disabled="saving">{{ saving ? 'Guardando…' : 'Guardar' }}</button></div>
    </form>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import api from '../../services/api'
import { detail } from './hubUi'

const props = defineProps({
  group: { type: String, required: true },
  settings: { type: Object, default: () => ({ mode: 'guided', done_by: 'person', auto_accept: false, scope_phases: [], scope_tasks: [] }) },
  objective: { type: Object, default: () => ({ done: 0, total: 0, complete: false, text: '' }) },
  phases: { type: Array, default: () => [] },
  canManage: Boolean,
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

function open() {
  const s = props.settings
  form.value = { mode: s.mode, done_by: s.done_by, auto_accept: s.auto_accept, objective: s.objective || '',
    scope_phases: [...(s.scope_phases || [])], tasks: (s.scope_tasks || []).join(', ') }
  error.value = ''
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
    form.value = null; emit('saved')
  } catch (e) { error.value = detail(e, 'No se pudo guardar el modo de trabajo.') }
  finally { saving.value = false }
}
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .55rem .75rem; }
</style>
