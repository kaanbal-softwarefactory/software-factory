<template>
  <div class="w-full flex justify-center p-4">
    <div class="max-w-2xl w-full bg-gray-800/80 backdrop-blur-md rounded-lg shadow-xl overflow-hidden border border-white/10">
      
      <!-- Header -->
      <div class="px-6 py-6 border-b border-white/10 flex justify-between items-center">
        <div>
           <h1 class="text-2xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">Deploy New App</h1>
           <p class="text-gray-400 text-sm mt-1">Configure and launch your application.</p>
        </div>
        <div class="text-right">
            <span class="text-xs text-slate-500 uppercase font-bold tracking-wider">Step {{ step }} of 4</span>
            <div class="flex gap-1 mt-1 justify-end" v-if="step > 1">
              <span v-for="env in allEnvironments" :key="env" :class="['px-2 py-0.5 rounded text-xs font-medium', envBadgeColors[env]]">
                {{ env }}
              </span>
            </div>
        </div>
      </div>

      <!-- Credentials Warning -->
      <div v-if="!credentialsOk && step === 2" class="px-6 py-3 bg-yellow-500/10 border-b border-yellow-500/30 flex items-center gap-3">
        <span class="text-xl">⚠️</span>
        <div class="flex-1">
          <p class="text-yellow-200 text-sm font-medium">Credentials not configured</p>
          <p class="text-yellow-200/70 text-xs">Go to Settings → Credentials to configure Git and Docker before deploying.</p>
        </div>
        <router-link to="/settings" class="text-yellow-400 hover:text-yellow-300 text-sm underline">Configure</router-link>
      </div>

      <!-- Content -->
      <div class="p-8 space-y-6">
        
        <!-- Step 1: Creation Mode Selection -->
        <div v-if="step === 1" class="space-y-6 animate-fade-in">
          <div class="text-center mb-6">
            <h2 class="text-xl font-bold text-white mb-2">How do you want to create your app?</h2>
            <p class="text-slate-400 text-sm">Choose how to set up your project</p>
          </div>

          <div class="grid grid-cols-1 gap-4">
            <!-- Scaffold Mode -->
            <button 
              @click="form.creation_mode = 'scaffold'"
              :class="['p-5 rounded-xl border-2 text-left transition-all', form.creation_mode === 'scaffold' ? 'border-blue-500 bg-blue-500/10' : 'border-white/10 hover:border-white/30 bg-white/5']"
            >
              <div class="flex items-start gap-4">
                <span class="text-3xl">🏗️</span>
                <div class="flex-1">
                  <h3 class="font-bold text-white">Scaffold from Template</h3>
                  <p class="text-sm text-slate-400 mt-1">Create from our battle-tested templates with best practices built-in. Perfect for new projects.</p>
                  <div class="flex gap-2 mt-2">
                    <span class="text-xs px-2 py-1 bg-blue-500/20 text-blue-400 rounded">Recommended</span>
                    <span class="text-xs px-2 py-1 bg-slate-700 text-slate-400 rounded">Vue, FastAPI, n8n...</span>
                  </div>
                </div>
              </div>
            </button>

            <!-- Empty Repo Mode -->
            <button 
              @click="form.creation_mode = 'empty'"
              :class="['p-5 rounded-xl border-2 text-left transition-all', form.creation_mode === 'empty' ? 'border-purple-500 bg-purple-500/10' : 'border-white/10 hover:border-white/30 bg-white/5']"
            >
              <div class="flex items-start gap-4">
                <span class="text-3xl">📁</span>
                <div class="flex-1">
                  <h3 class="font-bold text-white">Empty Repository</h3>
                  <p class="text-sm text-slate-400 mt-1">Create an empty repo with pipeline template. Clone it, add your code, and push.</p>
                  <div class="flex gap-2 mt-2">
                    <span class="text-xs px-2 py-1 bg-purple-500/20 text-purple-400 rounded">Full Control</span>
                    <span class="text-xs px-2 py-1 bg-slate-700 text-slate-400 rounded">Custom Code</span>
                  </div>
                </div>
              </div>
            </button>

            <!-- Config Only Mode -->
            <button 
              @click="form.creation_mode = 'config-only'"
              :class="['p-5 rounded-xl border-2 text-left transition-all', form.creation_mode === 'config-only' ? 'border-emerald-500 bg-emerald-500/10' : 'border-white/10 hover:border-white/30 bg-white/5']"
            >
              <div class="flex items-start gap-4">
                <span class="text-3xl">⚙️</span>
                <div class="flex-1">
                  <h3 class="font-bold text-white">Config Only (No Code)</h3>
                  <p class="text-sm text-slate-400 mt-1">Deploy official Docker images like MongoDB, PostgreSQL, Redis. No code repo needed.</p>
                  <div class="flex gap-2 mt-2">
                    <span class="text-xs px-2 py-1 bg-emerald-500/20 text-emerald-400 rounded">Databases</span>
                    <span class="text-xs px-2 py-1 bg-slate-700 text-slate-400 rounded">Services</span>
                  </div>
                </div>
              </div>
            </button>
          </div>
        </div>
        
        <!-- Step 2: Configuration -->
        <div v-if="step === 2" class="space-y-6 animate-fade-in">
          
          <!-- 🚀 Technology Picker -->
          <div class="space-y-3">
            <label class="block text-sm font-medium text-gray-300">Pick your technology</label>
            <!-- Search + Category Filter -->
            <div class="flex flex-col sm:flex-row gap-2">
              <div class="relative flex-1">
                <span class="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-sm pointer-events-none">🔍</span>
                <input v-model="templateSearch" type="text" placeholder="Search templates..." class="glass-input w-full pl-9 text-sm" />
              </div>
              <div class="flex flex-wrap gap-1 items-center">
                <button type="button" @click="templateCategoryFilter = ''"
                        :class="['px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all border', !templateCategoryFilter ? 'bg-blue-600/20 border-blue-500/50 text-blue-400' : 'border-transparent bg-slate-800/50 text-slate-500 hover:text-slate-300']">
                  All
                </button>
                <button type="button" v-for="cat in availableCategories" :key="cat" @click="templateCategoryFilter = cat"
                        :class="['px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all border capitalize', templateCategoryFilter === cat ? 'bg-blue-600/20 border-blue-500/50 text-blue-400' : 'border-transparent bg-slate-800/50 text-slate-500 hover:text-slate-300']">
                  {{ categoryIcons[cat] || '📦' }} {{ cat }}
                </button>
              </div>
            </div>
            <!-- Template Cards Grid -->
            <div class="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-52 overflow-y-auto custom-scrollbar pr-1">
              <button v-for="tpl in displayedTemplates" :key="tpl.id" type="button" @click="form.template = tpl.id"
                      :class="['p-3 rounded-xl border-2 text-left transition-all group relative overflow-hidden',
                                form.template === tpl.id
                                  ? 'border-blue-500 bg-blue-500/10 shadow-lg shadow-blue-500/10'
                                  : 'border-white/5 hover:border-white/20 bg-slate-900/40 hover:bg-slate-800/60']">
                <div class="absolute top-0 left-0 right-0 h-0.5 opacity-80" :style="{ background: tpl.color || '#6366f1' }"></div>
                <div class="flex items-center gap-2 mb-1.5">
                  <span class="text-base" :style="{ filter: form.template === tpl.id ? 'drop-shadow(0 0 6px ' + (tpl.color || '#6366f1') + ')' : 'none' }">{{ getTemplateIcon(tpl.icon) }}</span>
                  <h4 class="text-xs font-bold text-white truncate flex-1">{{ tpl.name }}</h4>
                  <span v-if="tpl.popular" class="text-[8px] leading-none">⭐</span>
                </div>
                <p class="text-[10px] text-slate-500 line-clamp-2 mb-1.5 leading-tight">{{ tpl.description }}</p>
                <div class="flex flex-wrap gap-0.5">
                  <span v-for="tech in (tpl.stack || []).slice(0, 3)" :key="tech"
                        class="text-[8px] px-1 py-0.5 rounded bg-slate-800/80 text-slate-400">{{ tech }}</span>
                  <span v-if="tpl.status !== 'ready'" class="text-[8px] px-1 py-0.5 rounded bg-yellow-500/10 text-yellow-500">{{ tpl.status }}</span>
                </div>
              </button>
            </div>
            <p v-if="displayedTemplates.length === 0" class="text-center text-xs text-slate-500 py-3">No templates match your criteria.</p>
            <!-- Selected template indicator -->
            <div v-if="selectedTemplate" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-blue-500/5 border border-blue-500/20 transition-all">
              <span>{{ getTemplateIcon(selectedTemplate.icon) }}</span>
              <span class="text-sm text-blue-400 font-medium">{{ selectedTemplate.name }}</span>
              <span class="text-[10px] text-slate-500 uppercase tracking-wider">selected</span>
            </div>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
              <!-- Name & Environments -->
              <div class="space-y-4">
                  <div>
                    <label class="block text-sm font-medium text-gray-300 mb-1">Application Name</label>
                    <input v-model="form.name" type="text" class="glass-input w-full" :disabled="useRootDomain" placeholder="e.g. customer-portal" required />
                    <p class="text-xs text-slate-500 mt-1">Lowercase, hyphens only.</p>
                    <label v-if="supportsRootDomain" class="mt-2 flex items-center gap-2 text-xs text-slate-300 cursor-pointer">
                      <input type="checkbox" v-model="useRootDomain" class="w-4 h-4 rounded bg-slate-700 border-slate-600" />
                      <span>Homepage del dominio: prod queda en <code>https://{{ rootDomainHost }}</code> con el nombre interno <code>{{ rootNamePreview }}</code>.</span>
                    </label>
                    <p v-if="supportsRootDomain && useRootDomain" class="mt-1 text-[11px] text-amber-300/90">
                      Kaanbal tomará la raíz de <span class="font-mono">{{ rootDomainHost }}</span>: si hoy apunta a otro
                      servidor (por ejemplo la página de Hostinger), dejará de mostrarse y verás tu app.
                    </p>
                    <p v-else-if="existingRootApp && selectedTemplate?.category === 'frontend'" class="mt-2 text-xs text-amber-400/80">
                      ⚠️ La raíz de <span class="font-mono">{{ rootDomainHost }}</span> ya la usa
                      <span class="font-mono font-semibold">{{ existingRootApp }}</span>. Puede haber una app raíz por dominio: elige otro dominio para usar su raíz.
                    </p>
                  </div>

                  <div>
                    <label class="block text-sm font-medium text-gray-300 mb-1">Group (Optional)</label>
                    <input
                      v-model="form.app_group"
                      type="text"
                      class="glass-input w-full"
                      list="app-group-suggestions"
                      placeholder="e.g. shop"
                    />
                    <datalist id="app-group-suggestions">
                      <option v-for="group in appGroupSuggestions" :key="group" :value="group" />
                    </datalist>
                    <p class="text-xs text-slate-500 mt-1">Use the same group to keep related frontend/backend apps together.</p>
                  </div>

                  <!-- Multi-Environment Selector (Prod is always included, can add dev/staging) -->
                  <div>
                    <label class="block text-sm font-medium text-gray-300 mb-2">Additional Environments <span class="text-slate-500">(prod always included)</span></label>
                    <div class="space-y-2">
                        <label class="flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all"
                               :class="form.environments.includes('dev') ? 'bg-yellow-500/20 border border-yellow-500/30' : 'bg-slate-900/50 border border-transparent hover:border-slate-600'">
                            <input type="checkbox" value="dev" v-model="form.environments" class="w-4 h-4 rounded bg-slate-700 border-slate-600" />
                            <span class="text-lg">🧪</span>
                            <div class="flex-1">
                                <span class="text-white font-medium">+ Development</span>
                                <p class="text-xs text-slate-400">For testing and development</p>
                            </div>
                        </label>
                        <label class="flex items-center gap-3 p-3 rounded-lg cursor-pointer transition-all"
                               :class="form.environments.includes('staging') ? 'bg-orange-500/20 border border-orange-500/30' : 'bg-slate-900/50 border border-transparent hover:border-slate-600'">
                            <input type="checkbox" value="staging" v-model="form.environments" class="w-4 h-4 rounded bg-slate-700 border-slate-600" />
                            <span class="text-lg">🔬</span>
                            <div class="flex-1">
                                <span class="text-white font-medium">+ Staging</span>
                                <p class="text-xs text-slate-400">Pre-production testing</p>
                            </div>
                        </label>
                        <!-- Prod is ALWAYS included (shown as always-on) -->
                        <div class="flex items-center gap-3 p-3 rounded-lg bg-emerald-500/20 border border-emerald-500/30">
                            <input type="checkbox" checked disabled class="w-4 h-4 rounded bg-emerald-600 border-emerald-500 cursor-not-allowed" />
                            <span class="text-lg">🚀</span>
                            <div class="flex-1">
                                <span class="text-white font-medium">Production</span>
                                <span class="text-xs text-emerald-400 ml-2">(always included)</span>
                                <p class="text-xs text-slate-400">Live environment</p>
                            </div>
                        </div>
                    </div>
                  </div>
              </div>

              <!-- Specs -->
              <div class="space-y-4">
                  <div>
                    <label class="block text-sm font-medium text-gray-300 mb-1">Exposure per Environment</label>
                    <p v-if="exposureHint" class="text-xs text-amber-400/80 mb-2 flex items-center gap-1">
                      <span>💡</span> {{ exposureHint }}
                    </p>

                    <!-- Dominio padre: solo importa si algún ambiente sale a internet -->
                    <div v-if="hasPublicExposure && availableDomains.length > 0" class="mb-3 p-3 rounded-lg border border-cyan-500/30 bg-cyan-500/5">
                      <label class="block text-xs font-semibold text-cyan-300 mb-2">Dominio público</label>
                      <select v-model="form.domain_id" class="w-full bg-slate-900/80 border border-white/10 rounded-lg px-3 py-2 text-white text-sm">
                        <option v-for="d in availableDomains" :key="d._id" :value="d._id">
                          {{ d.fqdn }}{{ d.is_default ? ' (default)' : '' }}
                        </option>
                      </select>
                      <p class="text-[11px] text-slate-400 mt-2">
                        Producción quedará en
                        <span class="font-mono text-slate-300">{{ previewPublicHost }}</span>.
                        Se puede mudar a otro dominio después sin volver a desplegar.
                      </p>
                    </div>

                    <!-- ── MULTI-PORT MODE: port × env matrix ── -->
                    <div v-if="isMultiPort" class="space-y-3">
                      <!-- EMQX Edge profile picker -->
                      <div v-if="isEmqxTemplate" class="p-3 rounded-lg border border-cyan-500/30 bg-cyan-500/5 space-y-2">
                        <p class="text-xs text-cyan-300 font-semibold">Perfil de despliegue</p>
                        <div class="flex flex-col gap-2">
                          <label class="flex items-start gap-2 cursor-pointer">
                            <input type="radio" value="edge" v-model="emqxProfile" class="mt-1" @change="applyEmqxProfile" />
                            <span>
                              <span class="text-white text-sm font-medium">EMQX Edge — recomendado</span>
                              <p class="text-[11px] text-slate-400">Broker local-first: MQTT en LAN+VPN, WSS público, dashboard privado.</p>
                            </span>
                          </label>
                          <label class="flex items-start gap-2 cursor-pointer">
                            <input type="radio" value="custom" v-model="emqxProfile" class="mt-1" @change="applyEmqxProfile" />
                            <span>
                              <span class="text-white text-sm font-medium">Personalizado</span>
                              <p class="text-[11px] text-slate-400">Canales independientes por listener.</p>
                            </span>
                          </label>
                        </div>
                        <div v-if="emqxProfile === 'edge'" class="text-[10px] text-slate-300 font-mono space-y-1 pt-1 border-t border-white/5">
                          <div>MQTT 1883 — ✓ cluster ✓ LAN ✓ Tailscale ✗ Internet</div>
                          <div>WebSocket 8083 — ✓ cluster ✓ LAN ✓ Tailscale ✓ WSS público</div>
                          <div>Dashboard 18083 — ✓ cluster ✓ LAN ✓ Tailscale ✗ Internet</div>
                        </div>
                      </div>

                      <p class="text-xs text-blue-400/80 flex items-center gap-1 mb-1">
                        📡 Canales por puerto (multi-canal). Public no aplica a MQTT TCP.
                      </p>
                      <div class="overflow-x-auto">
                        <table class="w-full text-[11px]">
                          <thead>
                            <tr class="border-b border-white/10">
                              <th class="text-left text-slate-500 font-medium py-1.5 pr-2 w-32">Port</th>
                              <th v-for="env in allEnvironments" :key="'th-' + env"
                                  class="text-center py-1.5 px-1">
                                <span :class="['text-[10px] px-2.5 py-0.5 rounded font-bold', envBadgeColors[env]]">{{ env }}</span>
                              </th>
                            </tr>
                          </thead>
                          <tbody>
                            <tr v-for="p in templatePorts" :key="p.name" class="border-b border-white/5">
                              <td class="py-2.5 pr-2">
                                <div class="flex flex-col">
                                  <span class="text-white font-semibold text-xs">{{ p.name }}</span>
                                  <span class="text-slate-600 text-[9px]">:{{ p.port }} {{ p.protocol }}</span>
                                  <span v-if="p.description" class="text-slate-700 text-[8px] truncate max-w-[110px]">{{ p.description }}</span>
                                </div>
                              </td>
                              <td v-for="env in allEnvironments" :key="env + '-' + p.name" class="py-1.5 px-0.5">
                                <div class="flex flex-col gap-[3px]">
                                  <label v-for="mode in channelOptionsForPort(p.name)" :key="mode.value"
                                      class="flex items-center gap-1 px-1.5 py-[3px] rounded border text-[10px] cursor-pointer"
                                      :class="hasPortChannel(env, p.name, mode.value)
                                        ? mode.activeClass
                                        : 'bg-slate-900/50 border-slate-800/50 text-slate-600'"
                                      :title="mode.disabledReason || ''">
                                    <input type="checkbox"
                                      :disabled="mode.disabled || emqxProfile === 'edge'"
                                      :checked="hasPortChannel(env, p.name, mode.value)"
                                      @change="togglePortChannel(env, p.name, mode.value, $event.target.checked)"
                                      class="w-3 h-3" />
                                    {{ mode.icon }} {{ mode.label }}
                                  </label>
                                </div>
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>

                    <!-- ── SIMPLE MODE: single exposure per env ── -->
                    <div v-else class="space-y-1.5">
                      <div v-for="env in allEnvironments" :key="'exp-' + env" class="flex items-center gap-2 p-1.5 rounded-lg bg-slate-900/30 border border-white/5">
                        <span :class="['text-[10px] font-bold px-2 py-0.5 rounded w-16 text-center shrink-0', envBadgeColors[env]]">{{ env }}</span>
                        <!-- Root-domain apps: prod is always public (locked) -->
                        <div v-if="useRootDomain && env === 'prod'" class="flex gap-1 flex-1">
                          <span class="px-2 py-1 rounded text-[11px] border flex-1 text-center bg-blue-600 border-blue-500 text-white cursor-not-allowed opacity-80">
                            🌐 Public (root domain)
                          </span>
                        </div>
                        <div v-else class="flex gap-1 flex-1">
                          <button v-for="mode in availableExposureModes" :key="mode.value"
                              type="button" @click="setEnvExposure(env, mode.value)"
                              :class="['px-2 py-1 rounded text-[11px] border transition-all flex-1 text-center',
                                         getEnvExposure(env) === mode.value
                                           ? 'bg-blue-600 border-blue-500 text-white'
                                           : 'bg-slate-900/50 border-slate-700/50 text-slate-500 hover:border-slate-500 hover:text-slate-300']">
                              {{ mode.icon }} {{ mode.label }}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <label class="block text-sm font-medium text-gray-300 mb-1">Pods (réplicas)</label>
                    <input v-model.number="form.specs.replicas" type="number" min="1" max="20" class="glass-input w-full" />
                    <p class="text-[11px] text-slate-500 mt-1">
                      Copias iguales del contenedor. Con 2+ nodos, k3s puede repartirlas si hay CPU/RAM libre.
                      Luego puedes cambiar este número en la app ya lanzada. Autoscaler min/max viene después.
                    </p>
                  </div>
              </div>
          </div>

          <!-- Protocol Support (backend apps only) -->
          <div v-if="selectedTemplate?.category === 'backend'" class="animate-fade-in">
            <label class="block text-sm font-medium text-gray-300 mb-2">
              Real-time Protocols
              <span class="text-xs text-slate-500 ml-2">auto-configures nginx ingress</span>
            </label>
            <div class="grid grid-cols-2 gap-2">
              <label v-for="proto in availableProtocols" :key="proto.value"
                     class="flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all"
                     :class="form.protocols.includes(proto.value)
                       ? 'border-blue-500 bg-blue-500/10'
                       : 'border-white/10 bg-white/5 hover:border-white/30'">
                <input type="checkbox" :value="proto.value" v-model="form.protocols" class="w-4 h-4 rounded bg-slate-700 border-slate-600 text-blue-500" />
                <div>
                  <div class="text-white text-sm font-medium">{{ proto.icon }} {{ proto.label }}</div>
                  <div class="text-xs text-slate-400">{{ proto.description }}</div>
                </div>
              </label>
            </div>
          </div>

          <div v-if="websocketTemplateField" class="pt-4 border-t border-white/10 mt-4 animate-fade-in">
            <label class="flex items-start gap-3 p-4 rounded-xl border border-cyan-500/20 bg-cyan-500/5 cursor-pointer">
              <input
                type="checkbox"
                v-model="form.template_config.enable_websocket"
                class="mt-0.5 rounded bg-slate-700 border-slate-600 text-cyan-500"
              />
              <div class="flex-1">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="text-sm font-medium text-cyan-300">Enable WebSocket</span>
                  <span class="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded bg-cyan-500/15 text-cyan-200 border border-cyan-500/25">
                    api endpoint
                  </span>
                </div>
                <p class="text-xs text-slate-400 mt-1 leading-relaxed">
                  {{ websocketFieldHelp }}
                </p>
              </div>
            </label>
          </div>

          <div v-if="selectedTemplate?.category === 'backend'" class="pt-4 border-t border-white/10 mt-4 animate-fade-in">
            <label
              class="flex items-center gap-3 p-3 rounded-lg border cursor-pointer"
              :class="availableDatabaseTargets.length > 0
                ? 'bg-slate-900/50 border-white/10'
                : 'bg-slate-900/30 border-white/5 opacity-60 cursor-not-allowed'"
            >
              <input
                type="checkbox"
                v-model="databaseBindingsEnabled"
                :disabled="availableDatabaseTargets.length === 0"
                class="rounded bg-slate-700 border-slate-600 text-blue-500"
              />
              <div class="flex-1">
                <div class="text-white text-sm font-medium flex items-center gap-2">
                  <span>Use existing databases</span>
                  <span v-if="availableDatabaseTargets.length > 0" class="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/15 text-blue-300 border border-blue-500/30">
                    {{ availableDatabaseTargets.length }} available
                  </span>
                </div>
                <div class="text-xs text-slate-400">
                  <template v-if="availableDatabaseTargets.length > 0">
                    Map each backend environment to one or more database environments. The deployer pulls credentials from Vault and injects <code class="text-blue-300">{ALIAS}_URI</code>, <code class="text-blue-300">{ALIAS}_HOST</code>, etc. into the backend.
                  </template>
                  <template v-else>
                    No databases registered yet. Deploy one (MongoDB, Postgres, MySQL, Redis...) first and it will show up here per environment.
                  </template>
                </div>
              </div>
              <router-link
                v-if="availableDatabaseTargets.length === 0"
                to="/wizard?mode=config-only"
                class="text-xs px-2 py-1 rounded bg-emerald-500/15 text-emerald-300 border border-emerald-500/30 hover:bg-emerald-500/25 whitespace-nowrap"
              >
                + Deploy DB
              </router-link>
            </label>

            <div v-if="databaseBindingsEnabled && availableDatabaseTargets.length > 0" class="mt-4 space-y-4">
              <div v-for="env in allEnvironments" :key="'dbbind-' + env" class="rounded-lg border border-white/10 bg-white/5 p-3">
                <div class="flex items-center justify-between gap-3 mb-3">
                  <div class="flex items-center gap-2">
                    <span :class="['text-[10px] font-bold px-2 py-0.5 rounded', envBadgeColors[env]]">{{ env }}</span>
                    <span class="text-sm text-slate-300">backend connects to</span>
                  </div>
                  <button type="button" @click="addDatabaseBinding(env)" class="text-xs px-2 py-1 rounded bg-blue-500/20 text-blue-200 border border-blue-500/30 hover:bg-blue-500/30">
                    Add DB
                  </button>
                </div>

                <div v-if="!form.database_bindings[env]?.length" class="text-xs text-slate-500">
                  No database selected for this environment.
                </div>

                <div v-for="(binding, index) in form.database_bindings[env]" :key="'dbbind-row-' + env + '-' + index" class="grid grid-cols-1 md:grid-cols-[1fr_140px_32px] gap-2 mb-2">
                  <select v-model="binding.target" @change="applyDatabaseTarget(env, index)" class="glass-input w-full">
                    <option value="">Select database...</option>
                    <option v-for="target in availableDatabaseTargets" :key="target.key" :value="target.key">
                      {{ target.label }}
                    </option>
                  </select>
                  <input v-model="binding.alias" type="text" placeholder="alias" class="glass-input w-full text-sm" />
                  <button type="button" @click="removeDatabaseBinding(env, index)" class="rounded bg-red-500/10 text-red-300 border border-red-500/20 hover:bg-red-500/20">
                    x
                  </button>
                </div>

                <div v-if="form.database_bindings[env]?.length" class="mt-2 text-[10px] text-slate-500 font-mono">
                  <span class="text-slate-400">Will inject:</span>
                  <span v-for="(binding, idx) in form.database_bindings[env]" :key="'preview-' + env + '-' + idx" class="ml-2 text-blue-300">
                    {{ aliasForPreview(binding.alias) }}_URI{{ idx < form.database_bindings[env].length - 1 ? ',' : '' }}
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div>
             <label class="block text-sm font-medium text-gray-300 mb-1">Description</label>
             <textarea v-model="form.description" rows="3" class="glass-input w-full" placeholder="What does this app do?"></textarea>
          </div>

          <!-- Dynamic Template Configuration -->
          <div v-if="visibleTemplateSchema" class="pt-4 border-t border-white/10 mt-4 animate-fade-in">
              <h3 class="text-sm font-medium text-blue-400 mb-4 flex items-center gap-2">
                <span>⚡</span> Template Configuration
              </h3>
              <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div v-for="(field, key) in visibleTemplateSchema" :key="key">
                    <label class="block text-sm font-medium text-gray-300 mb-1 capitalize">{{ field.label || key.replace(/_/g, ' ') }}</label>
                      
                      <!-- Select -->
                      <div v-if="field.type === 'select'" class="relative">
                        <select v-model="form.template_config[key]" class="glass-input w-full appearance-none cursor-pointer">
                            <option v-for="opt in field.options" :key="opt" :value="opt">{{ opt }}</option>
                        </select>
                        <div class="absolute inset-y-0 right-0 flex items-center px-2 pointer-events-none text-slate-400">
                          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"></path></svg>
                        </div>
                      </div>
                      
                      <!-- Number -->
                      <input v-else-if="field.type === 'number'" type="number" 
                            v-model.number="form.template_config[key]" 
                            :min="field.min" :max="field.max"
                            class="glass-input w-full" />
                            
                      <!-- Checkbox (Boolean) -->
                      <label v-else-if="field.type === 'boolean'" class="flex items-center gap-3 p-3 rounded-lg bg-slate-900/50 border border-white/5 cursor-pointer">
                          <input type="checkbox" v-model="form.template_config[key]" class="rounded bg-slate-700 border-slate-600 text-blue-500" />
                          <span class="text-sm text-slate-300">{{ field.label || key.replace(/_/g, ' ') }}</span>
                      </label>

                      <!-- String/Default -->
                      <input v-else type="text" v-model="form.template_config[key]" class="glass-input w-full" />
                      
                      <p v-if="field.description" class="text-xs text-slate-500 mt-1">{{ field.description }}</p>
                  </div>
              </div>
          </div>

        </div>

        <!-- Step 2: Review -->
        <div v-if="step === 3" class="space-y-4 animate-fade-in">
             <!-- Creation Mode Badge -->
             <div :class="['rounded-lg p-4 border', creationModeBadge.classes]">
                <div class="flex items-center gap-3">
                  <span class="text-2xl">{{ creationModeBadge.icon }}</span>
                  <div>
                    <h3 :class="['font-semibold', creationModeBadge.textClass]">{{ creationModeBadge.title }}</h3>
                    <p class="text-sm text-slate-400">{{ creationModeBadge.description }}</p>
                  </div>
                </div>
             </div>

             <div class="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
                <h3 class="text-blue-400 font-semibold mb-2">Summary</h3>
                <dl class="grid grid-cols-2 gap-4 text-sm">
                    <div class="col-span-1">
                        <dt class="text-slate-500">Name</dt>
                        <dd class="text-white font-medium">{{ form.name }}</dd>
                    </div>
                     <div class="col-span-1">
                        <dt class="text-slate-500">Template</dt>
                        <dd class="text-white font-medium">{{ selectedTemplate?.name || form.template }}</dd>
                    </div>
                     <div class="col-span-2">
                        <dt class="text-slate-500 mb-2">Environments</dt>
                        <dd class="flex gap-2">
                            <span v-for="env in allEnvironments" :key="env" 
                                  :class="['px-3 py-1 rounded-lg text-sm font-medium', envBadgeColors[env]]">
                                {{ envLabels[env] }}
                            </span>
                        </dd>
                    </div>
                     <div class="col-span-1">
                        <dt class="text-slate-500 mb-1">Exposure</dt>
                        <dd class="space-y-1">
                          <!-- Multi-port exposure summary -->
                          <template v-if="isMultiPort && form.exposure.port_exposure">
                            <div v-for="env in allEnvironments" :key="'rev-mp-' + env" class="mb-2">
                              <div class="flex items-center gap-1.5 mb-1">
                                <span :class="['text-[9px] font-bold px-1.5 py-0.5 rounded', envBadgeColors[env]]">{{ env }}</span>
                              </div>
                              <div class="ml-5 space-y-0.5">
                                <div v-for="p in templatePorts" :key="p.name" class="flex items-center gap-2 text-[10px]">
                                  <span class="text-slate-500 w-20 truncate">{{ p.name }} :{{ p.port }}</span>
                                  <span :class="['px-1.5 py-0.5 rounded text-[9px] font-medium',
                                    getPortExposure(env, p.name) === 'public' ? 'bg-emerald-500/20 text-emerald-400' :
                                    getPortExposure(env, p.name) === 'tailscale' ? 'bg-purple-500/20 text-purple-400' :
                                    'bg-slate-500/20 text-slate-400']">
                                    {{ getPortExposure(env, p.name) === 'tailscale' ? 'Private' : getPortExposure(env, p.name) }}
                                  </span>
                                </div>
                              </div>
                            </div>
                          </template>
                          <!-- Simple exposure summary -->
                          <template v-else>
                            <div v-for="env in allEnvironments" :key="'rev-' + env" class="flex items-center gap-1.5">
                              <span :class="['text-[9px] font-bold px-1.5 py-0.5 rounded', envBadgeColors[env]]">{{ env }}</span>
                              <span class="text-white text-xs capitalize">{{ getEnvExposure(env) }}</span>
                            </div>
                          </template>
                        </dd>
                    </div>
                     <div class="col-span-1">
                        <dt class="text-slate-500">Scale</dt>
                        <dd class="text-white font-medium">{{ form.specs.replicas }} pods (copias)</dd>
                    </div>

                    <!-- Dynamic Config Summary -->
                    <div v-if="Object.keys(form.template_config).length > 0" class="col-span-2 pt-2 border-t border-blue-500/20 mt-2">
                       <dt class="text-slate-500 mb-2">Template Configuration</dt>
                       <dd class="grid grid-cols-2 gap-2">
                           <div v-for="(val, key) in form.template_config" :key="key" class="bg-slate-900/50 px-3 py-1.5 rounded border border-white/5 flex flex-col">
                               <span class="text-[10px] text-slate-500 uppercase font-bold tracking-wider">{{ key.replace(/_/g, ' ') }}</span>
                               <span class="text-white font-mono text-xs">{{ val }}</span>
                           </div>
                       </dd>
                    </div>
                </dl>
             </div>
             
             <div class="flex items-center gap-3 p-4 bg-slate-900/50 rounded-lg border border-slate-700/50">
                 <div class="text-2xl">🚀</div>
                 <div>
                     <p class="text-white text-sm font-medium">Ready to Deploy to {{ allEnvironments.length }} environment(s)?</p>
                     <p class="text-slate-400 text-xs" v-if="form.creation_mode === 'scaffold'">This will create the repository with template code, pipeline, and GitOps manifests.</p>
                     <p class="text-slate-400 text-xs" v-else-if="form.creation_mode === 'empty'">This will create an empty repo. After deploy, clone it, add your code, and push to trigger the pipeline.</p>
                     <p class="text-slate-400 text-xs" v-else>This will create GitOps manifests and deploy the official Docker image.</p>
                 </div>
             </div>

             <!-- Instructions for Empty Mode -->
             <div v-if="form.creation_mode === 'empty'" class="bg-purple-500/10 border border-purple-500/30 rounded-lg p-4">
                <h4 class="text-purple-400 font-semibold mb-2 flex items-center gap-2">
                  <span>📋</span> Next Steps After Deploy
                </h4>
                <ol class="text-sm text-slate-300 space-y-2 list-decimal list-inside">
                  <li>Clone the repository: <code class="bg-slate-800 px-2 py-1 rounded text-xs">git clone {{ repoCloneUrl }}</code></li>
                  <li>Add your code and a Dockerfile</li>
                  <li>Push to main branch to trigger the pipeline</li>
                  <li>The pipeline will build and deploy automatically</li>
                </ol>
             </div>
        </div>

        <!-- Step 3: Deployment Progress with Terminal -->
        <div v-if="step === 4" class="w-full">
             <div class="text-center mb-6">
                 <h3 class="text-xl font-bold text-white mb-2">Deploying {{ form.name }}...</h3>
                 <p class="text-slate-400 text-sm">Initializing factory workers and building your app.</p>
             </div>

             <!-- Terminal Window -->
             <div class="bg-[#0d1117] rounded-lg border border-slate-700 overflow-hidden font-mono text-xs md:text-sm shadow-2xl">
                 <!-- Terminal Header -->
                 <div class="flex items-center justify-between px-4 py-2 bg-slate-800 border-b border-slate-700">
                     <div class="flex gap-2">
                         <div class="w-3 h-3 rounded-full bg-red-500"></div>
                         <div class="w-3 h-3 rounded-full bg-yellow-500"></div>
                         <div class="w-3 h-3 rounded-full bg-green-500"></div>
                     </div>
                     <div class="text-slate-400 text-xs">kaanbal-engine-cli — node</div>
                     <div></div>
                 </div>
                 
                 <!-- Terminal Body -->
                 <div class="p-4 h-64 overflow-y-auto space-y-2" ref="terminalBody">
                     <div v-for="(log, index) in deployLogs" :key="index" class="font-mono">
                         <span class="text-slate-500">[{{ log.time }}]</span>
                         <span :class="log.color || 'text-slate-300'"> {{ log.message }}</span>
                     </div>
                     <div v-if="loading" class="animate-pulse text-blue-400">_</div>
                 </div>
             </div>
        </div>

         <!-- Step 4: Success -->
        <div v-if="step === 5" class="text-center py-8">
             <div class="mb-6 text-6xl">✨</div>
             <h3 class="text-xl font-bold text-white mb-2">
               {{ form.creation_mode === 'empty' ? 'Repository Created!' : 'Deployed Successfully!' }}
             </h3>
             <p class="text-slate-400 mb-6">
               {{ form.creation_mode === 'empty' 
                  ? 'Clone the repo, add your code, and push to deploy.' 
                  : 'Your app is now provisioning in the cluster.' }}
             </p>
             
             <!-- Empty mode: show clone command -->
             <div v-if="form.creation_mode === 'empty' && deployResult?.repo_url" class="max-w-md mx-auto mb-6 bg-slate-800 rounded-lg p-4 text-left">
               <p class="text-xs text-slate-500 mb-2">Clone command:</p>
               <code class="text-sm text-emerald-400 break-all">git clone {{ deployResult.repo_url }}</code>
             </div>
             
             <div class="flex justify-center gap-4">
                 <router-link to="/apps" class="glass-button bg-slate-700 hover:bg-slate-600">View Apps</router-link>
                 <a v-if="deployResult?.repo_url" :href="deployResult.repo_url.replace('.git', '')" target="_blank" class="glass-button">View Repository</a>
             </div>
        </div>

      </div>

      <!-- Footer -->
      <div v-if="step < 4" class="px-6 py-4 bg-black/20 border-t border-white/10 flex justify-between items-center">
         <button v-if="step > 1" @click="step--" class="text-gray-400 hover:text-white px-4 py-2 transition-colors">Back</button>
         <div v-else></div>

         <button v-if="step === 1" @click="nextStep" :disabled="!form.creation_mode" class="glass-button disabled:opacity-50 disabled:cursor-not-allowed">Next</button>
         <button v-if="step === 2" @click="nextStep" :disabled="!isFormValid" class="glass-button disabled:opacity-50 disabled:cursor-not-allowed">Next</button>
         <button v-if="step === 3" @click="deploy" :disabled="loading" class="bg-gradient-to-r from-blue-600 to-purple-600 hover:from-blue-500 hover:to-purple-500 text-white px-8 py-2.5 rounded-lg font-bold shadow-lg shadow-blue-900/20 transform hover:-translate-y-0.5 transition-all flex items-center">
            <span v-if="loading" class="animate-spin mr-2">⚙️</span>
            {{ loading ? 'Igniting...' : 'Launch App' }}
         </button>
      </div>
      
      <!-- Error Message -->
      <div v-if="errorMessage" class="p-4 bg-red-900/50 border-t border-red-500/20 text-center text-sm font-medium text-red-200">
          {{ errorMessage.replace(/https:\/\/[^@]+@/g, 'https://***@') }}
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import axios from 'axios'
import { getConfig } from '@/config'
import { allocateHomepageName, siteGroup } from '@/services/sites'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()

const step = ref(1)
const loading = ref(false)
const loadingTemplates = ref(true)
const errorMessage = ref('')
const deployResult = ref(null)
const credentialsOk = ref(true)
const templates = ref([])
const existingApps = ref([])
const databaseBindingsEnabled = ref(false)
const deployLogs = ref([])
const terminalBody = ref(null)
const templateSearch = ref('')
const templateCategoryFilter = ref('')
const useRootDomain = ref(false)

// Environment config
const envLabels = { dev: 'Development', staging: 'Staging', prod: 'Production' }
const envColors = { dev: 'text-yellow-400', staging: 'text-orange-400', prod: 'text-emerald-400' }
const envBadgeColors = {
    dev: 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30',
    staging: 'bg-orange-500/20 text-orange-400 border border-orange-500/30',
    prod: 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
}
const envDescriptions = {
    dev: 'For testing and development. Changes can be made freely.',
    staging: 'Pre-production testing. Mirror of production environment.',
    prod: 'Live production environment. Handle with care.'
}

const form = reactive({
    name: '',
    template: '',
  app_group: '',
    description: '',
    creation_mode: 'scaffold',  // scaffold, empty, config-only
    protocols: [],
    template_config: {},
    database_bindings: {},
    environments: [],  // Additional envs (dev, staging) - prod is always added automatically
    specs: {
        replicas: 1,
        port: 80,
        resources: {
            cpu_request: "100m",
            cpu_limit: "500m",
            mem_request: "128Mi",
            mem_limit: "512Mi"
        }
    },
    domain_id: null,
    exposure: {
        type: 'internal',
        public_path: '/',
        tailscale_hostname: null,
        per_env: {},
        // Multi-port support
        ports: null,          // [{name,port,protocol,description}] from template
        port_exposure: null   // { env: { portName: 'public'|'tailscale'|... } }
    }
})

// Computed: all environments (prod + selected additional)
const allEnvironments = computed(() => {
    // prod is ALWAYS included, plus any additional selected
    const envs = [...form.environments]
    if (!envs.includes('prod')) {
        envs.push('prod')
    }
    // Sort: dev, staging, prod
    return envs.sort((a, b) => {
        const order = { dev: 0, staging: 1, prod: 2 }
        return order[a] - order[b]
    })
})

  const repoCloneUrl = computed(() => {
    const name = form.name || '<app-name>'
    const provider = getConfig('gitProvider', 'bitbucket')
    const namespace = getConfig('gitNamespace', '')

    if (provider === 'github') {
      const org = namespace || '<org>'
      return `https://github.com/${org}/${name}.git`
    }

    const workspace = namespace || '<workspace>'
    return `https://bitbucket.org/${workspace}/${name}.git`
  })

// Computed for selected template details
const selectedTemplate = computed(() => {
    return templates.value.find(t => t.id === form.template)
})

// Computed for creation mode badge
const creationModeBadge = computed(() => {
    const modes = {
        'scaffold': {
            icon: '🏗️',
            title: 'Scaffold from Template',
            description: 'Will create repo with template code and configured pipeline',
            classes: 'bg-blue-500/10 border-blue-500/30',
            textClass: 'text-blue-400'
        },
        'empty': {
            icon: '📁',
            title: 'Empty Repository',
            description: 'Will create empty repo - you clone, add code, and push',
            classes: 'bg-purple-500/10 border-purple-500/30',
            textClass: 'text-purple-400'
        },
        'config-only': {
            icon: '⚙️',
            title: 'Config Only (No Code)',
            description: 'Will deploy using official Docker image - no code repo',
            classes: 'bg-emerald-500/10 border-emerald-500/30',
            textClass: 'text-emerald-400'
        }
    }
    return modes[form.creation_mode] || modes['scaffold']
})

// Computed for selected template schema
const templateSchema = computed(() => {
    if (!selectedTemplate.value || !selectedTemplate.value.config_schema) return null
    return selectedTemplate.value.config_schema
})

const visibleTemplateSchema = computed(() => {
    if (!templateSchema.value) return null
    const entries = Object.entries(templateSchema.value).filter(([key]) => {
    if (selectedTemplate.value?.category === 'backend' && key === 'database') return false
    if (key === 'enable_websocket') return false
    return true
    })
    return Object.fromEntries(entries)
})

const websocketTemplateField = computed(() => {
  if (selectedTemplate.value?.id !== 'fastapi-api') return null
  return templateSchema.value?.enable_websocket || null
})

const websocketFieldHelp = computed(() => {
  const field = websocketTemplateField.value
  if (!field) return ''
  return field.help || 'Adds a /ws endpoint and test client for real-time traffic.'
})

// Computed for template env_vars definition (Docker Hub services)
const templateEnvVars = computed(() => {
    if (!selectedTemplate.value || !selectedTemplate.value.env_vars) return null
    return selectedTemplate.value.env_vars.filter(ev => !ev.secret)
})

// Computed: template has user-configurable env vars
const hasEnvVars = computed(() => {
    return templateEnvVars.value && templateEnvVars.value.length > 0
})

const availableProtocols = [
  { value: 'http', label: 'HTTP', icon: '🌐', description: 'Standard REST traffic' },
  { value: 'websocket', label: 'WebSocket', icon: '🔌', description: 'Persistent bidirectional connection' },
  { value: 'grpc', label: 'gRPC', icon: '⚡', description: 'Low-latency binary RPC' },
  { value: 'tcp', label: 'TCP', icon: '📡', description: 'Raw TCP service endpoints' }
]

const normalizeAlias = (value) => {
  return (value || '')
    .toString()
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '') || 'db'
}

const aliasForPreview = (value) => normalizeAlias(value).toUpperCase()

const addDatabaseBinding = (env) => {
  if (!form.database_bindings[env]) form.database_bindings[env] = []
  form.database_bindings[env].push({ target: '', app_name: '', env: '', template: '', alias: 'db' })
}

const removeDatabaseBinding = (env, index) => {
  if (!form.database_bindings[env]) return
  form.database_bindings[env].splice(index, 1)
}

const applyDatabaseTarget = (env, index) => {
  const row = form.database_bindings?.[env]?.[index]
  if (!row?.target) return
  const selected = availableDatabaseTargets.value.find(t => t.key === row.target)
  if (!selected) return
  row.app_name = selected.app_name
  row.env = selected.env
  row.template = selected.template
  if (!row.alias || row.alias === 'db') row.alias = normalizeAlias(selected.app_name)
}

const databaseApps = computed(() => {
    return existingApps.value.filter(app => {
      if (app.category === 'database') return true
      const tpl = (app.template || '').toLowerCase()
      return ['mongo', 'postgres', 'mysql', 'mariadb', 'redis', 'db'].some(token => tpl.includes(token))
    })
})

const availableDatabaseTargets = computed(() => {
    const targets = []
    databaseApps.value.forEach(app => {
        const envs = app.environments?.length ? app.environments : ['prod']
        envs.forEach(env => {
            targets.push({
                key: `${app.name}::${env}`,
                label: `${app.name} / ${env} (${app.template || 'database'})`,
                app_name: app.name,
                env,
                template: app.template || 'database'
            })
        })
    })
    return targets
})
// All possible exposure modes with labels (bitácora Fase 0)
const allExposureModes = {
    public:    { value: 'public',    label: 'Public',   icon: '🌐' },
    tailscale: { value: 'tailscale', label: 'VPN',      icon: '🔒' },
    lan:       { value: 'lan',       label: 'LAN',      icon: '📡' },
    internal:  { value: 'internal',  label: 'Cluster',  icon: '🏠' },
    off:       { value: 'off',       label: 'Off',      icon: '⏹' },
    both:      { value: 'both',      label: 'Mixed',    icon: '🔀' }
}

// Simplified exposure modes for multi-port matrix (per-port level)
const portExposureModes = [
    { value: 'public',    label: 'Public',   icon: '🌐', activeClass: 'bg-emerald-600 border-emerald-500 text-white' },
    { value: 'tailscale', label: 'Private',  icon: '🔒', activeClass: 'bg-purple-600 border-purple-500 text-white' },
    { value: 'lan',       label: 'LAN',      icon: '📡', activeClass: 'bg-sky-600 border-sky-500 text-white' },
    { value: 'internal',  label: 'Cluster',  icon: '🏠', activeClass: 'bg-slate-600 border-slate-500 text-white' },
    { value: 'off',       label: 'Off',      icon: '⏹', activeClass: 'bg-rose-900 border-rose-700 text-white' }
]

// Computed: available exposure modes based on selected template's category
const availableExposureModes = computed(() => {
    const tpl = selectedTemplate.value
    if (!tpl) return [allExposureModes.public, allExposureModes.tailscale]

    // v1 create UX: one channel per env (Public OR VPN). Do NOT lock to
    // template.exposure.mode (that forced n8n into confusing Mixed-only).
    // template.exposure.mode is only used as the default when selecting the template.
    const categoryDefaults = {
        database:   ['internal', 'tailscale', 'lan', 'off'],
        monitoring: ['tailscale', 'lan', 'off'],
        devtools:   ['tailscale', 'lan', 'off'],
        // workflow (n8n): full Public or full VPN per env — no Mixed/path-split in v1
        workflow:   ['public', 'tailscale'],
        frontend:   ['public', 'tailscale', 'lan', 'off'],
        backend:    ['internal', 'tailscale', 'public', 'lan', 'off'],
        iot:        ['internal', 'tailscale', 'public', 'lan', 'off'],
        messaging:  ['internal', 'tailscale', 'public', 'lan', 'off']
    }

    const category = tpl.category
    const allowed = categoryDefaults[category] || ['public', 'tailscale', 'lan', 'off']
    return allowed.map(m => allExposureModes[m]).filter(Boolean)
})

// ── Multi-dominio ─────────────────────────────────────────────────────────
const availableDomains = ref([])

const loadDomains = async () => {
    try {
        const { data } = await axios.get('/api/v1/domains')
        availableDomains.value = data || []
        if (!form.domain_id) {
            const preferred = availableDomains.value.find(d => d.is_default) || availableDomains.value[0]
            form.domain_id = preferred?._id || null
        }
    } catch (e) {
        // Sin dominios listados el wizard sigue funcionando: el API cae al
        // dominio default de la instalación.
        console.error('Failed to load domains:', e)
    }
}

// El dominio solo cambia algo si la app sale a internet; en tailscale/lan/internal
// el FQDN público no se usa.
const hasPublicExposure = computed(() => {
    const perEnv = form.exposure.per_env || {}
    const modes = Object.values(perEnv)
    if (modes.length === 0) return ['public', 'both'].includes(form.exposure.type)
    return modes.some(m => ['public', 'both'].includes(m))
})

const previewPublicHost = computed(() => {
    const domain = availableDomains.value.find(d => d._id === form.domain_id)
    const fqdn = domain?.fqdn || 'dominio'
    // El homepage ocupa la raíz: su prod no lleva el nombre de la app delante.
    if (useRootDomain.value) return fqdn
    return form.name ? `${form.name}.${fqdn}` : `<app>.${fqdn}`
})

// Computed: hint text for exposure
const exposureHint = computed(() => {
    const tpl = selectedTemplate.value
    if (!tpl) return ''

    const hints = {
        database: 'Databases should stay internal or VPN. Never expose publicly.',
        monitoring: 'Monitoring tools should be VPN only.',
        devtools: 'Admin tools should be VPN only.',
        workflow: 'Elige Public o VPN completo por ambiente (sin partir rutas). Ej: prod=Public, staging=VPN.',
        frontend: 'Frontends are public or VPN. Internal access has no use for a UI.',
        backend: 'APIs can be internal (cluster only), VPN (private access), or public.',
        messaging: 'MQTT ports can be public for devices. Dashboard should stay VPN (Tailscale).',
        iot: 'Dashboard/MQTT: Public or VPN per environment (full channel).'
    }
    return hints[tpl.category] || ''
})

// Template icon mapping
const getTemplateIcon = (iconId) => {
    const icons = {
      vue: '🟢', react: '⚛️', angular: '🅰️', next: '▲',
      python: '🐍', nodejs: '💚', nestjs: '🔺', laravel: '🔻',
      django: '🟤', flask: '⚗️', go: '🔵',
      mongodb: '🍃', mysql: '🐬', postgres: '🐘', redis: '🔴',
      n8n: '🔄', grafana: '📊', mosquitto: '📡', emqx: '📡'
    }
    return icons[iconId] || '📦'
}

const categoryIcons = {
    frontend: '🎨', backend: '⚙️', database: '💾', workflow: '🔄',
    iot: '📡', monitoring: '📊', devtools: '🛠️', fullstack: '📚', messaging: '📡'
}

// Multi-dominio: la raíz es la del dominio elegido, no la de la instalación.
const selectedDomainFqdn = computed(() =>
  availableDomains.value.find(d => d._id === form.domain_id)?.fqdn || null
)

const rootDomainHost = computed(() => {
  if (selectedDomainFqdn.value) return selectedDomainFqdn.value
  const configured = getConfig('domain', '')
  if (configured) return configured
  return window.location.hostname.replace(/^kaanbal-console\./, '')
})

// Mismo nombre que asigna la API (domain_service.root_app_candidates): '<sitio>-homepage',
// o 'northwind-store-homepage' si otro dominio ya tomó 'northwind-homepage'. Antes el Wizard
// mandaba siempre 'homepage' y el homepage de un segundo dominio chocaba con el del primero.
const rootNamePreview = computed(() =>
  allocateHomepageName(rootDomainHost.value, existingApps.value.map(app => app.name))
)

// Una app raíz por dominio: cada cliente puede tener su propio sitio en la raíz
// de su dominio. Antes el límite era uno por instalación.
const existingRootApp = computed(() => {
  const defaultId = availableDomains.value.find(d => d.is_default)?._id || null
  const targetId = form.domain_id || defaultId
  const found = existingApps.value.find(app =>
    app.is_root_domain && ((app.domain?.id || app.domain_id || defaultId) === targetId)
  )
  return found ? found.name : null
})

// Cambiar a un dominio cuya raíz ya está ocupada invalida la elección anterior.
watch(existingRootApp, (taken) => {
  if (taken && useRootDomain.value) useRootDomain.value = false
})

const supportsRootDomain = computed(() => {
  const category = selectedTemplate.value?.category
  return category === 'frontend' && !existingRootApp.value
})

// Available categories from filtered templates
const availableCategories = computed(() => {
    const cats = [...new Set(filteredTemplates.value.map(t => t.category).filter(Boolean))]
    const order = ['frontend', 'backend', 'database', 'workflow', 'iot', 'monitoring', 'devtools']
    return cats.sort((a, b) => (order.indexOf(a) === -1 ? 99 : order.indexOf(a)) - (order.indexOf(b) === -1 ? 99 : order.indexOf(b)))
})

// Templates filtered by search + category filter
const displayedTemplates = computed(() => {
    let tpls = filteredTemplates.value
    if (templateCategoryFilter.value) {
        tpls = tpls.filter(t => t.category === templateCategoryFilter.value)
    }
    if (templateSearch.value) {
        const q = templateSearch.value.toLowerCase()
        tpls = tpls.filter(t =>
            t.name?.toLowerCase().includes(q) ||
            t.description?.toLowerCase().includes(q) ||
          (Array.isArray(t.stack) && t.stack.some(s => String(s).toLowerCase().includes(q))) ||
            t.category?.toLowerCase().includes(q)
        )
    }
    return tpls.sort((a, b) => {
        if (a.status === 'ready' && b.status !== 'ready') return -1
        if (b.status === 'ready' && a.status !== 'ready') return 1
        if (a.popular && !b.popular) return -1
        if (b.popular && !a.popular) return 1
        return (a.name || '').localeCompare(b.name || '')
    })
})

  const appGroupSuggestions = computed(() => {
    const groups = new Set()
    existingApps.value.forEach(app => {
      const g = (app.app_group || '').toString().trim()
      if (g) groups.add(g)
    })
    return Array.from(groups).sort((a, b) => a.localeCompare(b))
  })

// Per-environment exposure helpers
const setEnvExposure = (env, type) => {
    if (!form.exposure.per_env) form.exposure.per_env = {}
    form.exposure.per_env[env] = type
}

const getEnvExposure = (env) => {
    return form.exposure.per_env?.[env] || form.exposure.type || 'internal'
}

// Multi-port support
const isMultiPort = computed(() => {
    const tpl = selectedTemplate.value
    return tpl?.ports && tpl.ports.length > 1
})

const isEmqxTemplate = computed(() => {
    const id = (selectedTemplate.value?.id || form.template || '').toLowerCase()
    return id.includes('emqx')
})

const emqxProfile = ref('edge')

const EDGE_CHANNELS = {
    mqtt: ['internal', 'lan', 'tailscale'],
    ws: ['internal', 'lan', 'tailscale', 'public'],
    dashboard: ['internal', 'lan', 'tailscale'],
}

const templatePorts = computed(() => {
    return selectedTemplate.value?.ports || []
})

const normalizeChannels = (value) => {
    if (!value) return []
    if (Array.isArray(value)) return [...new Set(value)]
    if (typeof value === 'string') return value === 'off' ? [] : [value]
    if (typeof value === 'object' && Array.isArray(value.channels)) return [...value.channels]
    return []
}

const setPortChannels = (env, portName, channels) => {
    if (!form.exposure.port_exposure) form.exposure.port_exposure = {}
    if (!form.exposure.port_exposure[env]) form.exposure.port_exposure[env] = {}
    let list = normalizeChannels(channels)
    if (portName === 'mqtt') list = list.filter(c => c !== 'public')
    form.exposure.port_exposure[env][portName] = list
}

const setPortExposure = (env, portName, type) => {
    // Legacy single-mode setter → replace channels with that one mode
    setPortChannels(env, portName, type ? [type] : [])
}

const getPortChannels = (env, portName) => {
    const raw = form.exposure.port_exposure?.[env]?.[portName]
    const list = normalizeChannels(raw)
    if (list.length) return list
    // fallback single mode string from env exposure
    const fallback = getEnvExposure(env)
    return fallback && fallback !== 'off' ? [fallback] : ['internal']
}

const getPortExposure = (env, portName) => {
    const ch = getPortChannels(env, portName)
    return ch[0] || getEnvExposure(env)
}

const hasPortChannel = (env, portName, channel) => {
    return getPortChannels(env, portName).includes(channel)
}

const togglePortChannel = (env, portName, channel, enabled) => {
    if (emqxProfile.value === 'edge') return
    if (channel === 'public' && portName === 'mqtt') return
    let list = getPortChannels(env, portName).filter(c => c !== channel)
    if (enabled) list.push(channel)
    if (!list.includes('internal')) list = ['internal', ...list]
    setPortChannels(env, portName, list)
}

const channelOptionsForPort = (portName) => {
    return [
        { value: 'internal', label: 'Cluster', icon: '🏠', activeClass: 'bg-slate-600 border-slate-500 text-white' },
        { value: 'lan', label: 'LAN', icon: '📡', activeClass: 'bg-sky-600 border-sky-500 text-white' },
        { value: 'tailscale', label: 'VPN', icon: '🔒', activeClass: 'bg-purple-600 border-purple-500 text-white' },
        {
            value: 'public',
            label: 'Internet',
            icon: '🌐',
            activeClass: 'bg-emerald-600 border-emerald-500 text-white',
            disabled: portName === 'mqtt',
            disabledReason: portName === 'mqtt' ? 'MQTT TCP no se publica en Internet (usa WSS)' : '',
        },
    ]
}

const applyEmqxProfile = () => {
    form.template_config.profile = emqxProfile.value
    if (emqxProfile.value !== 'edge') return
    allEnvironments.value.forEach(env => {
        Object.entries(EDGE_CHANNELS).forEach(([port, channels]) => {
            if (templatePorts.value.some(p => p.name === port)) {
                setPortChannels(env, port, channels)
            }
        })
    })
}

// Initialize config when template changes
watch(() => form.template, (newVal) => {
    // Reset config
    form.template_config = {}
    
    // Initialize defaults from schema
    if (newVal && templateSchema.value) {
        Object.entries(templateSchema.value).forEach(([key, field]) => {
            if (field.default !== undefined) {
                form.template_config[key] = field.default
            }
        })
    }
    
    // Set smart exposure default based on category
    const tpl = selectedTemplate.value
    if (tpl) {
        // Sync specs.port from template catalog (e.g. 8000 for FastAPI, 80 for Vue)
        if (tpl.port) {
            form.specs.port = tpl.port
        }

        // Prod-level default (what you'd expose to the world)
        const categoryExposureDefaults = {
            database: 'internal',
            monitoring: 'tailscale',
            devtools: 'tailscale',
            workflow: 'public',
            frontend: 'public',
            backend: 'public',
            iot: 'tailscale',
            messaging: 'tailscale'
        }
        const defaultExposure = categoryExposureDefaults[tpl.category] || 'public'
        // Prefer catalog default only if it is a simple channel (never Mixed)
        const tplMode = tpl.exposure?.mode
        form.exposure.type = (tplMode && tplMode !== 'both') ? tplMode : defaultExposure

        // Smart per-env: prod=public (or type), non-prod=VPN for web/workflow apps
        // so "2 ambientes: uno internet + uno VPN" is ready out of the box.
        form.exposure.per_env = {}
        const nonProdOverride = ['frontend', 'backend', 'workflow'].includes(tpl.category)
            ? 'tailscale'
            : null
        allEnvironments.value.forEach(env => {
            if (nonProdOverride && env !== 'prod') {
                form.exposure.per_env[env] = nonProdOverride
            } else {
                form.exposure.per_env[env] = form.exposure.type
            }
        })
        
        // Multi-port: populate ports and port_exposure from template
        if (tpl.ports && tpl.ports.length > 1) {
            form.exposure.ports = tpl.ports
            form.exposure.port_exposure = {}
            const isEmqx = (tpl.id || '').toLowerCase().includes('emqx')
            if (isEmqx) {
                emqxProfile.value = (form.template_config.profile || tpl.default_profile || 'edge')
                form.template_config.profile = emqxProfile.value
            }
            allEnvironments.value.forEach(env => {
                form.exposure.port_exposure[env] = {}
                tpl.ports.forEach(p => {
                    const perEnv = tpl.port_defaults?.[env]?.[p.name]
                    const flat = tpl.port_defaults?.[p.name]
                    const raw = perEnv || flat || defaultExposure
                    form.exposure.port_exposure[env][p.name] = Array.isArray(raw) ? [...raw] : [raw]
                })
            })
            if (isEmqx && emqxProfile.value === 'edge') {
                applyEmqxProfile()
            }
        } else {
            form.exposure.ports = null
            form.exposure.port_exposure = null
        }
    }
    
    // Don't auto-override creation_mode — user already chose it in step 1
    // Only override if current mode isn't supported by this template
    if (tpl && tpl.creation_modes && tpl.creation_modes.length > 0) {
       if (!tpl.creation_modes.includes(form.creation_mode)) {
           form.creation_mode = tpl.creation_modes[0]
       }
    }

    // Backend-only sections: reset state when switching to non-backend templates.
    if (tpl?.category !== 'backend') {
      form.protocols = []
      databaseBindingsEnabled.value = false
      form.database_bindings = {}
    }

    if (!supportsRootDomain.value) {
      useRootDomain.value = false
    }
})

  watch(useRootDomain, (enabled) => {
    if (!enabled) return
    // El nombre sale del dominio; si hiciera falta desempatar, la API agrega '-N'.
    form.name = rootNamePreview.value
    // El homepage abre un sitio: sin grupo, recibe el del sitio ('northwind-homepage' → 'northwind').
    if (!form.app_group) form.app_group = siteGroup(rootNamePreview.value)
    // Root-domain apps MUST have prod exposed as public (it IS the root domain).
    if (!form.exposure.per_env) form.exposure.per_env = {}
    form.exposure.per_env.prod = 'public'
  })

  // Cambiar de dominio con la raíz elegida cambia el sitio: nombre y grupo lo siguen.
  watch(rootNamePreview, (name, previous) => {
    if (!useRootDomain.value) return
    const previousGroup = siteGroup(previous)
    form.name = name
    if (!form.app_group || form.app_group === previousGroup) form.app_group = siteGroup(name)
  })

// Watch environments to auto-populate per_env for new envs
watch(() => [...form.environments], () => {
    if (!form.exposure.per_env) form.exposure.per_env = {}
    allEnvironments.value.forEach(env => {
        if (!(env in form.exposure.per_env)) {
            form.exposure.per_env[env] = form.exposure.type || 'internal'
        }
    })
    // Also populate port_exposure for multi-port templates
    if (form.exposure.ports && form.exposure.port_exposure) {
        allEnvironments.value.forEach(env => {
            if (!form.exposure.port_exposure[env]) {
                form.exposure.port_exposure[env] = {}
                form.exposure.ports.forEach(p => {
                    form.exposure.port_exposure[env][p.name] = form.exposure.type || 'internal'
                })
            }
        })
    }
}, { deep: true })

watch(databaseBindingsEnabled, (enabled) => {
  if (!enabled) {
    form.database_bindings = {}
    return
  }
  allEnvironments.value.forEach(env => {
    if (!form.database_bindings[env]) form.database_bindings[env] = []
  })
})

onMounted(async () => {
    const domainsLoaded = loadDomains()

    // Load templates from API
    try {
        const { data } = await axios.get('/api/v1/templates')
        templates.value = data
    } catch (e) {
        console.error('Failed to load templates:', e)
    } finally {
        loadingTemplates.value = false
    }

    // Apps existentes: nombres ocupados y apps raíz por dominio (existingRootApp).
    try {
        const { data } = await axios.get('/api/v1/apps')
        existingApps.value = data
    } catch (e) {
        // Non-critical — supportsRootDomain stays false if we can't check
    }
    
    // Check for pre-selected template from query
    if (route.query.template) {
        form.template = route.query.template
    }

    // Llegadas desde "Sitios web": el Wizard viene preconfigurado para el sitio.
    //   ?site=<domain_id>                       → homepage (raíz) de ese dominio
    //   ?domain_id=&group=&category=backend|database → API o base del sitio
    const DEFAULT_TEMPLATE_BY_CATEGORY = { frontend: 'vue3-spa', backend: 'fastapi-api', database: 'postgres' }
    // El nombre y la raíz del homepage salen del dominio elegido: hace falta la lista.
    await domainsLoaded
    // 'default' = el dominio de Kaanbal cuando la célula aún no lista dominios.
    const presetDomain = route.query.site || route.query.domain_id
    if (presetDomain && presetDomain !== 'default') form.domain_id = String(presetDomain)
    if (route.query.group) form.app_group = String(route.query.group)
    const presetCategory = route.query.site ? 'frontend' : route.query.category
    if (!form.template && presetCategory && DEFAULT_TEMPLATE_BY_CATEGORY[presetCategory]) {
        const wanted = templates.value.find(t => t.id === DEFAULT_TEMPLATE_BY_CATEGORY[presetCategory])
        if (wanted) {
            form.template = wanted.id
            // Las bases son imágenes oficiales (Config Only); el resto se genera del template.
            const modes = wanted.creation_modes || ['scaffold']
            form.creation_mode = modes.includes('scaffold') ? 'scaffold' : modes[0]
            // El sitio ya decidió qué crear: directo a la configuración.
            step.value = 2
        }
    }
    // API y base de un sitio se llaman como él ('north-star-bay-api'): así se sabe
    // de quién son también en GitHub, ArgoCD y Vault. Es solo una sugerencia editable.
    const SITE_PIECE_SUFFIX = { backend: 'api', database: 'db' }
    if (!route.query.site && route.query.group && SITE_PIECE_SUFFIX[presetCategory] && !form.name) {
        const taken = new Set(existingApps.value.map(app => String(app.name).toLowerCase()))
        const base = `${String(route.query.group).slice(0, 56)}-${SITE_PIECE_SUFFIX[presetCategory]}`
        let candidate = base
        for (let n = 2; taken.has(candidate); n++) candidate = `${base}-${n}`
        form.name = candidate
    }
    if (route.query.site) {
        // La casilla de raíz depende de que el template ya sea frontend.
        await nextTick()
        if (supportsRootDomain.value) useRootDomain.value = true
    }
    
    // Check credentials status
    try {
        const { data } = await axios.get('/api/v1/system/credentials/status')
        credentialsOk.value = data.configured
    } catch (e) {
        console.warn('Could not check credentials status')
    }
})

const isFormValid = computed(() => {
    return form.name.length > 2 && form.template
})

// Filtered templates based on selected creation mode
const filteredTemplates = computed(() => {
    if (!templates.value.length) return []
    return templates.value.filter(t => {
        if (!t.creation_modes) return true
        // Map 'config-only' to 'config-only' in template's creation_modes array
        return t.creation_modes.includes(form.creation_mode)
    })
})

const nextStep = () => {
    if (step.value === 1) {
        // Step 1 only needs a creation mode selected
        if (form.creation_mode) {
      // Keep preselected template (e.g. dashboard shortcut) when compatible.
      if (form.template) {
        const tpl = templates.value.find(t => t.id === form.template)
        const supportsMode = !tpl?.creation_modes || tpl.creation_modes.includes(form.creation_mode)
        if (!supportsMode) {
          form.template = ''
          form.template_config = {}
        }
      }
            templateSearch.value = ''
            templateCategoryFilter.value = ''
            step.value++
        }
    } else if (step.value === 2) {
        if (isFormValid.value) step.value++
    } else {
        step.value++
    }
}

const addLog = (message, color = 'text-slate-300') => {
    const time = new Date().toLocaleTimeString('en-US', { hour12: false })
    // Sanitize: strip any credential/token patterns that might leak
    let safeMsg = message
        .replace(/https:\/\/[^@]+@/g, 'https://***@')
        .replace(/ATATT[A-Za-z0-9_=-]+/g, '***')
        .replace(/:[A-Za-z0-9_=-]{20,}@/g, ':***@')
    deployLogs.value.push({ time, message: safeMsg, color })
    // Auto scroll
    setTimeout(() => {
        if (terminalBody.value) {
            terminalBody.value.scrollTop = terminalBody.value.scrollHeight
        }
    }, 10)
}

const deploy = async () => {
    loading.value = true
    errorMessage.value = ''
    step.value = 4
    deployLogs.value = []

    addLog('Initializing deployment sequence...')
    addLog(`Target: ${form.name} (${allEnvironments.value.join(', ')})`)

    try {
        const normalizedBindings = {}
        if (databaseBindingsEnabled.value) {
          allEnvironments.value.forEach(env => {
            const rows = (form.database_bindings?.[env] || [])
              .filter(r => r?.app_name && r?.env)
              .map(r => ({
                app_name: r.app_name,
                env: r.env,
                template: r.template,
                alias: normalizeAlias(r.alias)
              }))
            if (rows.length) normalizedBindings[env] = rows
          })
        }

        // Build payload
        const payload = {
            ...form,
            category: selectedTemplate.value?.category || null,
            environments: allEnvironments.value,
          creation_mode: form.creation_mode,
          protocols: selectedTemplate.value?.category === 'backend' ? form.protocols : [],
          database_bindings: normalizedBindings,
          template_config: {
            ...(form.template_config || {}),
            use_root_domain: useRootDomain.value
          }
        }

        // Step 1: Create app (returns immediately with app_id + stream_url)
        const response = await axios.post('/api/v1/apps', payload)
        const { id: appId, stream_url } = response.data
        deployResult.value = response.data

        addLog('App registered, connecting to deploy stream...', 'text-blue-400')

        // Step 2: Connect to SSE stream for real-time progress
        const sseUrl = (stream_url || `/api/v1/apps/${appId}/deploy/stream`)
        const evtSource = new EventSource(sseUrl)

        evtSource.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data)

                // Map status to terminal colors
                const colorMap = {
                    running: 'text-slate-300',
                    success: 'text-emerald-400',
                    warning: 'text-yellow-400',
                    error: 'text-red-500 font-bold'
                }
                const color = colorMap[data.status] || 'text-slate-300'
                const prefix = data.status === 'success' ? '✔ ' :
                               data.status === 'error' ? 'ERROR: ' :
                               data.status === 'warning' ? '⚠ ' : '> '

                addLog(`${prefix}${data.message}`, color)

                if (data.done) {
                    evtSource.close()

                    if (data.status === 'success') {
                        // Merge final deploy data
                        if (data.data) {
                            deployResult.value = { ...deployResult.value, ...data.data }
                        }
                        addLog('Deployment completed successfully!', 'text-emerald-300 font-bold')
                        setTimeout(() => { step.value = 5 }, 1500)
                    } else {
                        errorMessage.value = data.message || 'Deployment failed'
                        loading.value = false
                    }
                }
            } catch (parseErr) {
                console.warn('Failed to parse SSE event:', event.data)
            }
        }

        evtSource.onerror = () => {
            evtSource.close()
            // If we haven't received a completion event, fall back to polling
            if (loading.value && step.value === 4) {
                addLog('Stream disconnected, polling for status...', 'text-yellow-400')
                pollDeployStatus(appId)
            }
        }

    } catch (e) {
        console.error(e)
        const detail = e.response?.data?.detail
        let errorMsg = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map(d => d.msg || JSON.stringify(d)).join('; ') : JSON.stringify(detail || 'Deployment Failed')
        errorMsg = errorMsg
            .replace(/https:\/\/[^@]+@/g, 'https://***@')
            .replace(/ATATT[A-Za-z0-9_=-]+/g, '***')
        addLog(`ERROR: ${errorMsg}`, 'text-red-500 font-bold')
        errorMessage.value = errorMsg
        loading.value = false
    }
}

// Fallback: poll app status if SSE stream disconnects
const pollDeployStatus = async (appId) => {
    for (let i = 0; i < 60; i++) {
        await new Promise(r => setTimeout(r, 3000))
        try {
            const { data } = await axios.get(`/api/v1/apps/${form.name}`)
            if (data.status === 'running' || data.status === 'healthy') {
                deployResult.value = data
                addLog('Deployment completed.', 'text-emerald-400')
                setTimeout(() => { step.value = 5 }, 1000)
                return
            } else if (data.status === 'error') {
                addLog(`Deploy error: ${data.error || 'Unknown'}`, 'text-red-500')
                errorMessage.value = data.error || 'Deployment failed'
                loading.value = false
                return
            }
        } catch { /* continue polling */ }
    }
    addLog('Timed out waiting for deployment status', 'text-yellow-400')
    loading.value = false
}
</script>

<style scoped>
.animate-progress {
    animation: progress 2s ease-in-out infinite;
}

@keyframes progress {
    0% { transform: translateX(-100%); }
    100% { transform: translateX(100%); }
}

.custom-scrollbar::-webkit-scrollbar {
    width: 4px;
}
.custom-scrollbar::-webkit-scrollbar-track {
    background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
    background: rgba(255,255,255,0.1);
    border-radius: 2px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
    background: rgba(255,255,255,0.2);
}

.animate-fade-in {
    animation: fadeIn 0.3s ease-out;
}

@keyframes fadeIn {
    from { opacity: 0; transform: translateY(10px); }
    to { opacity: 1; transform: translateY(0); }
}
</style>
