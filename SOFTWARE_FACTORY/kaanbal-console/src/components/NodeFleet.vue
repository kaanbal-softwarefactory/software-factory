<template>
  <div v-if="authState.isAuthenticated" class="fixed bottom-6 left-6 z-[9990] screenshot-ignore flex flex-col items-start gap-2 max-w-[min(28rem,calc(100vw-3rem))]">
    <Transition name="fleet-panel">
      <div
        v-if="open"
        class="w-[22rem] max-h-[70vh] overflow-hidden rounded-2xl border border-white/10 bg-slate-900/95 shadow-2xl backdrop-blur-md"
      >
        <div class="flex items-center justify-between px-4 py-3 border-b border-white/5">
          <div>
            <p class="text-sm font-semibold text-white">Nodos del cluster</p>
            <p class="text-[11px] text-slate-400">
              {{ data?.node_count ?? '—' }} máquina{{ data?.node_count === 1 ? '' : 's' }}
              · k3s coloca pods donde hay RAM/CPU reservada
            </p>
          </div>
          <button class="text-slate-400 hover:text-white p-1" type="button" @click="open = false">✕</button>
        </div>

        <div class="overflow-y-auto max-h-[calc(70vh-3.5rem)] p-3 space-y-3">
          <p v-if="error" class="text-xs text-amber-300">{{ error }}</p>
          <p v-else-if="loading && !data" class="text-xs text-slate-400">Cargando nodos…</p>

          <article
            v-for="node in data?.nodes || []"
            :key="node.name"
            class="rounded-xl border border-white/10 bg-slate-800/50 p-3 space-y-2"
          >
            <div class="flex items-start justify-between gap-2">
              <div>
                <div class="flex items-center gap-2">
                  <span
                    class="h-2 w-2 rounded-full"
                    :class="node.ready ? 'bg-emerald-400' : 'bg-rose-400'"
                  />
                  <h4 class="text-sm font-semibold text-white">{{ node.name }}</h4>
                </div>
                <p class="text-[11px] text-slate-400 mt-0.5">
                  {{ node.internal_ip || 'sin IP' }}
                  · {{ (node.roles || []).join(', ') || 'worker' }}
                </p>
              </div>
              <span class="text-[10px] text-slate-500">{{ node.kubelet }}</span>
            </div>

            <div class="grid grid-cols-2 gap-2 text-[11px]">
              <div>
                <div class="flex justify-between text-slate-400 mb-1">
                  <span>CPU</span>
                  <span class="font-mono text-slate-200">{{ fmtPct(node.cpu?.percent) }}</span>
                </div>
                <div class="h-1.5 rounded-full bg-slate-700 overflow-hidden">
                  <div class="h-full bg-sky-400" :style="{ width: barWidth(node.cpu?.percent) }" />
                </div>
              </div>
              <div>
                <div class="flex justify-between text-slate-400 mb-1">
                  <span>RAM</span>
                  <span class="font-mono text-slate-200">{{ fmtPct(node.memory?.percent) }}</span>
                </div>
                <div class="h-1.5 rounded-full bg-slate-700 overflow-hidden">
                  <div class="h-full bg-violet-400" :style="{ width: barWidth(node.memory?.percent) }" />
                </div>
              </div>
            </div>
            <p class="text-[10px] text-slate-500">
              {{ fmtGi(node.memory?.used_bytes) }} / {{ fmtGi(node.memory?.allocatable_bytes) }} GiB
              · {{ node.cpu?.used?.toFixed?.(2) || '—' }} / {{ node.cpu?.allocatable }} CPU
            </p>
            <div class="flex flex-wrap gap-1">
              <span v-if="node.pressure?.memory" class="text-[10px] px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-300">MemoryPressure</span>
              <span v-if="node.pressure?.disk" class="text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-300">DiskPressure</span>
              <span v-if="node.battery == null" class="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400">Batería N/A</span>
            </div>

            <button
              type="button"
              class="text-[11px] text-blue-300 hover:text-blue-200"
              @click="togglePods(node.name)"
            >
              {{ expanded === node.name ? 'Ocultar pods' : `Pods (${node.pod_count})` }}
            </button>
            <ul v-if="expanded === node.name" class="space-y-1 max-h-40 overflow-y-auto">
              <li
                v-for="pod in node.pods"
                :key="pod.name"
                class="flex justify-between gap-2 text-[11px] px-2 py-1 rounded bg-slate-900/60"
              >
                <span class="text-slate-200 truncate">
                  <span class="text-slate-500">{{ pod.namespace }}/</span>{{ pod.app }}
                </span>
                <span :class="pod.ready ? 'text-emerald-400' : 'text-amber-300'">{{ pod.phase }}</span>
              </li>
            </ul>
          </article>

          <p v-if="(data?.unscheduled_pods || []).length" class="text-[11px] text-amber-300">
            {{ data.unscheduled_pods.length }} pod(s) sin nodo (Pending / sin espacio).
          </p>
          <p class="text-[10px] text-slate-500">
            Si una máquina está llena de *requests*, k3s pone la siguiente app en otro nodo.
          </p>
        </div>
      </div>
    </Transition>

    <button
      type="button"
      class="flex items-center gap-2 px-3 py-2.5 rounded-full border shadow-2xl backdrop-blur-sm"
      :class="chipClass"
      @click="open = !open"
    >
      <span class="relative flex h-2.5 w-2.5">
        <span v-if="allReady" class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
        <span class="relative inline-flex rounded-full h-2.5 w-2.5" :class="allReady ? 'bg-emerald-500' : 'bg-amber-400'" />
      </span>
      <span class="text-xs font-medium text-slate-200">
        {{ chipLabel }}
      </span>
    </button>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import api from '@/services/api'
import { authState } from '@/store/auth'

const open = ref(false)
const loading = ref(false)
const error = ref('')
const data = ref(null)
const expanded = ref('')
let timer = null

const allReady = computed(() => (data.value?.nodes || []).every((n) => n.ready) && (data.value?.nodes || []).length > 0)

const chipLabel = computed(() => {
  const nodes = data.value?.nodes || []
  if (!nodes.length) return 'Nodos'
  const mem = nodes[0]?.memory?.percent
  const label = nodes.length === 1 ? nodes[0].name : `${nodes.length} nodos`
  return mem != null ? `${label} · RAM ${Math.round(mem)}%` : label
})

const chipClass = computed(() =>
  open.value
    ? 'bg-slate-800 border-blue-500/40'
    : 'bg-slate-800/90 border-white/10 hover:border-blue-500/40'
)

function fmtPct(value) {
  return value == null ? '—' : `${Math.round(value)}%`
}

function barWidth(value) {
  if (value == null) return '0%'
  return `${Math.min(100, Math.max(0, value))}%`
}

function fmtGi(bytes) {
  if (!bytes) return '—'
  return (bytes / 1024 ** 3).toFixed(1)
}

function togglePods(name) {
  expanded.value = expanded.value === name ? '' : name
}

async function load() {
  if (!authState.isAuthenticated) return
  loading.value = true
  try {
    const res = await api.get('/system/cluster/nodes')
    data.value = res.data
    error.value = res.data?.error || res.data?.message || ''
    if (res.data?.in_cluster && !res.data?.error) error.value = ''
  } catch (err) {
    error.value = err.response?.data?.detail || err.message || 'No se pudo leer nodos'
  } finally {
    loading.value = false
  }
}

watch(open, (value) => {
  if (value) load()
})

onMounted(() => {
  load()
  timer = setInterval(load, 20000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.fleet-panel-enter-active,
.fleet-panel-leave-active {
  transition: all 0.2s ease;
}
.fleet-panel-enter-from,
.fleet-panel-leave-to {
  opacity: 0;
  transform: translateY(8px);
}
</style>
