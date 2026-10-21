<template>
  <div class="space-y-6">
    <div class="flex justify-between gap-4 flex-wrap">
      <div><h1 class="text-3xl font-bold text-white">Sistemas</h1>
        <p class="text-slate-400 mt-2">Cada grupo reúne las aplicaciones de un sistema y su responsable.</p>
        <p class="text-xs text-slate-500 mt-1">El responsable organiza el trabajo. La visibilidad sigue definida por los permisos de Kaanbal.</p></div>
      <router-link to="/stacks" class="glass-button self-start">Lanzar un stack</router-link>
    </div>
    <p v-if="error" role="alert" class="text-red-300">{{ error }}</p>
    <div class="flex flex-wrap gap-3">
      <input v-model="search" placeholder="Buscar sistema o aplicación" aria-label="Buscar sistema" class="field flex-1 min-w-56" />
      <select v-model="ownerFilter" class="field" aria-label="Filtrar responsable"><option value="all">Todos los responsables</option><option value="">Sin asignar</option><option v-for="owner in assignedOwners" :key="owner">{{ owner }}</option></select>
      <button @click="load" class="glass-button" :disabled="loading">Actualizar</button>
      <button v-if="canManage" @click="edit({ slug: '', name: '', owner: null, stage: 'prototype', description: '' })" class="glass-button">Nuevo grupo</button>
    </div>
    <p v-if="loading" class="text-slate-400">Cargando sistemas…</p>
    <p v-else-if="!filtered.length" class="glass-panel p-8 text-slate-400">No hay sistemas que coincidan con los filtros.</p>
    <div class="grid md:grid-cols-2 xl:grid-cols-3 gap-4">
      <article v-for="group in filtered" :key="group.slug" class="glass-panel p-5 rounded-2xl space-y-4">
        <div class="flex justify-between gap-3"><div><h2 class="text-lg font-semibold text-white">{{ group.name }}</h2><span class="text-xs text-cyan-300">{{ stages[group.stage] }} · {{ group.app_count }} apps</span></div>
          <button v-if="canManage && group.slug" @click="edit(group)" class="text-sm text-slate-300 hover:text-white">Editar</button></div>
        <p class="text-sm text-slate-400">{{ group.description || 'Sin descripción' }}</p>
        <div class="text-sm text-slate-200">Responsable: <strong>{{ group.owner || 'Sin asignar' }}</strong></div>
        <ul class="space-y-2"><li v-for="app in group.apps" :key="app.name" class="flex justify-between gap-2 text-sm border-t border-white/5 pt-2"><span class="text-slate-200 break-all">{{ app.name }}</span><span class="text-slate-500">{{ app.template || app.status }}</span></li></ul>
        <router-link :to="{ path: '/apps', query: { group: group.slug || '__ungrouped' } }" class="text-sm text-cyan-300 hover:underline">Ver aplicaciones →</router-link>
      </article>
    </div>
    <div v-if="form" class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" @click.self="form = null">
      <form @submit.prevent="save" class="bg-slate-900 border border-white/10 rounded-2xl p-6 w-full max-w-lg space-y-4" role="dialog" aria-modal="true" aria-label="Editar sistema">
        <h2 class="text-xl font-semibold text-white">Configurar sistema</h2>
        <label class="block text-sm text-slate-300">Identificador<input v-model="form.slug" required pattern="[a-z0-9_][a-z0-9_-]{0,99}" :disabled="!isNew" class="field w-full mt-1" /></label>
        <label class="block text-sm text-slate-300">Nombre<input v-model="form.name" required maxlength="100" class="field w-full mt-1" /></label>
        <label class="block text-sm text-slate-300">Responsable<select v-model="form.owner" class="field w-full mt-1"><option :value="null">Sin asignar</option><option v-for="owner in owners" :key="owner">{{ owner }}</option><option v-if="form.owner && !owners.includes(form.owner)" :value="form.owner" disabled>{{ form.owner }} (cuenta inactiva; reasignar)</option></select></label>
        <label class="block text-sm text-slate-300">Etapa<select v-model="form.stage" class="field w-full mt-1"><option v-for="(label, value) in stages" :key="value" :value="value">{{ label }}</option></select></label>
        <label class="block text-sm text-slate-300">Descripción<textarea v-model="form.description" maxlength="1000" class="field w-full mt-1" /></label>
        <p v-if="saveError" role="alert" class="text-red-300 text-sm">{{ saveError }}</p>
        <div class="flex justify-end gap-3"><button type="button" @click="form = null" class="glass-button">Cancelar</button><button class="glass-button" :disabled="saving">{{ saving ? 'Guardando…' : 'Guardar' }}</button></div>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import api from '../services/api'

const groups = ref([]), owners = ref([]), search = ref(''), ownerFilter = ref('all')
const loading = ref(false), error = ref(''), canManage = ref(false), form = ref(null)
const isNew = ref(false), saving = ref(false), saveError = ref('')
const stages = { prototype: 'Prototipo', active: 'Activo', reference: 'Base de referencia', archived: 'Archivado' }
const assignedOwners = computed(() => [...new Set(groups.value.map(g => g.owner).filter(Boolean))].sort())
const filtered = computed(() => groups.value.filter(g => (ownerFilter.value === 'all' || (g.owner || '') === ownerFilter.value) && `${g.name} ${g.slug} ${g.apps.map(a => a.name).join(' ')}`.toLowerCase().includes(search.value.toLowerCase())))
async function load() {
  loading.value = true; error.value = ''
  try { groups.value = (await api.get('/groups')).data.groups }
  catch (e) { error.value = e.response?.data?.detail || 'No se pudieron cargar los sistemas.' }
  finally { loading.value = false }
}
function edit(group) { isNew.value = !group.slug; form.value = { slug: group.slug, name: group.name, owner: group.owner, stage: group.stage, description: group.description }; saveError.value = '' }
async function save() {
  saving.value = true; saveError.value = ''
  try { const { slug, ...body } = form.value; await api.put(`/groups/${encodeURIComponent(slug)}`, body); form.value = null; await load() }
  catch (e) { saveError.value = typeof e.response?.data?.detail === 'string' ? e.response.data.detail : 'No se pudo guardar el sistema.' }
  finally { saving.value = false }
}
onMounted(async () => {
  await load()
  try { owners.value = (await api.get('/groups/owners')).data.owners; canManage.value = true }
  catch { canManage.value = false }
})
</script>

<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .65rem .8rem; }
</style>
