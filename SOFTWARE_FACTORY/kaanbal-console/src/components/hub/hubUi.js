// Etiquetas y formato compartidos por las vistas del Hub de agentes.

export const HARNESS = {
  codex: { label: 'Codex', color: 'bg-emerald-500/20 text-emerald-300 border-emerald-400/30' },
  claude: { label: 'Claude', color: 'bg-orange-500/20 text-orange-300 border-orange-400/30' },
  cursor: { label: 'Cursor', color: 'bg-sky-500/20 text-sky-300 border-sky-400/30' },
  chatgpt: { label: 'ChatGPT', color: 'bg-teal-500/20 text-teal-300 border-teal-400/30' },
  kaanbal: { label: 'Kaanbal', color: 'bg-blue-500/20 text-blue-300 border-blue-400/30' },
  otro: { label: 'Agente', color: 'bg-slate-500/20 text-slate-300 border-slate-400/30' },
}

export const PRESENCE = {
  online: { label: 'En línea', dot: 'bg-emerald-400' },
  idle: { label: 'Sin latido reciente', dot: 'bg-amber-400' },
  offline: { label: 'Desconectado', dot: 'bg-slate-500' },
  left: { label: 'Salió', dot: 'bg-slate-700' },
}

export const STATUS = {
  proposed: { label: 'Propuestas', tone: 'border-violet-400/40 text-violet-200' },
  todo: { label: 'Por hacer', tone: 'border-slate-400/40 text-slate-200' },
  in_progress: { label: 'En curso', tone: 'border-cyan-400/40 text-cyan-200' },
  blocked: { label: 'Bloqueadas', tone: 'border-red-400/40 text-red-200' },
  review: { label: 'En revisión', tone: 'border-amber-400/40 text-amber-200' },
  done: { label: 'Hechas', tone: 'border-emerald-400/40 text-emerald-200' },
  dropped: { label: 'Descartadas', tone: 'border-slate-700 text-slate-500' },
}

export const KIND = {
  join: '↘ entró', leave: '↗ salió', progress: '▸ avance', decision: '◆ decisión', blocker: '⛔ bloqueo',
  question: '? pregunta', handoff: '⇄ relevo', lesson: '✎ lección', note: '· nota', task: '☐ tarea',
  file: '▤ archivo', board: '▦ tablero', digest: '✉ secretario', message: '✉ mensaje',
}

export function harnessOf(name) { return HARNESS[name] || HARNESS.otro }

export function inScope(task, settings) {
  const phases = settings.scope_phases || [], keys = settings.scope_tasks || []
  return (!phases.length && !keys.length) || phases.includes(task.phase) || keys.includes(task.key)
}

export function safeLink(value) {
  try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) ? url.href : null } catch { return null }
}

export function utcDate(value) {
  if (!value) return new Date(NaN)
  const text = String(value)
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text) ? text : `${text}Z`)
}

export function ago(value) {
  if (!value) return '—'
  const date = utcDate(value)
  if (Number.isNaN(date.getTime())) return '—'
  const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000)
  if (seconds < 60) return 'hace un momento'
  if (seconds < 3600) return `hace ${Math.floor(seconds / 60)} min`
  if (seconds < 86400) return `hace ${Math.floor(seconds / 3600)} h`
  return date.toLocaleDateString()
}

export function detail(error, fallback) {
  const value = error?.response?.data?.detail
  if (typeof value === 'string') return value
  if (value?.message) return value.message
  return fallback
}

// Markdown mínimo y seguro para el tablero: se escapa todo antes de dar formato.
export function renderMarkdown(text) {
  const escape = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const inline = (s) => escape(s)
    .replace(/`([^`]+)`/g, '<code class="px-1 rounded bg-slate-800 text-cyan-200">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong class="text-white">$1</strong>')
  const out = []
  let list = false
  for (const line of String(text || '').split('\n')) {
    const heading = line.match(/^(#{1,4})\s+(.*)$/)
    const item = line.match(/^\s*[-*]\s+(.*)$/)
    if (!item && list) { out.push('</ul>'); list = false }
    if (heading) {
      const size = ['text-xl', 'text-lg', 'text-base', 'text-sm'][heading[1].length - 1]
      out.push(`<p class="${size} font-semibold text-white mt-3">${inline(heading[2])}</p>`)
    } else if (item) {
      if (!list) { out.push('<ul class="list-disc pl-5 space-y-1">'); list = true }
      out.push(`<li>${inline(item[1])}</li>`)
    } else if (line.trim()) {
      out.push(`<p>${inline(line)}</p>`)
    }
  }
  if (list) out.push('</ul>')
  return out.join('')
}
