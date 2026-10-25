<template>
  <div class="space-y-4">
    <div class="glass-panel p-4 rounded-xl flex flex-wrap items-end gap-3">
      <label class="text-sm text-slate-300">Archivo o ZIP de fases
        <input ref="picker" type="file" class="block mt-1 text-sm text-slate-300" @change="pick" />
      </label>
      <label class="text-sm text-slate-300">Carpeta destino
        <input v-model="dest" class="field block mt-1" placeholder="fuente" />
      </label>
      <label class="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" v-model="extract" /> Descomprimir ZIP</label>
      <button class="glass-button" :disabled="!file || uploading" @click="upload">{{ uploading ? 'Subiendo…' : 'Subir' }}</button>
      <p class="text-xs text-slate-500 basis-full">Los ZIP se abren en la carpeta destino; los ZIP de adentro (una fase por archivo) se abren un nivel. Un archivo con la misma ruta se reemplaza.</p>
      <p v-if="message" class="text-sm text-emerald-300 basis-full">{{ message }}</p>
      <p v-if="error" role="alert" class="text-sm text-red-300 basis-full">{{ error }}</p>
      <button v-if="planFound" class="glass-button" @click="$emit('import-plan', planFound)">Importar plan de {{ planFound }}</button>
    </div>

    <div class="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-4">
      <div class="glass-panel p-4 rounded-xl max-h-[70vh] overflow-auto">
        <div class="flex justify-between items-center mb-2">
          <p class="text-sm text-slate-400">{{ files.length }} archivos · {{ size(total) }}</p>
          <input v-model="filter" placeholder="Filtrar" aria-label="Filtrar archivos" class="field text-sm py-1" />
        </div>
        <p v-if="!files.length" class="text-slate-500 text-sm">Todavía no hay archivos. Sube el ZIP de fases para que sea la fuente de los agentes.</p>
        <ul class="text-sm space-y-0.5">
          <li v-for="row in visibleRows" :key="row.key">
            <button v-if="row.folder" class="w-full text-left text-slate-300 hover:text-white flex gap-2"
                    :style="{ paddingLeft: `${row.depth * 14}px` }" @click="toggle(row.key)">
              <span class="w-3">{{ open.has(row.key) ? '▾' : '▸' }}</span><span>{{ row.name }}</span>
              <span class="text-slate-600 ml-auto">{{ row.count }}</span>
            </button>
            <button v-else :class="['w-full text-left flex gap-2 rounded px-1', selected?.path === row.path ? 'bg-cyan-500/10 text-cyan-200' : 'text-slate-400 hover:text-white']"
                    :style="{ paddingLeft: `${row.depth * 14 + 16}px` }" @click="preview(row.file)">
              <span class="truncate">{{ row.name }}</span><span class="text-slate-600 ml-auto shrink-0">{{ size(row.file.size) }}</span>
            </button>
          </li>
        </ul>
      </div>

      <div class="glass-panel p-4 rounded-xl min-h-64">
        <p v-if="!selected" class="text-slate-500 text-sm">Elige un archivo para verlo. Las imágenes y los textos se muestran aquí.</p>
        <template v-else>
          <div class="flex justify-between gap-3 items-start mb-3">
            <div class="min-w-0">
              <p class="text-white font-medium break-all">{{ selected.path }}</p>
              <p class="text-xs text-slate-500">{{ selected.content_type }} · {{ size(selected.size) }} · subido por {{ selected.uploaded_by || '—' }}</p>
            </div>
            <div class="flex gap-2 shrink-0">
              <a v-if="blobUrl" :href="blobUrl" :download="selected.path.split('/').pop()" class="glass-button text-sm">Descargar</a>
              <button v-if="canManage" class="glass-button text-sm text-red-300" @click="remove(selected.path)">Quitar</button>
            </div>
          </div>
          <p v-if="loadingPreview" class="text-slate-400 text-sm">Cargando…</p>
          <img v-else-if="isImage" :src="blobUrl" :alt="selected.path" class="max-w-full rounded-lg border border-white/10" />
          <pre v-else-if="text !== null" class="text-xs text-slate-300 whitespace-pre-wrap break-words max-h-[60vh] overflow-auto">{{ text }}</pre>
          <p v-else class="text-slate-500 text-sm">Vista previa no disponible para este tipo; descárgalo.</p>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import api from '../../services/api'
import { detail } from './hubUi'

const props = defineProps({ group: { type: String, required: true }, canManage: Boolean })
const emit = defineEmits(['changed', 'import-plan'])

const files = ref([]), filter = ref(''), open = ref(new Set(['fuente', 'live']))
const file = ref(null), picker = ref(null), dest = ref('fuente'), extract = ref(true)
const uploading = ref(false), message = ref(''), error = ref(''), planFound = ref('')
const selected = ref(null), blobUrl = ref(''), text = ref(null), loadingPreview = ref(false)

const total = computed(() => files.value.reduce((sum, f) => sum + (f.size || 0), 0))
const isImage = computed(() => (selected.value?.content_type || '').startsWith('image/') && blobUrl.value)

// Árbol plano: carpetas con conteo y archivos, respetando qué carpetas están abiertas.
const visibleRows = computed(() => {
  const needle = filter.value.toLowerCase()
  const list = files.value.filter(f => !needle || f.path.toLowerCase().includes(needle))
  const rows = [], counts = {}
  for (const f of list) {
    const parts = f.path.split('/')
    for (let i = 1; i < parts.length; i++) { const key = parts.slice(0, i).join('/'); counts[key] = (counts[key] || 0) + 1 }
  }
  const seen = new Set()
  for (const f of list) {
    const parts = f.path.split('/')
    let visible = true
    for (let i = 1; i < parts.length; i++) {
      const key = parts.slice(0, i).join('/')
      if (visible && !seen.has(key)) { rows.push({ key, folder: true, name: parts[i - 1], depth: i - 1, count: counts[key] }); seen.add(key) }
      visible = visible && (open.value.has(key) || !!needle)
    }
    if (visible) rows.push({ key: f.path, path: f.path, name: parts[parts.length - 1], depth: parts.length - 1, file: f })
  }
  return rows
})

function size(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']; let i = 0, n = bytes
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(n >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}
function toggle(key) { const next = new Set(open.value); next.has(key) ? next.delete(key) : next.add(key); open.value = next }
function pick(event) { file.value = event.target.files?.[0] || null; message.value = ''; error.value = '' }

async function load() {
  try { files.value = (await api.get(`/hub/projects/${props.group}/files`)).data.files }
  catch (e) { error.value = detail(e, 'No se pudieron listar los archivos.') }
}

async function upload() {
  uploading.value = true; message.value = ''; error.value = ''
  const form = new FormData()
  form.append('file', file.value); form.append('dest', dest.value || 'fuente'); form.append('extract', String(extract.value))
  try {
    const { data } = await api.post(`/hub/projects/${props.group}/files`, form,
      { headers: { 'Content-Type': 'multipart/form-data' }, timeout: 300000 })
    message.value = `Listo: ${data.stored} archivo(s) en ${data.dest}/.`
    planFound.value = data.plan_found || ''
    file.value = null; if (picker.value) picker.value.value = ''
    await load(); emit('changed')
  } catch (e) { error.value = detail(e, 'No se pudo subir el archivo.') }
  finally { uploading.value = false }
}

function clearPreview() { if (blobUrl.value) URL.revokeObjectURL(blobUrl.value); blobUrl.value = ''; text.value = null }

async function preview(f) {
  clearPreview(); selected.value = f; loadingPreview.value = true
  try {
    const { data } = await api.get(`/hub/projects/${props.group}/files/content`, { params: { path: f.path }, responseType: 'blob' })
    blobUrl.value = URL.createObjectURL(data)
    const type = f.content_type || ''
    if (type.startsWith('text/') || /json|xml|javascript|csv/.test(type)) text.value = (await data.text()).slice(0, 200000)
  } catch (e) { error.value = detail(e, 'No se pudo abrir el archivo.') }
  finally { loadingPreview.value = false }
}

async function remove(path) {
  if (!confirm(`¿Quitar ${path} del proyecto? Los agentes dejarán de verlo.`)) return
  try { await api.delete(`/hub/projects/${props.group}/files`, { params: { path } }); clearPreview(); selected.value = null; await load(); emit('changed') }
  catch (e) { error.value = detail(e, 'No se pudo quitar el archivo.') }
}

watch(() => props.group, () => { selected.value = null; clearPreview(); load() })
onMounted(load)
onBeforeUnmount(clearPreview)
defineExpose({ load })
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .5rem .7rem; }
</style>
