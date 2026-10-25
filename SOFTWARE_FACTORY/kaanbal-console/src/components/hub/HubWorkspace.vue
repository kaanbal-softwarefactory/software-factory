<template>
  <section class="space-y-5" aria-label="Centro del proyecto">
    <div class="grid xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] gap-4">
      <section class="rounded-2xl border border-cyan-400/20 bg-gradient-to-br from-cyan-400/10 to-slate-900 p-5 sm:p-6 space-y-4">
        <div class="flex justify-between gap-3 flex-wrap items-start">
          <div><p class="text-xs uppercase tracking-widest text-cyan-200">Resumen vivo</p><h2 class="text-xl sm:text-2xl font-semibold text-white mt-2">{{ context.headline || 'Todo el proyecto, en un lugar' }}</h2></div>
          <span class="text-xs text-slate-400">{{ ago(context.as_of) }}</span>
        </div>
        <p class="text-sm text-slate-300">{{ context.objective?.text || 'Los acuerdos, las fases y la actividad del equipo se reúnen aquí.' }}</p>
        <div class="flex flex-wrap gap-2 text-xs">
          <span class="rounded-full px-3 py-1 bg-white/5 text-slate-200">{{ context.delivery_counts?.reviewed || 0 }} revisadas sin despliegue confirmado</span>
          <span class="rounded-full px-3 py-1 bg-cyan-400/10 text-cyan-200">{{ context.delivery_counts?.verified || 0 }} comprobadas en su ambiente</span>
        </div>
        <article v-for="c in (context.checkpoints || []).slice(0, 2)" :key="c.person + c.agent" class="rounded-xl bg-slate-950/40 p-4 space-y-2">
          <p class="text-xs text-slate-400">{{ c.person }} · {{ c.agent }} · {{ ago(c.updated_at) }}</p>
          <p class="text-sm text-white whitespace-pre-wrap">{{ c.summary }}</p>
          <ul v-if="c.next_steps?.length" class="text-xs text-cyan-200 space-y-1"><li v-for="step in c.next_steps.slice(0, 3)" :key="step">→ {{ step }}</li></ul>
        </article>
        <p v-if="!context.checkpoints?.length" class="text-sm text-slate-400">Al cerrar un avance, los agentes dejan aquí un resumen breve para que puedas retomar sin leer toda la traza.</p>
        <ul v-if="context.decisions?.length" class="space-y-2 border-t border-white/10 pt-3">
          <li v-for="d in context.decisions.slice(0, 3)" :key="d.at + d.text" class="text-xs text-slate-300"><span class="text-slate-500">{{ d.agent }} · {{ ago(d.at) }}</span><p class="mt-1 line-clamp-3">{{ d.text }}</p></li>
        </ul>
      </section>

      <section v-if="!platform" class="glass-panel rounded-2xl p-5 sm:p-6 space-y-4" aria-label="Probar y publicar">
        <div><p class="text-xs uppercase tracking-widest text-emerald-300">Del trabajo a la aplicación</p><h2 class="text-xl font-semibold text-white mt-2">Primero lo probamos en Dev</h2></div>
        <ol class="flex flex-wrap gap-2 text-xs text-slate-400"><li>1. Código revisado</li><li>→ 2. Integrado en Dev</li><li>→ 3. Prueba técnica</li><li>→ 4. Aceptación y promoción</li></ol>
        <div v-if="context.dev_environment?.url" class="rounded-xl border border-emerald-400/20 bg-emerald-400/5 p-4 space-y-2">
          <a v-if="safeLink(context.dev_environment.url)" :href="safeLink(context.dev_environment.url)" target="_blank" rel="noopener" class="text-emerald-200 font-semibold underline">Abrir Dev para probar ↗</a>
          <p class="text-xs text-slate-400">Última comprobación {{ ago(context.dev_environment.at) }}. Dev tiene su propia base de datos e identidad.</p>
        </div>
        <div v-if="context.dev_preparation" class="rounded-xl bg-white/5 p-3 text-sm text-slate-300" role="status"><p>{{ DEV_LABEL[context.dev_preparation.state] || context.dev_preparation.state }}</p><p class="text-xs mt-1 text-slate-400">{{ context.dev_preparation.detail }}</p></div>
        <p v-if="!context.dev_environment" class="text-sm text-slate-400">Crea un espacio de prueba del stack completo. Los agentes trabajan en develop; producción conserva sus datos y su identidad.</p>
        <button v-if="canIntegrate && hasBusiness && !preparing" class="glass-button w-full" :disabled="busy" @click="previewDev">{{ context.dev_environment ? 'Revisar preparación de Dev' : 'Preparar Dev del proyecto' }}</button>
        <p v-if="!hasBusiness" class="text-xs text-slate-500">La preparación aislada de este piloto está disponible para stacks Business Base.</p>
        <button v-if="canIntegrate && context.dev_environment" class="glass-button w-full" :disabled="busy" @click="promote">Preparar promoción a producción</button>
        <a v-if="safeLink(promotion?.url)" :href="safeLink(promotion.url)" target="_blank" rel="noopener" class="block text-sm text-cyan-200 underline">Revisar PR de promoción #{{ promotion.number }} ↗</a>
        <p class="text-xs text-slate-500">La promoción abre un PR del commit verificado. Producción cambia al fusionarlo; los datos y secretos de Dev no se copian.</p>
      </section>
      <section v-else class="glass-panel rounded-2xl p-6 space-y-3">
        <p class="text-xs uppercase tracking-widest text-violet-300">Mejora compartida</p><h2 class="text-xl font-semibold text-white">Kaanbal también es un proyecto</h2>
        <p class="text-sm text-slate-300">Aquí llegan las fricciones de todos los proyectos, con su origen. Un agente puede enfocarse en resolverlas sin perder el contexto del proyecto donde aparecieron.</p>
        <p class="rounded-xl bg-violet-400/10 p-3 text-sm text-violet-200">El código del núcleo y la versión instalada son cosas distintas. Tú eliges cuándo actualizar tu plataforma.</p>
      </section>
    </div>

    <section v-if="context.services?.length" class="space-y-3" aria-label="Servicios del stack">
      <div class="flex justify-between items-center"><h2 class="text-white font-semibold">Lo que tiene este proyecto</h2><span class="text-xs text-slate-500">{{ context.services.length }} servicios</span></div>
      <div class="grid sm:grid-cols-2 xl:grid-cols-3 gap-3">
        <article v-for="s in context.services" :key="s.name" class="glass-panel rounded-xl p-4 space-y-3 min-w-0">
          <div class="flex gap-3 items-start"><span class="rounded-lg bg-cyan-400/10 p-2 text-cyan-200" aria-hidden="true">{{ s.template === 'business-postgres' ? '▤' : s.template === 'business-identity' ? '◇' : '◈' }}</span><div class="min-w-0"><h3 class="font-medium text-white break-words">{{ s.display_name }}</h3><p class="text-xs text-slate-400">{{ serviceLabel(s) }}</p></div></div>
          <div class="flex flex-wrap gap-2"><template v-for="env in s.environments" :key="env"><a v-if="safeLink(s.urls?.[env])" :href="safeLink(s.urls[env])" target="_blank" rel="noopener" class="rounded-full border border-white/10 px-3 py-1 text-xs text-cyan-200 hover:bg-white/5">{{ env === 'prod' ? 'Producción' : 'Dev' }} ↗</a><span v-else class="rounded-full bg-white/5 px-3 py-1 text-xs text-slate-400">{{ env === 'prod' ? 'Producción' : 'Dev' }} · interno</span></template></div>
          <a v-if="safeLink(s.repo_url)" :href="safeLink(s.repo_url)" target="_blank" rel="noopener" class="text-xs text-slate-400 underline">Repositorio ↗</a>
        </article>
      </div>
    </section>

    <section v-if="sources.length" class="space-y-3" aria-label="Fases y referencias">
      <div class="flex justify-between"><h2 class="text-white font-semibold">Tus fases y referencias</h2><button class="text-xs text-cyan-300 underline" @click="$emit('open-files', 'fuente/')">Ver todos los archivos</button></div>
      <div class="flex gap-3 overflow-x-auto pb-2"><button v-for="f in sources" :key="f.path" class="glass-panel text-left p-4 rounded-xl min-w-44 hover:border-cyan-400/30 border border-white/10" @click="$emit('open-files', f.path)"><span class="block text-white text-sm font-medium">{{ f.path.replace('fuente/', '') }}</span><span class="text-xs text-slate-500">{{ f.count }} archivos · abrir imágenes e instrucciones →</span></button></div>
    </section>

    <section v-if="context.deliveries?.length" class="glass-panel rounded-xl p-4 space-y-3" aria-label="Entregas y comprobaciones">
      <h2 class="text-white font-semibold">Qué está entregado y qué puedes probar</h2>
      <div v-for="d in [...context.deliveries].reverse().slice(0, 6)" :key="d.task" class="flex flex-wrap justify-between gap-2 border-t border-white/5 pt-3 text-sm">
        <div class="min-w-0"><p class="text-slate-200">{{ d.task }} · {{ d.title }}</p><p class="text-xs text-slate-500 mt-1">{{ d.label }}<span v-if="d.environment"> · {{ d.environment === 'dev' ? 'Dev' : 'Producción' }}</span> · {{ ago(d.at) }}</p><p v-if="d.verification?.visual_acceptance === 'pending'" class="text-xs text-amber-200 mt-1">Prueba técnica aprobada; falta aceptar el resultado visual.</p></div>
        <a v-if="safeLink(d.url)" :href="safeLink(d.url)" target="_blank" rel="noopener" class="text-emerald-200 text-xs underline self-center">Probar ↗</a>
      </div>
    </section>

    <section class="rounded-xl border border-white/10 p-4 flex flex-wrap gap-4 justify-between items-center">
      <div><h2 class="text-sm font-medium text-white">¿Qué podemos mejorar de Kaanbal?</h2><p class="text-xs text-slate-400 mt-1">La mejora va a Software Factory; este proyecto conserva la referencia.</p></div>
      <div class="flex gap-3 items-center"><router-link v-if="!platform" to="/hub/software-factory" class="text-xs text-violet-200 underline">Ver Software Factory</router-link><button v-if="canParticipate" class="glass-button text-sm" @click="feedback = { title: '', description: '', kind: 'friction' }">Reportar una mejora</button></div>
    </section>
    <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p><p v-if="notice" role="status" class="text-sm text-emerald-200">{{ notice }}</p>

    <div v-if="plan || feedback" class="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4" @keydown.esc="closeDialog" @keydown.tab="trapFocus" @click.self="closeDialog">
      <section v-if="plan" ref="dialog" class="bg-slate-900 border border-white/10 rounded-2xl p-6 max-w-xl w-full space-y-4 max-h-[90vh] overflow-auto" role="dialog" aria-modal="true" aria-label="Preparar Dev">
        <h2 class="text-xl text-white font-semibold">Un Dev separado para este stack</h2>
        <ul class="space-y-2 text-sm text-slate-300"><li v-for="c in plan.plan.components" :key="c.name">{{ c.name }} · {{ c.exists ? 'conservar ambiente Dev' : 'preparar ambiente Dev' }}</li></ul>
        <ul class="list-disc pl-5 text-sm text-slate-400 space-y-2"><li v-for="change in plan.plan.changes" :key="change">{{ change }}</li></ul>
        <p class="text-sm text-emerald-200">{{ plan.plan.preserves }}</p><p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p>
        <div class="flex gap-3 justify-end"><button class="glass-button" :disabled="busy" @click="closeDialog">Cancelar</button><button class="glass-button" :disabled="busy" @click="applyDev">{{ busy ? 'Preparando…' : 'Crear Dev y activar trabajo en Dev' }}</button></div>
      </section>
      <form v-else ref="dialog" class="bg-slate-900 border border-white/10 rounded-2xl p-6 max-w-lg w-full space-y-4" role="dialog" aria-modal="true" aria-label="Reportar una mejora" @submit.prevent="sendFeedback">
        <h2 class="text-xl text-white font-semibold">Mejorar Kaanbal desde tu experiencia</h2>
        <label class="block text-sm text-slate-300">Qué encontraste<input v-model="feedback.title" class="field mt-1 w-full" required maxlength="160" /></label>
        <label class="block text-sm text-slate-300">Qué esperabas y qué ocurrió<textarea v-model="feedback.description" class="field mt-1 w-full" required maxlength="4000" rows="5"></textarea></label>
        <p class="text-xs text-slate-500">Se publica como propuesta en Software Factory con el proyecto de origen. No incluyas contraseñas ni datos personales.</p>
        <p v-if="error" role="alert" class="text-sm text-red-300">{{ error }}</p><div class="flex gap-3 justify-end"><button type="button" class="glass-button" :disabled="busy" @click="closeDialog">Cancelar</button><button class="glass-button" :disabled="busy">Enviar propuesta</button></div>
      </form>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch, nextTick } from 'vue'
import api from '../../services/api'
import { ago, safeLink, detail } from './hubUi'
const props = defineProps({ group: String, context: { type: Object, default: () => ({}) }, files: { type: Object, default: () => ({}) }, canIntegrate: Boolean, canParticipate: Boolean })
const emit = defineEmits(['refresh', 'open-files'])
const busy = ref(false), error = ref(''), notice = ref(''), plan = ref(null), feedback = ref(null), promotion = ref(null), dialog = ref(null)
const platform = computed(() => props.group === 'software-factory')
const hasBusiness = computed(() => props.context.services?.some(s => s.template === 'business-base'))
const preparing = computed(() => props.context.dev_preparation?.state === 'preparing')
const sources = computed(() => Object.entries(props.files.folders || {}).filter(([path]) => path.startsWith('fuente/')).map(([path, count]) => ({ path, count })))
const DEV_LABEL = { preparing: 'Preparando Dev', ready: 'Dev preparado', failed: 'Preparación pendiente de resolver', interrupted: 'Preparación interrumpida' }
const serviceLabel = s => ({ 'business-base': 'Aplicación · Next.js frontend y backend', 'business-postgres': 'Base de datos · PostgreSQL', 'business-identity': 'Identidad · Keycloak' }[s.template] || s.template || 'Servicio del proyecto')
let opener
watch(() => !!(plan.value || feedback.value), async opened => { if (opened) { opener = document.activeElement; await nextTick(); dialog.value?.querySelector('input,button')?.focus() } else { await nextTick(); opener?.focus() } })
function closeDialog() { if (busy.value) return; plan.value = null; feedback.value = null; error.value = '' }
function trapFocus(event) { const nodes = [...dialog.value?.querySelectorAll('input,textarea,button:not(:disabled)') || []]; if (event.shiftKey && document.activeElement === nodes[0]) { event.preventDefault(); nodes.at(-1)?.focus() } else if (!event.shiftKey && document.activeElement === nodes.at(-1)) { event.preventDefault(); nodes[0]?.focus() } }
async function previewDev() { busy.value = true; error.value = ''; try { plan.value = (await api.post(`/hub/projects/${props.group}/dev-environment`, {})).data } catch (e) { error.value = detail(e, 'No se pudo preparar la vista previa de Dev.') } finally { busy.value = false } }
async function applyDev() { busy.value = true; error.value = ''; try { await api.post(`/hub/projects/${props.group}/dev-environment`, { apply: true, plan_id: plan.value.plan_id, app: plan.value.plan.app }); plan.value = null; notice.value = 'Preparación iniciada. El proyecto mostrará el avance y la URL cuando Dev esté verificado.'; emit('refresh') } catch (e) { error.value = detail(e, 'No se pudo iniciar Dev.') } finally { busy.value = false } }
async function promote() { busy.value = true; error.value = ''; try { promotion.value = (await api.post(`/hub/projects/${props.group}/promotion`)).data.promotion; notice.value = 'PR de promoción preparado. Producción cambia cuando lo revises y fusiones.'; emit('refresh') } catch (e) { error.value = detail(e, 'No se pudo preparar la promoción.') } finally { busy.value = false } }
async function sendFeedback() { busy.value = true; error.value = ''; try { const { data } = await api.post(`/hub/projects/${props.group}/feedback`, feedback.value); feedback.value = null; notice.value = `Propuesta ${data.task.key} enviada a Software Factory.`; emit('refresh') } catch (e) { error.value = detail(e, 'No se pudo enviar la propuesta.') } finally { busy.value = false } }
watch(() => props.group, () => { plan.value = null; feedback.value = null; promotion.value = null; notice.value = ''; error.value = '' })
</script>
<style scoped>
.field { background: #0f172a; color: #e2e8f0; border: 1px solid #334155; border-radius: .6rem; padding: .65rem .8rem; }
</style>
