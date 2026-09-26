<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold bg-gradient-to-r from-amber-400 to-orange-500 bg-clip-text text-transparent">Updates</h1>
        <p class="mt-2 text-slate-400">La versión del engine que corre esta célula y lo que hay publicado.</p>
      </div>
      <button @click="load" :disabled="loading" class="glass-button text-sm flex items-center gap-2">
        <span :class="{'animate-spin': loading}">🔄</span> Revisar
      </button>
    </div>

    <div v-if="loading && !data" class="text-center py-12 text-slate-400">Consultando upstream...</div>

    <!-- Progreso del upgrade: se lee del clúster, sobrevive a recargas y al reinicio de la API -->
    <div
      v-if="upgrade && upgrade.exists"
      class="glass-panel p-6 rounded-xl"
      :class="{
        'border-sky-500/30': upgrade.state === 'running',
        'border-emerald-500/30 bg-emerald-500/5': upgrade.state === 'succeeded',
        'border-red-500/30 bg-red-500/5': upgrade.state === 'failed',
      }"
    >
      <div class="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h3 class="font-semibold" :class="{
            'text-sky-300': upgrade.state === 'running',
            'text-emerald-300': upgrade.state === 'succeeded',
            'text-red-300': upgrade.state === 'failed',
          }">
            <span v-if="upgrade.state === 'running'">⏳ Actualizando la célula…</span>
            <span v-else-if="upgrade.state === 'succeeded'">✅ Último update: verificado</span>
            <span v-else>❌ Último update: falló</span>
          </h3>
          <p v-if="upgrade.state !== 'running'" class="text-xs text-slate-400 mt-1">
            {{ upgrade.ref ? `ref ${upgrade.ref}` : '' }}
            <span v-if="upgrade.actor"> · por {{ upgrade.actor }}</span>
            <span v-if="upgrade.finished_at || upgrade.started_at">
              · {{ new Date(upgrade.finished_at || upgrade.started_at).toLocaleString() }}
            </span>
          </p>
          <p class="text-xs text-slate-400 mt-1">
            {{ currentStep }}
            <span v-if="connectionLost" class="text-amber-300">
              · Reconectando con la API (se está reemplazando a sí misma)…
            </span>
          </p>
        </div>
        <span class="font-mono text-xs text-slate-500">{{ upgrade.name }}</span>
      </div>

      <p v-if="upgrade.state === 'failed'" class="text-sm text-slate-300 mt-3">
        Si el fallo ocurrió después de promover, la célula ya se revirtió a su versión anterior.
        El detalle está en el log.
      </p>

      <div v-if="upgrade.state === 'succeeded' && upgradeJustFinished" class="mt-3 flex items-center gap-3 flex-wrap">
        <p class="text-sm text-slate-300">La consola corre una versión nueva. Recárgala para verla.</p>
        <button @click="reloadPage" class="upgrade-button">Recargar consola</button>
      </div>

      <!-- En curso o recién terminado: log a la vista. Histórico: plegado. -->
      <pre
        v-if="upgradeRunning || upgradeJustFinished || upgrade.state === 'failed'"
        ref="logBox"
        class="mt-4 text-[11px] leading-relaxed bg-slate-950/80 border border-white/10 rounded-lg p-3 max-h-80 overflow-y-auto text-slate-300 whitespace-pre-wrap"
      >{{ upgrade.log || 'Esperando a que arranque el Job…' }}</pre>
      <details v-else class="mt-3">
        <summary class="text-xs text-slate-500 cursor-pointer">Ver log del último update</summary>
        <pre class="mt-2 text-[11px] leading-relaxed bg-slate-950/80 border border-white/10 rounded-lg p-3 max-h-80 overflow-y-auto text-slate-300 whitespace-pre-wrap">{{ upgrade.log || 'El log ya no está disponible (se conserva 24 h).' }}</pre>
      </details>
    </div>

    <template v-if="data">
      <!-- Versión actual -->
      <div class="glass-panel p-6 rounded-xl">
        <div class="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <p class="text-xs uppercase tracking-wider text-slate-500">Versión instalada</p>
            <p class="text-2xl font-bold text-white mt-1">{{ data.current.version }}</p>
            <p v-if="!data.current.known" class="text-sm text-amber-300 mt-2 max-w-xl">
              {{ data.current.reason }}
            </p>
            <p v-else-if="data.current.upstream_sha" class="text-xs font-mono text-slate-500 mt-1">
              {{ data.current.upstream_sha.slice(0, 7) }}
            </p>
          </div>
          <span class="text-xs px-3 py-1 rounded-full" :class="channelClass">
            canal {{ data.channel }}
          </span>
        </div>

        <!-- Componentes -->
        <div v-if="Object.keys(data.current.components || {}).length" class="mt-5 pt-5 border-t border-white/10 grid gap-2 sm:grid-cols-3">
          <div v-for="(info, name) in data.current.components" :key="name" class="text-sm">
            <p class="text-slate-300 font-medium">{{ name }}</p>
            <p class="font-mono text-xs text-slate-500 break-all">{{ info.tag }}</p>
            <p v-if="driftFor(name)?.custom" class="text-xs text-amber-300 mt-1">
              ⚠ modificado localmente
            </p>
          </div>
        </div>
      </div>

      <!-- Estado del upgrade -->
      <div v-if="data.update_available" class="glass-panel p-6 rounded-xl border-amber-500/30 bg-amber-500/5">
        <div class="flex items-start gap-3">
          <span class="text-2xl">⬆️</span>
          <div class="min-w-0 flex-1">
            <h3 class="font-semibold text-amber-300">
              Hay una versión nueva: {{ data.latest?.version }}
            </h3>
            <p v-if="data.latest?.published_at" class="text-xs text-slate-400 mt-1">
              Publicada el {{ new Date(data.latest.published_at).toLocaleDateString() }}
            </p>

            <div v-if="data.blocked_by_drift" class="mt-4 rounded-lg bg-slate-900/60 border border-amber-500/30 p-4 space-y-2">
              <p class="text-sm font-medium text-amber-200">Esta célula tiene cambios locales</p>
              <p class="text-sm text-slate-400">
                Actualizar sobrescribiría el código que modificaste. Elige qué hacer con él antes
                de continuar — nunca se descarta solo.
              </p>
              <ul class="text-sm text-slate-400 list-disc list-inside space-y-1 mt-2">
                <li><span class="text-slate-200">Adoptar upstream</span> — descarta lo local y vuelve al carril común.</li>
                <li><span class="text-slate-200">Rebasar</span> — reaplica tus cambios sobre la versión nueva.</li>
                <li><span class="text-slate-200">Proponer</span> — abre un PR upstream con tu cambio; si se acepta, vuelve a ti como versión oficial.</li>
              </ul>
            </div>

            <div v-if="data.latest?.notes" class="mt-4 text-sm text-slate-300 whitespace-pre-wrap max-h-48 overflow-y-auto bg-slate-900/40 rounded-lg p-3">{{ data.latest.notes }}</div>

            <p class="text-xs text-slate-500 mt-4">
              El upgrade lo ejecuta un Job dedicado, no la consola: así el proceso que conduce la
              actualización sobrevive al reemplazo de la propia API.
            </p>
          </div>
        </div>
      </div>

      <div v-else class="glass-panel p-6 rounded-xl border-emerald-500/25 bg-emerald-500/5">
        <p class="text-emerald-300 font-medium">✅ Esta célula está al día.</p>
      </div>

      <!-- Canal dev: commits pendientes del monorepo -->
      <div v-if="data.tracking === 'commits'" class="glass-panel p-6 rounded-xl">
        <div class="flex items-center justify-between gap-3 flex-wrap mb-4">
          <h3 class="font-semibold text-white">Commits en {{ data.source || 'software-factory' }}</h3>
          <span v-if="data.upstream?.head_sha" class="font-mono text-xs text-slate-500">
            main @ {{ data.upstream.head_sha.slice(0, 7) }}
          </span>
        </div>

        <p v-if="!data.upstream?.available" class="text-sm text-amber-300">
          {{ data.upstream?.reason || 'No se pudo consultar GitHub.' }}
        </p>
        <p v-else-if="data.upstream.reason" class="text-sm text-amber-300 mb-3">{{ data.upstream.reason }}</p>
        <p v-else-if="!data.upstream.commits?.length" class="text-sm text-slate-400">
          Esta célula corre el último commit de main.
        </p>

        <template v-if="data.upstream?.commits?.length">
          <p class="text-sm text-slate-300 mb-3">
            {{ data.upstream.ahead_by }} commit(s) sin aplicar.
            <span v-if="data.upstream.touches_engine">
              Cambian: <span class="text-amber-300">{{ data.upstream.components.join(', ') }}</span>
            </span>
            <span v-else class="text-slate-500">Ninguno toca el engine: no hace falta actualizar.</span>
          </p>
          <div class="space-y-2 max-h-72 overflow-y-auto">
            <a
              v-for="c in data.upstream.commits"
              :key="c.sha"
              :href="c.url"
              target="_blank"
              rel="noopener"
              class="flex items-start gap-3 text-sm rounded-lg px-2 py-1.5 hover:bg-white/5"
            >
              <span class="font-mono text-xs bg-slate-800 px-2 py-0.5 rounded text-slate-300 shrink-0">{{ c.sha.slice(0, 7) }}</span>
              <span class="min-w-0">
                <span class="text-slate-200 break-words">{{ c.message }}</span>
                <span class="block text-xs text-slate-500">{{ c.author }} · {{ c.date ? new Date(c.date).toLocaleString() : '' }}</span>
              </span>
            </a>
          </div>
        </template>

        <!-- El botón no depende de que haya lista de commits: cuando el historial cambió
             (el proyecto se mudó de repositorio) no hay qué listar, pero sí qué aplicar. -->
        <template v-if="data.update_available && !upgradeRunning">
          <div class="mt-5 pt-4 border-t border-white/10">
            <p class="text-xs text-slate-400">
              Construye las imágenes, promueve, verifica que los pods arranquen y revierte solo si algo
              falla. Tus apps y datos no se tocan. La consola se reiniciará unos segundos durante el proceso.
            </p>

            <div v-if="!confirming" class="mt-3">
              <button
                @click="confirming = true"
                :disabled="data.blocked_by_drift || launching"
                class="upgrade-button"
              >
                ⬆️ Actualizar ahora
              </button>
              <p v-if="data.blocked_by_drift" class="text-xs text-amber-300 mt-2">
                Bloqueado: hay cambios locales en el engine. Resuelve la deriva primero.
              </p>
            </div>

            <div v-else class="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
              <p class="text-sm text-amber-200">
                {{ data.upstream.ahead_by != null
                  ? `¿Aplicar ${data.upstream.ahead_by} commit(s) sobre esta célula?`
                  : `¿Actualizar esta célula a la última revisión de ${data.source || 'upstream'}?` }}
              </p>
              <div class="flex gap-2 mt-3">
                <button @click="launchUpgrade" :disabled="launching" class="upgrade-button">
                  {{ launching ? 'Lanzando…' : 'Sí, actualizar' }}
                </button>
                <button @click="confirming = false" :disabled="launching" class="glass-button text-sm">Cancelar</button>
              </div>
            </div>

            <details class="mt-4">
              <summary class="text-xs text-slate-500 cursor-pointer">Avanzado: ejecutarlo desde el nodo</summary>
              <pre class="mt-2 text-xs bg-slate-950/80 border border-white/10 rounded-lg p-3 overflow-x-auto text-emerald-300">{{ upgradeCommand }}</pre>
            </details>
          </div>
        </template>
      </div>

      <!-- Historial -->
      <div v-if="data.pending_releases?.length" class="glass-panel p-6 rounded-xl">
        <h3 class="font-semibold text-white mb-4">Cambios pendientes de aplicar</h3>
        <div class="space-y-3">
          <div v-for="r in data.pending_releases" :key="r.version" class="flex items-start gap-3 text-sm">
            <span class="font-mono text-xs bg-slate-800 px-2 py-1 rounded text-slate-300 shrink-0">{{ r.version }}</span>
            <div class="min-w-0">
              <p class="text-slate-200">{{ r.name || r.version }}</p>
              <p v-if="r.notes" class="text-xs text-slate-400 line-clamp-2">{{ r.notes }}</p>
            </div>
          </div>
        </div>
      </div>
    </template>

    <div v-if="error" class="glass-panel p-4 rounded-xl border-red-500/30 bg-red-500/5 text-sm text-red-300">
      {{ error }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'

// ── Upgrade desde la consola ─────────────────────────────────────────────
// El upgrade corre como Job en el clúster. La consola solo lo lanza y lee su
// estado, así que recargar la página o que la API se reinicie a mitad del
// proceso no interrumpe nada: al volver se retoma el seguimiento.
const POLL_MS = 4000
const upgrade = ref(null)
const confirming = ref(false)
const launching = ref(false)
const connectionLost = ref(false)
const upgradeJustFinished = ref(false)
const logBox = ref(null)
let pollTimer = null

const upgradeRunning = computed(() => upgrade.value?.exists && upgrade.value.state === 'running')

// Última línea con prefijo del script: dice en qué fase va la transacción.
const currentStep = computed(() => {
  const lines = (upgrade.value?.log || '').split('\n').filter(l => l.includes('[kaanbal-upgrade]'))
  const last = lines[lines.length - 1] || ''
  return last.replace('[kaanbal-upgrade]', '').trim() || 'Preparando…'
})

const scrollLog = async () => {
  await nextTick()
  if (logBox.value) logBox.value.scrollTop = logBox.value.scrollHeight
}

const pollUpgrade = async () => {
  try {
    const { data: status } = await axios.get('/api/v1/core/upgrade', {
      params: upgrade.value?.name ? { name: upgrade.value.name } : {},
    })
    connectionLost.value = false
    const wasRunning = upgradeRunning.value
    upgrade.value = status
    scrollLog()
    if (status.exists && status.state !== 'running') {
      stopPolling()
      if (wasRunning) {
        upgradeJustFinished.value = true
        load()
      }
    }
  } catch (e) {
    // Durante el upgrade la API recibe su imagen nueva y deja de responder unos
    // segundos. No es un fallo del upgrade: se sigue intentando.
    connectionLost.value = true
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(pollUpgrade, POLL_MS)
}

const stopPolling = () => {
  clearInterval(pollTimer)
  pollTimer = null
}

const launchUpgrade = async () => {
  launching.value = true
  error.value = ''
  try {
    const { data: started } = await axios.post('/api/v1/core/upgrade', { ref: 'main' })
    upgrade.value = { exists: true, ...started, log: '' }
    upgradeJustFinished.value = false
    confirming.value = false
    startPolling()
  } catch (e) {
    error.value = e.response?.data?.detail || 'No se pudo lanzar el upgrade'
  } finally {
    launching.value = false
  }
}

const reloadPage = () => window.location.reload()

// Al entrar se muestra el resultado del último update. Si sigue en curso (por
// ejemplo, tras recargar la página a mitad del proceso), se retoma el seguimiento.
const resumeIfRunning = async () => {
  try {
    const { data: status } = await axios.get('/api/v1/core/upgrade')
    if (status.exists) upgrade.value = status
    if (status.exists && status.state === 'running') {
      startPolling()
      scrollLog()
    }
  } catch (e) {
    // Sin permisos de Jobs (célula aún sin el RBAC nuevo) simplemente no se muestra.
  }
}

onUnmounted(stopPolling)

const data = ref(null)
const loading = ref(false)
const error = ref('')

const channelClass = computed(() => ({
  stable: 'bg-emerald-500/20 text-emerald-300',
  dev: 'bg-blue-500/20 text-blue-300',
  custom: 'bg-amber-500/20 text-amber-300',
}[data.value?.channel] || 'bg-slate-500/20 text-slate-300'))

const driftFor = (name) => data.value?.drift?.components?.[name]

const upgradeCommand = 'sudo KAANBAL_ORG=<tu-org> bash ~/kaanbal-source/SOFTWARE_FACTORY/tools/core-upgrade.sh --ref main'

const load = async () => {
  loading.value = true
  error.value = ''
  try {
    const { data: payload } = await axios.get('/api/v1/core/updates')
    data.value = payload
    window.dispatchEvent(new CustomEvent('kaanbal:engine-checked', { detail: payload }))
  } catch (e) {
    error.value = e.response?.data?.detail || 'No se pudo consultar el estado del engine'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  load()
  resumeIfRunning()
})
</script>

<style scoped>
.glass-panel {
  background: rgba(15, 23, 42, 0.6);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.1);
}
.glass-button {
  padding: 0.5rem 1rem;
  border-radius: 0.5rem;
  background: rgba(148, 163, 184, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.25);
  color: white;
  font-weight: 500;
  transition: all 0.2s;
}
.glass-button:hover:not(:disabled) { background: rgba(148, 163, 184, 0.22); }
.glass-button:disabled { opacity: 0.45; cursor: not-allowed; }
.upgrade-button {
  padding: 0.55rem 1.1rem;
  border-radius: 0.5rem;
  background: rgba(245, 158, 11, 0.2);
  border: 1px solid rgba(245, 158, 11, 0.4);
  color: rgb(253, 230, 138);
  font-weight: 600;
  font-size: 0.875rem;
  transition: all 0.2s;
}
.upgrade-button:hover:not(:disabled) { background: rgba(245, 158, 11, 0.32); }
.upgrade-button:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
