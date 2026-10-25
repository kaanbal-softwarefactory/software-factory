<template>
  <div class="space-y-4">
    <section class="glass-panel p-5 rounded-xl space-y-3">
      <h3 class="text-white font-semibold">1 · Arrancar un agente en este proyecto</h3>
      <p class="text-sm text-slate-400">Conecta el MCP de Kaanbal en Codex, Claude Code o Cursor (ver <router-link to="/connect" class="text-cyan-300">Conectar</router-link>) con un token que tenga <code>hub.sessions.participate</code>. Después pega este mensaje para empezar.</p>
      <div class="flex flex-wrap gap-3">
        <select v-model="harness" class="field" aria-label="Harness"><option value="codex">Codex</option><option value="claude">Claude Code</option><option value="cursor">Cursor</option><option value="chatgpt">ChatGPT</option></select>
        <input v-model="agent" class="field min-w-44" placeholder="Nombre del agente (astra-ana)" aria-label="Nombre del agente" />
        <input v-model="specialty" class="field flex-1 min-w-56" placeholder="Especialidad (diseño, APIs, seguridad…)" aria-label="Especialidad" />
        <button class="glass-button" @click="load">Generar</button>
      </div>
      <Copyable :text="guides.agent_start" />
    </section>

    <section class="glass-panel p-5 rounded-xl space-y-3">
      <h3 class="text-white font-semibold">2 · Prompt para ChatGPT web: fases en formato Kaanbal</h3>
      <p class="text-sm text-slate-400">Con este prompt, ChatGPT entrega las fases como ZIP con imágenes, instrucciones, contenido validado y un <code>{{ guides.plan_file }}</code> que el Hub importa como tareas con dependencias. Si ChatGPT tiene el MCP de Kaanbal conectado, también puede leer el estado y proponer tareas.</p>
      <Copyable :text="guides.chatgpt_phases" tall />
    </section>

    <section class="glass-panel p-5 rounded-xl space-y-3">
      <h3 class="text-white font-semibold">3 · Bloque para AGENTS.md / CLAUDE.md del repositorio</h3>
      <p class="text-sm text-slate-400">Así cualquier agente que abra el repositorio sabe que la coordinación vive en el Hub.</p>
      <Copyable :text="guides.repo_snippet" />
    </section>

    <section class="glass-panel p-5 rounded-xl">
      <h3 class="text-white font-semibold mb-2">Protocolo que reciben los agentes</h3>
      <ol class="list-decimal pl-5 space-y-1 text-sm text-slate-300"><li v-for="rule in guides.protocol" :key="rule">{{ rule }}</li></ol>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, defineComponent, h } from 'vue'
import api from '../../services/api'

const props = defineProps({ group: { type: String, required: true } })
const guides = ref({ agent_start: '', chatgpt_phases: '', repo_snippet: '', protocol: [], plan_file: 'kaanbal.hub.json' })
const harness = ref('claude'), specialty = ref(''), agent = ref('')

const Copyable = defineComponent({
  props: { text: String, tall: Boolean },
  setup(p) {
    const copied = ref(false)
    const copy = async () => { await navigator.clipboard.writeText(p.text || ''); copied.value = true; setTimeout(() => (copied.value = false), 1500) }
    return () => h('div', { class: 'relative' }, [
      h('pre', { class: `text-xs text-slate-300 whitespace-pre-wrap bg-slate-950/60 border border-white/10 rounded-lg p-3 overflow-auto ${p.tall ? 'max-h-96' : 'max-h-60'}` }, p.text),
      h('button', { class: 'glass-button text-xs absolute top-2 right-2', onClick: copy }, copied.value ? 'Copiado' : 'Copiar'),
    ])
  },
})

async function load() {
  guides.value = (await api.get('/hub/guides', { params: { group: props.group, harness: harness.value, specialty: specialty.value, agent: agent.value } })).data
}
onMounted(load)
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .55rem .75rem; }
</style>
