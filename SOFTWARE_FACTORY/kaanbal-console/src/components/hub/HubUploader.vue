<template>
  <div class="glass-panel rounded-xl p-4 space-y-3">
    <div
      :class="['rounded-xl border-2 border-dashed p-6 text-center transition cursor-pointer',
               dragging ? 'border-cyan-400 bg-cyan-500/10' : 'border-white/15 hover:border-cyan-400/60']"
      role="button" tabindex="0" aria-label="Elegir o soltar archivos para subir"
      @click="picker?.click()" @keydown.enter.prevent="picker?.click()" @keydown.space.prevent="picker?.click()"
      @dragenter.prevent="dragging = true" @dragover.prevent="dragging = true" @dragleave.prevent="dragging = false"
      @drop.prevent="drop">
      <p class="text-3xl" aria-hidden="true">⇪</p>
      <p class="text-white font-medium mt-1">Arrastra aquí los ZIP de fases, imágenes o documentos</p>
      <p class="text-sm text-slate-400">o haz clic para elegirlos. Puedes soltar varios a la vez.</p>
      <input ref="picker" type="file" multiple class="hidden" @change="pick" />
    </div>

    <div class="flex flex-wrap items-center gap-3 text-sm">
      <label class="text-slate-300">Carpeta destino <input v-model="dest" class="field ml-1" placeholder="fuente" /></label>
      <label class="flex items-center gap-2 text-slate-300"><input type="checkbox" v-model="extract" /> Descomprimir ZIP</label>
      <span class="text-xs text-slate-500">Se sube por partes de 4 MB: si la conexión se corta, reintenta solo esa parte.</span>
    </div>

    <ul v-if="queue.length" class="space-y-2">
      <li v-for="item in queue" :key="item.id" class="bg-slate-950/50 border border-white/10 rounded-lg p-3">
        <div class="flex justify-between gap-3 text-sm">
          <span class="text-white truncate">{{ item.file.name }}</span>
          <span class="text-slate-400 shrink-0">{{ size(item.file.size) }}</span>
        </div>
        <div class="h-2 bg-slate-800 rounded mt-2 overflow-hidden">
          <div :class="['h-2 rounded transition-all', item.state === 'error' ? 'bg-red-400' : item.state === 'done' ? 'bg-emerald-400' : 'bg-cyan-400']"
               :style="{ width: `${Math.round(item.progress * 100)}%` }"></div>
        </div>
        <div class="flex justify-between gap-3 mt-1 text-xs">
          <span :class="item.state === 'error' ? 'text-red-300' : item.state === 'done' ? 'text-emerald-300' : 'text-slate-400'">{{ item.note }}</span>
          <span class="flex gap-3 shrink-0">
            <button v-if="item.state === 'error'" class="text-cyan-300" @click="retry(item)">Reintentar</button>
            <button v-if="item.state === 'done' && item.plan" class="text-cyan-300" @click="$emit('import-plan', item.plan)">Importar plan</button>
            <button v-if="['done', 'error', 'waiting'].includes(item.state)" class="text-slate-500 hover:text-white" @click="remove(item)">Quitar</button>
          </span>
        </div>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import api from '../../services/api'
import { detail } from './hubUi'

const props = defineProps({ group: { type: String, required: true } })
const emit = defineEmits(['uploaded', 'import-plan'])

const picker = ref(null), dragging = ref(false), dest = ref('fuente'), extract = ref(true)
const queue = ref([])
let running = false, seq = 0

function size(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']; let i = 0, n = bytes
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

function add(files) {
  for (const file of files) queue.value.push({ id: ++seq, file, state: 'waiting', progress: 0, note: 'En cola', plan: '', uploadId: '' })
  run()
}
function pick(event) { add([...(event.target.files || [])]); event.target.value = '' }
function drop(event) { dragging.value = false; add([...(event.dataTransfer?.files || [])]) }
function remove(item) { queue.value = queue.value.filter(i => i !== item) }
function retry(item) { item.state = 'waiting'; item.note = 'En cola'; run() }

const wait = ms => new Promise(resolve => setTimeout(resolve, ms))

async function withRetries(fn, tries = 4) {
  for (let attempt = 1; ; attempt++) {
    try { return await fn() } catch (e) {
      const status = e.response?.status
      if (attempt >= tries || (status && status < 500 && status !== 408 && status !== 429)) throw e
      await wait(1500 * attempt)
    }
  }
}

// Por partes: cada petición es corta (el proxy no la corta) y una parte fallida se reintenta sola.
async function chunked(item) {
  const file = item.file
  if (!item.uploadId) {
    const { data } = await api.post(`/hub/projects/${props.group}/uploads`, { name: file.name, size: file.size, dest: dest.value || 'fuente', extract: extract.value })
    Object.assign(item, { uploadId: data.upload_id, chunkBytes: data.chunk_bytes, chunks: data.chunks })
  }
  const done = new Set((await api.get(`/hub/uploads/${item.uploadId}`)).data.received)
  const started = Date.now(); let sent = 0
  for (let index = 0; index < item.chunks; index++) {
    if (done.has(index)) continue
    const blob = file.slice(index * item.chunkBytes, Math.min(file.size, (index + 1) * item.chunkBytes))
    await withRetries(() => api.put(`/hub/uploads/${item.uploadId}/chunks/${index}`, blob,
      { headers: { 'Content-Type': 'application/octet-stream' }, timeout: 120000 }))
    done.add(index); sent += blob.size
    item.progress = done.size / item.chunks * 0.95
    const rate = sent / Math.max(1, (Date.now() - started) / 1000)
    const left = (file.size - Math.min(file.size, done.size * item.chunkBytes)) / Math.max(rate, 1)
    item.note = `Parte ${done.size}/${item.chunks} · ${size(rate)}/s · faltan ~${Math.ceil(left)} s`
  }
  item.note = 'Descomprimiendo y guardando…'
  return (await withRetries(() => api.post(`/hub/uploads/${item.uploadId}/complete`, {}, { timeout: 300000 }))).data
}

// Si la API todavía no tiene /uploads (célula sin actualizar), una sola petición con progreso.
async function single(item) {
  const form = new FormData()
  form.append('file', item.file); form.append('dest', dest.value || 'fuente'); form.append('extract', String(extract.value))
  const { data } = await api.post(`/hub/projects/${props.group}/files`, form, {
    headers: { 'Content-Type': 'multipart/form-data' }, timeout: 600000,
    onUploadProgress: e => { item.progress = (e.progress || 0) * 0.95; item.note = `Subiendo ${Math.round((e.progress || 0) * 100)}% (en una sola petición)` },
  })
  return data
}

async function run() {
  if (running) return
  running = true
  try {
    let item
    while ((item = queue.value.find(i => i.state === 'waiting'))) {
      item.state = 'uploading'; item.note = 'Preparando…'
      try {
        let result
        try { result = await chunked(item) } catch (e) {
          if (item.uploadId || ![403, 404, 405].includes(e.response?.status)) throw e
          result = await single(item)
        }
        Object.assign(item, { state: 'done', progress: 1, plan: result.plan_found || '', uploadId: '',
          note: `Listo: ${result.stored} archivo(s) en ${result.dest}/${result.plan_found ? ' · trae plan de tareas' : ''}` })
        emit('uploaded', result)
      } catch (e) {
        item.state = 'error'
        item.note = detail(e, e.code === 'ECONNABORTED' ? 'La conexión tardó demasiado.' : 'No se pudo subir.') + ' Reintenta: continúa donde quedó.'
      }
    }
  } finally { running = false }
}
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .4rem .6rem; }
</style>
