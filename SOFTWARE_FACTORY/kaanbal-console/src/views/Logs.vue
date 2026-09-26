<template>
  <div class="space-y-6">
    <div class="glass-panel p-6 rounded-lg">
      <h1 class="text-3xl font-bold bg-gradient-to-r from-cyan-300 to-blue-500 bg-clip-text text-transparent">Activity Logs</h1>
      <p class="mt-2 text-slate-400">Audit trail for API requests, deployments, auth events and platform maintenance operations.</p>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
      <div class="glass-panel p-4 rounded-lg border border-white/10">
        <p class="text-xs uppercase tracking-wide text-slate-500">Total Logs</p>
        <p class="text-2xl font-bold text-white mt-2">{{ stats.total ?? 0 }}</p>
      </div>
      <div class="glass-panel p-4 rounded-lg border border-white/10">
        <p class="text-xs uppercase tracking-wide text-slate-500">Errors</p>
        <p class="text-2xl font-bold text-red-400 mt-2">{{ stats.by_level?.error ?? 0 }}</p>
      </div>
      <div class="glass-panel p-4 rounded-lg border border-white/10">
        <p class="text-xs uppercase tracking-wide text-slate-500">Deploy Events</p>
        <p class="text-2xl font-bold text-emerald-400 mt-2">{{ stats.by_category?.deploy ?? 0 }}</p>
      </div>
      <div class="glass-panel p-4 rounded-lg border border-white/10">
        <p class="text-xs uppercase tracking-wide text-slate-500">API Requests</p>
        <p class="text-2xl font-bold text-blue-400 mt-2">{{ stats.by_category?.api ?? 0 }}</p>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="glass-panel p-4 rounded-lg border border-white/10">
        <p class="text-xs uppercase tracking-wide text-slate-500 mb-3">Top Targets</p>
        <div class="space-y-2 max-h-36 overflow-auto pr-1">
          <div v-for="(count, target) in grouped.by_target" :key="target" class="flex items-center justify-between text-sm">
            <span class="text-slate-300 truncate mr-2">{{ target }}</span>
            <span class="text-cyan-300 font-semibold">{{ count }}</span>
          </div>
          <p v-if="!Object.keys(grouped.by_target || {}).length" class="text-slate-500 text-sm">No target grouping data yet.</p>
        </div>
      </div>
      <div class="glass-panel p-4 rounded-lg border border-white/10">
        <p class="text-xs uppercase tracking-wide text-slate-500 mb-3">By Environment</p>
        <div class="space-y-2 max-h-36 overflow-auto pr-1">
          <div v-for="(count, env) in grouped.by_env" :key="env" class="flex items-center justify-between text-sm">
            <span class="text-slate-300 uppercase">{{ env }}</span>
            <span class="text-emerald-300 font-semibold">{{ count }}</span>
          </div>
          <p v-if="!Object.keys(grouped.by_env || {}).length" class="text-slate-500 text-sm">No env grouping data yet.</p>
        </div>
      </div>
    </div>

    <div class="glass-panel p-6 rounded-lg space-y-4">
      <div class="grid grid-cols-1 md:grid-cols-5 gap-3">
        <input v-model="filters.search" class="glass-input" placeholder="Search action/target/actor/detail" />
        <select v-model="filters.category" class="glass-input">
          <option value="">All Categories</option>
          <option v-for="cat in categories" :key="cat" :value="cat">{{ cat }}</option>
        </select>
        <select v-model="filters.level" class="glass-input">
          <option value="">All Levels</option>
          <option value="info">info</option>
          <option value="warn">warn</option>
          <option value="error">error</option>
          <option value="debug">debug</option>
        </select>
        <input v-model="filters.actor" class="glass-input" placeholder="Actor username" />
        <input v-model="filters.target" class="glass-input" placeholder="Target app/resource" />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <input v-model="filters.since" type="datetime-local" class="glass-input" />
        <input v-model="filters.until" type="datetime-local" class="glass-input" />
        <input v-model="clearOlderThan" type="datetime-local" class="glass-input" placeholder="Clear older than" />
      </div>

      <div class="flex flex-wrap items-center gap-3">
        <button @click="loadLogs" class="glass-button">Refresh</button>
        <button @click="exportLogs" class="px-4 py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-all">Export NDJSON</button>
        <button @click="exportCsv" class="px-4 py-2.5 rounded-lg bg-teal-600 hover:bg-teal-500 text-white font-medium transition-all">Export CSV</button>
        <button @click="clearLogs" class="px-4 py-2.5 rounded-lg bg-red-600/80 hover:bg-red-500 text-white font-medium transition-all">Clear Filtered</button>
        <button @click="sendSampleClientLog" class="px-4 py-2.5 rounded-lg bg-indigo-600/80 hover:bg-indigo-500 text-white font-medium transition-all">Send Sample Client Log</button>
        <span class="text-xs text-slate-500">{{ total }} records</span>
      </div>

      <p v-if="message" class="text-sm" :class="messageClass">{{ message }}</p>
    </div>

    <div class="glass-panel rounded-lg overflow-hidden border border-white/10">
      <div class="overflow-auto max-h-[62vh]">
        <table class="w-full text-sm">
          <thead class="sticky top-0 bg-slate-900/95 border-b border-white/10">
            <tr class="text-left text-slate-400">
              <th class="px-4 py-3">Time</th>
              <th class="px-4 py-3">Level</th>
              <th class="px-4 py-3">Category</th>
              <th class="px-4 py-3">Action</th>
              <th class="px-4 py-3">Actor</th>
              <th class="px-4 py-3">Target</th>
              <th class="px-4 py-3">HTTP</th>
              <th class="px-4 py-3">Detail</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log._id" class="border-b border-white/5 hover:bg-white/5 align-top">
              <td class="px-4 py-3 text-slate-300 whitespace-nowrap">{{ formatTime(log.timestamp) }}</td>
              <td class="px-4 py-3">
                <span class="px-2 py-1 rounded text-xs font-semibold" :class="levelClass(log.level)">{{ log.level }}</span>
              </td>
              <td class="px-4 py-3 text-cyan-300">{{ log.category || '-' }}</td>
              <td class="px-4 py-3 text-white font-medium">{{ log.action }}</td>
              <td class="px-4 py-3 text-slate-300">{{ log.actor || '-' }}</td>
              <td class="px-4 py-3 text-slate-300">{{ log.target || '-' }}</td>
              <td class="px-4 py-3 text-slate-400">
                <div v-if="log.method || log.path" class="text-xs">
                  <div>{{ log.method || '-' }} {{ log.path || '-' }}</div>
                  <div>Status: {{ log.status_code ?? '-' }} · {{ formatDuration(log.duration_ms) }}</div>
                </div>
                <span v-else>-</span>
              </td>
              <td class="px-4 py-3 text-xs text-slate-400">
                <details>
                  <summary class="cursor-pointer hover:text-white">View</summary>
                  <pre class="mt-2 p-2 rounded bg-black/30 text-[11px] whitespace-pre-wrap max-w-[420px]">{{ pretty(log.detail) }}</pre>
                </details>
              </td>
            </tr>
            <tr v-if="!logs.length">
              <td colspan="8" class="px-4 py-8 text-center text-slate-500">No logs found for current filters.</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import axios from 'axios'

const logs = ref([])
const total = ref(0)
const stats = ref({ by_category: {}, by_level: {}, total: 0 })
const grouped = ref({ by_target: {}, by_env: {} })
const clearOlderThan = ref('')
const message = ref('')
const messageClass = ref('text-slate-400')

const filters = ref({
  search: '',
  category: '',
  level: '',
  actor: '',
  target: '',
  since: '',
  until: '',
  skip: 0,
  limit: 200,
})

const categories = computed(() => Object.keys(stats.value.by_category || {}).sort())

const toIso = (v) => (v ? new Date(v).toISOString() : '')

const buildParams = () => {
  const p = {
    skip: filters.value.skip,
    limit: filters.value.limit,
  }
  if (filters.value.search) p.search = filters.value.search
  if (filters.value.category) p.category = filters.value.category
  if (filters.value.level) p.level = filters.value.level
  if (filters.value.actor) p.actor = filters.value.actor
  if (filters.value.target) p.target = filters.value.target
  if (filters.value.since) p.since = toIso(filters.value.since)
  if (filters.value.until) p.until = toIso(filters.value.until)
  return p
}

const setMessage = (text, type = 'info') => {
  message.value = text
  messageClass.value = type === 'error' ? 'text-red-400' : type === 'success' ? 'text-emerald-400' : 'text-slate-400'
}

const loadStats = async () => {
  const { data } = await axios.get('/api/v1/logs/stats')
  stats.value = data || {}
  const groupedRes = await axios.get('/api/v1/logs/stats/grouped')
  grouped.value = groupedRes.data || { by_target: {}, by_env: {} }
}

const loadLogs = async () => {
  try {
    setMessage('')
    const { data } = await axios.get('/api/v1/logs', { params: buildParams() })
    logs.value = data.logs || []
    total.value = data.total || 0
    await loadStats()
  } catch (err) {
    setMessage(err?.response?.data?.detail || 'Failed to load logs', 'error')
  }
}

const exportLogs = async () => {
  try {
    const response = await axios.get('/api/v1/logs/export', {
      params: buildParams(),
      responseType: 'blob',
    })
    const blob = new Blob([response.data], { type: 'application/x-ndjson' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `activity-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.ndjson`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    setMessage('Logs exported successfully.', 'success')
  } catch (err) {
    setMessage(err?.response?.data?.detail || 'Failed to export logs', 'error')
  }
}

const exportCsv = async () => {
  try {
    const response = await axios.get('/api/v1/logs/export.csv', {
      params: buildParams(),
      responseType: 'blob',
    })
    const blob = new Blob([response.data], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `activity-logs-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    setMessage('CSV exported successfully.', 'success')
  } catch (err) {
    setMessage(err?.response?.data?.detail || 'Failed to export CSV', 'error')
  }
}

const clearLogs = async () => {
  try {
    const params = {}
    if (filters.value.category) params.category = filters.value.category
    if (filters.value.level) params.level = filters.value.level
    if (filters.value.target) params.target = filters.value.target
    if (clearOlderThan.value) params.older_than = toIso(clearOlderThan.value)

    const hasFilter = Object.keys(params).length > 0
    if (!hasFilter) {
      setMessage('For safety, set at least one clear filter (category/level/target/older_than).', 'error')
      return
    }

    const { data } = await axios.delete('/api/v1/logs', { params })
    setMessage(`Deleted ${data.deleted} logs.`, 'success')
    await loadLogs()
  } catch (err) {
    setMessage(err?.response?.data?.detail || 'Failed to clear logs', 'error')
  }
}

const sendSampleClientLog = async () => {
  try {
    await axios.post('/api/v1/logs/ingest', {
      action: 'client.sample.error',
      category: 'system',
      level: 'warn',
      target: 'kaanbal-console',
      source: 'logs-dashboard',
      detail: {
        message: 'Sample external/client log sent from dashboard',
        user_agent: navigator.userAgent,
      },
    })
    setMessage('Sample client log ingested.', 'success')
    await loadLogs()
  } catch (err) {
    setMessage(err?.response?.data?.detail || 'Failed to ingest sample log', 'error')
  }
}

const formatTime = (v) => {
  if (!v) return '-'
  return new Date(v).toLocaleString()
}

const formatDuration = (v) => {
  if (v === null || v === undefined) return '-'
  return `${Number(v).toFixed(1)} ms`
}

const levelClass = (lvl) => {
  if (lvl === 'error') return 'bg-red-500/20 text-red-300 border border-red-500/30'
  if (lvl === 'warn') return 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
  if (lvl === 'info') return 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
  return 'bg-slate-500/20 text-slate-300 border border-slate-500/30'
}

const pretty = (obj) => {
  if (!obj) return '{}'
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

onMounted(async () => {
  await loadLogs()
})
</script>
