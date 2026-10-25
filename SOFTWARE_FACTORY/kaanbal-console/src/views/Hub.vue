<template>
  <div class="space-y-6">
    <div class="flex justify-between gap-4 flex-wrap">
      <div>
        <h1 class="text-3xl font-bold text-white">Hub de agentes</h1>
        <p class="text-slate-400 mt-2">Dónde se coordinan Codex, Claude, Cursor y ChatGPT cuando trabajan en el mismo proyecto.</p>
        <p class="text-xs text-slate-500 mt-1">Cada proyecto es un grupo de Kaanbal. Los agentes se conectan por el MCP con las herramientas <code>hub_*</code>.</p>
      </div>
      <router-link to="/systems" class="glass-button self-start">Grupos y responsables</router-link>
    </div>

    <ol class="grid md:grid-cols-5 gap-3 text-sm">
      <li v-for="(step, i) in cycle" :key="step.title" class="glass-panel p-4 rounded-xl">
        <span class="text-cyan-300 font-mono text-xs">{{ i + 1 }}</span>
        <p class="text-white font-medium mt-1">{{ step.title }}</p>
        <p class="text-slate-400 text-xs mt-1">{{ step.text }}</p>
      </li>
    </ol>

    <p v-if="error" role="alert" class="text-red-300">{{ error }}</p>
    <div class="flex flex-wrap gap-3">
      <input v-model="search" placeholder="Buscar proyecto" aria-label="Buscar proyecto" class="field flex-1 min-w-56" />
      <label class="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" v-model="onlyActive" /> Solo con agentes en línea</label>
      <button class="glass-button" @click="load" :disabled="loading">Actualizar</button>
    </div>

    <p v-if="loading && !projects.length" class="text-slate-400">Cargando proyectos…</p>
    <p v-else-if="!filtered.length" class="glass-panel p-8 text-slate-400">
      No hay proyectos que coincidan. Crea un grupo en <router-link to="/systems" class="text-cyan-300">Sistemas</router-link> y ábrelo aquí.
    </p>
    <div class="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
      <router-link v-for="p in filtered" :key="p.group" :to="`/hub/${p.group}`"
                   class="glass-panel p-5 rounded-2xl space-y-3 hover:border-cyan-400/40 border border-transparent transition">
        <div class="flex justify-between gap-3">
          <div>
            <h2 class="text-lg font-semibold text-white">{{ p.name }}</h2>
            <span class="text-xs text-slate-500 font-mono">{{ p.group }}</span>
          </div>
          <span class="text-xs text-slate-400">{{ ago(p.last_activity) }}</span>
        </div>
        <p class="text-sm text-slate-400 line-clamp-2">{{ p.description || 'Sin descripción' }}</p>
        <div class="flex flex-wrap gap-2 min-h-7">
          <span v-for="a in p.agents_online" :key="a.id" :class="['text-xs border rounded-full px-2 py-1 flex items-center gap-1', harnessOf(a.harness).color]">
            <span :class="['w-2 h-2 rounded-full', PRESENCE[a.presence].dot]"></span>{{ a.agent }}
          </span>
          <span v-if="!p.agents_online.length" class="text-xs text-slate-500">Sin agentes en línea</span>
        </div>
        <div class="flex gap-4 text-sm">
          <span class="text-slate-300"><strong class="text-white">{{ p.open_tasks }}</strong> abiertas</span>
          <span v-if="p.blocked_tasks" class="text-red-300"><strong>{{ p.blocked_tasks }}</strong> bloqueadas</span>
          <span v-if="!p.in_hub" class="text-slate-500">Aún sin actividad</span>
        </div>
      </router-link>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import api from '../services/api'
import { PRESENCE, harnessOf, ago, detail } from '../components/hub/hubUi'

const projects = ref([]), loading = ref(false), error = ref(''), search = ref(''), onlyActive = ref(false)
const cycle = [
  { title: 'Idea y fases', text: 'Con ChatGPT web se arman las fases: imágenes, instrucciones y un plan (prompt en Conectar).' },
  { title: 'Fuente', text: 'La persona sube el ZIP al proyecto: Kaanbal lo descomprime en fuente/ e importa el plan.' },
  { title: 'Agentes', text: 'Cada agente entra con hub_join, toma tareas y deja traza; se coordinan por mensajes.' },
  { title: 'Pruebas', text: 'La persona prueba lo entregado, acepta propuestas y pide ajustes o fases nuevas.' },
  { title: 'Lecciones', text: 'Lo aprendido queda para este y otros proyectos; el secretario resume el estado.' },
]
const filtered = computed(() => projects.value.filter(p =>
  (!onlyActive.value || p.agents_online.length) &&
  `${p.name} ${p.group}`.toLowerCase().includes(search.value.toLowerCase())))

let timer = null
async function load() {
  loading.value = true; error.value = ''
  try { projects.value = (await api.get('/hub/projects')).data.projects }
  catch (e) { error.value = detail(e, 'No se pudieron cargar los proyectos del Hub.') }
  finally { loading.value = false }
}
onMounted(() => { load(); timer = setInterval(load, 20000) })
onBeforeUnmount(() => clearInterval(timer))
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .65rem .8rem; }
</style>
