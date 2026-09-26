<script setup>
// La URL de la API llega por VITE_API_URL: en local desde .env.development (tu
// uvicorn) y en el clúster desde .env.production, que Kaanbal escribe con la URL
// real de la API del stack. Vite las resuelve al construir, así que el mismo
// código sirve en los dos lados. Sin variable, se asume el mismo origen.
import { onMounted, ref } from 'vue'

const API = import.meta.env.VITE_API_URL || ''
const health = ref(null)
const error = ref('')
const items = ref([])
const newItem = ref('')

const call = async (path, options) => {
  const res = await fetch(`${API}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
}

const load = async () => {
  error.value = ''
  try {
    health.value = await call('/health')
    items.value = (await call('/items')).items
  } catch (e) {
    error.value = e.message
  }
}

const add = async () => {
  const name = newItem.value.trim()
  if (!name) return
  try {
    await call('/items', { method: 'POST', body: JSON.stringify({ name }) })
    newItem.value = ''
    await load()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(load)
</script>

<!-- El bloque de abajo va entre marcas "raw" de Jinja porque Kaanbal pasa cada
     archivo del template por Jinja al crear el repositorio, y si no, las llaves
     dobles de Vue se borrarían. Esas marcas no llegan al repo generado. -->

{% raw %}
<template>
  <main class="page">
    <h1>placeholder-app</h1>
    <p class="sub">Vue 3 + API + base de datos, desplegado con Kaanbal.</p>

    <section class="card">
      <h2>Conexión</h2>
      <p v-if="error" class="bad">No pude hablar con la API ({{ error }}). ¿Está corriendo y permite tu origen en CORS?</p>
      <ul v-else-if="health">
        <li>API: <strong class="ok">{{ health.status }}</strong> en <code>{{ API || 'mismo origen' }}</code></li>
        <li>Base ({{ health.engine }}): <strong :class="health.database ? 'ok' : 'bad'">{{ health.database ? 'conectada' : 'sin conexión' }}</strong></li>
      </ul>
      <p v-else>Consultando…</p>
    </section>

    <section class="card">
      <h2>Datos de prueba</h2>
      <form @submit.prevent="add">
        <input v-model="newItem" placeholder="Escribe algo y guárdalo" />
        <button type="submit">Guardar</button>
      </form>
      <ul>
        <li v-for="item in items" :key="item.id">{{ item.name }}</li>
        <li v-if="!items.length" class="muted">Todavía no hay nada guardado.</li>
      </ul>
    </section>
  </main>
</template>
{% endraw %}

<style scoped>
.page {
  font-family: system-ui, sans-serif;
  max-width: 40rem;
  margin: 4rem auto;
  padding: 0 1rem;
  color: #0f172a;
}
.sub { color: #64748b; margin-top: -0.5rem; }
.card {
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
  padding: 1rem 1.25rem;
  margin-top: 1.5rem;
}
h2 { font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; }
ul { list-style: none; padding: 0; }
li { padding: 0.25rem 0; }
.ok { color: #059669; }
.bad { color: #dc2626; }
.muted { color: #94a3b8; }
form { display: flex; gap: 0.5rem; margin-bottom: 0.75rem; }
input { flex: 1; padding: 0.5rem 0.75rem; border: 1px solid #cbd5e1; border-radius: 0.5rem; }
button { padding: 0.5rem 1rem; border: 0; border-radius: 0.5rem; background: #2563eb; color: white; cursor: pointer; }
@media (prefers-color-scheme: dark) {
  .page { color: #e2e8f0; }
  .card { border-color: #1e293b; }
  input { background: #0f172a; color: #e2e8f0; border-color: #334155; }
}
</style>
