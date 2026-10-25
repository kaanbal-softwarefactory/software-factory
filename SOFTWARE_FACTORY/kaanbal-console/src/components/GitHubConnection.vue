<template>
  <div class="rounded-2xl border border-white/10 bg-slate-900/60 p-6 space-y-3">
    <h2 class="text-lg font-semibold text-white">Tu GitHub</h2>
    <p class="text-sm text-slate-400">
      Conéctalo una vez y tus agentes trabajan sobre cualquier repo al que llegue tu cuenta, desde Claude, Codex,
      Cursor o el celular, sin configurar GitHub en cada equipo. El token se guarda cifrado y nunca se vuelve a mostrar;
      el código viaja al contenedor sin credenciales.
    </p>

    <div v-if="status.connected" class="space-y-3">
      <p class="text-sm text-slate-200">
        Conectado como <strong class="text-white">{{ status.login }}</strong>
        <span class="text-slate-500">· token {{ status.kind }} ····{{ status.token_hint }}</span>
      </p>
      <p v-if="status.scopes?.length" class="text-xs text-slate-500">Alcance: {{ status.scopes.join(', ') }}</p>
      <div class="flex flex-wrap gap-2">
        <button :class="buttonClass" @click="editing = !editing">{{ editing ? 'Cancelar' : 'Cambiar token' }}</button>
        <button class="rounded-lg border border-red-500/30 px-3 py-1.5 text-sm text-red-200 hover:bg-red-500/10" :disabled="busy" @click="disconnect">Desconectar</button>
      </div>
    </div>

    <form v-if="!status.connected || editing" class="space-y-2" @submit.prevent="connect">
      <label class="block text-xs text-slate-400">
        Token de GitHub (fine-grained con Contents y Pull requests de lectura/escritura, o clásico con <code>repo</code>)
        <input v-model="token" type="password" autocomplete="off" placeholder="github_pat_…" class="field" />
      </label>
      <button :class="buttonClass" :disabled="busy || !token">{{ busy ? 'Validando…' : 'Conectar' }}</button>
    </form>

    <p class="text-xs text-slate-500">
      El agente usa <code class="font-mono">github_repos</code>, <code class="font-mono">open_repo_workspace</code> y
      <code class="font-mono">push_workspace</code>. Empujar directo a la rama principal depende de «Push directo» en la política de autonomía (otras ramas no lo necesitan).
    </p>
    <p v-if="error" class="text-sm text-red-300">{{ error }}</p>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'

import api from '@/services/api'

const buttonClass =
  'rounded-lg border border-cyan-500/30 bg-cyan-500/10 px-3 py-1.5 text-sm text-cyan-200 hover:bg-cyan-500/20 transition-colors'

const status = ref({ connected: false })
const token = ref('')
const editing = ref(false)
const busy = ref(false)
const error = ref('')

async function run(action) {
  busy.value = true
  error.value = ''
  try {
    status.value = (await action()).data
    editing.value = false
  } catch (err) {
    error.value = err.response?.data?.detail || 'No se pudo completar la operación con GitHub.'
  } finally {
    token.value = ''
    busy.value = false
  }
}

const connect = () => run(() => api.put('/autonomy/github', { token: token.value.trim() }))
const disconnect = () => run(() => api.delete('/autonomy/github'))

onMounted(async () => {
  try {
    status.value = (await api.get('/autonomy/github')).data
  } catch {
    // Sin sesión o API antigua: se queda en «no conectado».
  }
})
</script>

<style scoped>
.field { display: block; width: 100%; margin-top: 0.35rem; border: 1px solid rgb(255 255 255 / 0.1); border-radius: 0.5rem; background: rgb(30 41 59); padding: 0.5rem 0.75rem; color: white; font-size: 0.875rem; }
</style>
