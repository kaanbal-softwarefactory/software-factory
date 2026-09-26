<template>
  <div class="space-y-6">
    <div class="flex items-center justify-between">
      <div>
        <h1 class="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">Templates</h1>
        <p class="mt-2 text-slate-400">Launch new services from battle-tested blueprints.</p>
      </div>
      <div class="flex gap-2">
        <button @click="showCreateModal = true" class="glass-button text-sm flex items-center gap-2 bg-purple-600 hover:bg-purple-500">
          <span>✨</span>
          Create Custom
        </button>
        <button @click="refreshTemplates" :disabled="loading" class="glass-button text-sm flex items-center gap-2">
          <span :class="{'animate-spin': loading}">🔄</span>
          Refresh
        </button>
      </div>
    </div>

    <!-- Category Filter -->
    <div class="flex gap-2 flex-wrap">
      <button 
        @click="selectedCategory = null" 
        :class="['px-4 py-2 rounded-lg text-sm transition-all', !selectedCategory ? 'bg-blue-600 text-white' : 'bg-white/5 text-slate-400 hover:bg-white/10']"
      >
        All
      </button>
      <button 
        v-for="cat in categories" :key="cat.id"
        @click="selectedCategory = cat.id" 
        :class="['px-4 py-2 rounded-lg text-sm transition-all flex items-center gap-2', selectedCategory === cat.id ? 'bg-blue-600 text-white' : 'bg-white/5 text-slate-400 hover:bg-white/10']"
      >
        <span>{{ cat.icon }}</span>
        {{ cat.name }}
      </button>
      <!-- Custom filter -->
      <button 
        @click="selectedCategory = 'custom'" 
        :class="['px-4 py-2 rounded-lg text-sm transition-all flex items-center gap-2', selectedCategory === 'custom' ? 'bg-purple-600 text-white' : 'bg-white/5 text-purple-400 hover:bg-white/10']"
      >
        <span>✨</span>
        Custom
      </button>
    </div>

    <!-- Loading State -->
    <div v-if="loading && templates.length === 0" class="text-center py-12 text-slate-400">
      Loading templates...
    </div>

    <!-- Available Templates -->
    <div v-if="readyTemplates.length > 0" class="space-y-4">
      <div class="flex items-center gap-3">
        <h2 class="text-lg font-semibold text-white">Available</h2>
        <span class="text-xs bg-emerald-500/20 text-emerald-400 px-2.5 py-1 rounded-full">
          {{ readyTemplates.length }} ready
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div v-for="tpl in readyTemplates" :key="tpl.id" class="glass-panel p-0 rounded-xl overflow-hidden hover:border-blue-500/50 transition-all duration-300 flex flex-col group relative">
          <!-- Custom Badge with Status -->
          <div v-if="tpl.is_custom" class="absolute top-4 left-4 z-20 flex gap-2">
            <span class="text-xs bg-purple-500/20 text-purple-400 px-2 py-1 rounded flex items-center gap-1">
              ✨ Custom
            </span>
            <span v-if="tpl.status === 'draft'" class="text-xs bg-slate-500/20 text-slate-400 px-2 py-1 rounded">
              📝 Draft
            </span>
            <span v-else-if="tpl.status === 'validating'" class="text-xs bg-yellow-500/20 text-yellow-400 px-2 py-1 rounded animate-pulse">
              🔄 Validating...
            </span>
            <span v-else-if="tpl.status === 'validation_failed'" class="text-xs bg-red-500/20 text-red-400 px-2 py-1 rounded">
              ❌ Failed
            </span>
            <span v-else-if="tpl.status === 'ready'" class="text-xs bg-emerald-500/20 text-emerald-400 px-2 py-1 rounded">
              ✅ Ready
            </span>
          </div>

          <!-- Action buttons for custom templates -->
          <div v-if="tpl.is_custom" class="absolute top-4 right-4 z-20 flex gap-2 opacity-0 group-hover:opacity-100 transition-all">
            <button
              v-if="tpl.status === 'draft' || tpl.status === 'validation_failed'"
              @click.stop="startValidation(tpl)"
              class="w-8 h-8 rounded-lg bg-blue-500/20 hover:bg-blue-500/40 text-blue-400 flex items-center justify-center"
              title="Start Validation"
            >
              🧪
            </button>
            <button
              v-if="tpl.status === 'validating'"
              @click.stop="viewValidation(tpl)"
              class="w-8 h-8 rounded-lg bg-yellow-500/20 hover:bg-yellow-500/40 text-yellow-400 flex items-center justify-center animate-pulse"
              title="View Progress"
            >
              👁️
            </button>
            <button
              v-if="tpl.status === 'ready' && !tpl.is_published"
              @click.stop="approveTemplate(tpl)"
              class="w-8 h-8 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/40 text-emerald-400 flex items-center justify-center"
              title="Approve & Publish"
            >
              🚀
            </button>
            <button
              @click.stop="confirmDelete(tpl)"
              class="w-8 h-8 rounded-lg bg-red-500/20 hover:bg-red-500/40 text-red-400 flex items-center justify-center"
              title="Delete Template"
            >
              🗑️
            </button>
          </div>

          <!-- Banner -->
          <div class="h-32 relative p-6 flex flex-col justify-end" :style="`background: linear-gradient(135deg, ${tpl.color || '#3b82f6'}20, transparent)`">
              <div class="absolute top-4 right-4 w-12 h-12 rounded-lg flex items-center justify-center" :style="`background: ${tpl.color || '#3b82f6'}30`">
                <span class="text-2xl">{{ iconMap[tpl.icon] || '📦' }}</span>
              </div>
              <span v-if="tpl.popular && !tpl.is_custom" class="absolute top-4 left-4 text-xs bg-yellow-500/20 text-yellow-400 px-2 py-1 rounded">⭐ Popular</span>
              <h3 class="text-xl font-bold text-white relative z-10">{{ tpl.name }}</h3>
              <span class="text-xs font-mono relative z-10" :style="`color: ${tpl.color || '#3b82f6'}`">{{ tpl.category }}</span>
          </div>

          <div class="p-6 flex-1 flex flex-col">
              <p class="text-slate-400 text-sm mb-4 flex-1">{{ tpl.description }}</p>
              <div class="flex items-center gap-2 mb-4 flex-wrap">
                  <span v-for="tech in (tpl.stack || []).slice(0, 4)" :key="tech" class="text-[10px] uppercase font-bold tracking-wider px-2 py-1 bg-slate-800 rounded text-slate-400">
                      {{ tech }}
                  </span>
                  <span v-if="tpl.version" class="text-[10px] font-mono px-2 py-1 bg-slate-700 rounded text-slate-500">
                    v{{ tpl.version }}
                  </span>
              </div>

              <!-- Deploy button -->
              <button
                v-if="!tpl.is_custom || tpl.status === 'ready'"
                @click="deploy(tpl)"
                class="w-full glass-button group-hover:bg-blue-500"
              >
                  🚀 Deploy
              </button>
              <div v-else-if="tpl.status === 'draft'" class="w-full text-center py-2 text-sm text-slate-500">
                ⚠️ Requires validation before deploy
              </div>
              <div v-else-if="tpl.status === 'validating'" class="w-full text-center py-2 text-sm text-yellow-400 animate-pulse">
                🔄 Validation in progress...
              </div>
              <div v-else-if="tpl.status === 'validation_failed'" class="w-full text-center py-2 text-sm text-red-400">
                ❌ Validation failed - fix and retry
              </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Coming Soon Templates -->
    <div v-if="comingSoonTemplates.length > 0" class="space-y-4">
      <div class="flex items-center gap-3">
        <h2 class="text-lg font-semibold text-slate-400">Coming Soon</h2>
        <span class="text-xs bg-slate-500/20 text-slate-500 px-2.5 py-1 rounded-full">
          {{ comingSoonTemplates.length }} in development
        </span>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div v-for="tpl in comingSoonTemplates" :key="tpl.id" class="glass-panel p-0 rounded-xl overflow-hidden transition-all duration-300 flex flex-col relative opacity-50 grayscale hover:opacity-70 hover:grayscale-[50%]">
          <!-- Coming Soon Badge -->
          <div class="absolute top-4 right-4 z-20">
            <span class="text-xs bg-slate-500/30 text-slate-400 px-2.5 py-1 rounded-full backdrop-blur-sm border border-white/5">
              Proximamente
            </span>
          </div>

          <!-- Banner -->
          <div class="h-32 relative p-6 flex flex-col justify-end" :style="`background: linear-gradient(135deg, ${tpl.color || '#3b82f6'}20, transparent)`">
              <div class="absolute top-4 right-4 w-12 h-12 rounded-lg flex items-center justify-center" :style="`background: ${tpl.color || '#3b82f6'}30`">
                <span class="text-2xl">{{ iconMap[tpl.icon] || '📦' }}</span>
              </div>
              <span v-if="tpl.popular" class="absolute top-4 left-4 text-xs bg-yellow-500/20 text-yellow-400 px-2 py-1 rounded">⭐ Popular</span>
              <h3 class="text-xl font-bold text-white relative z-10">{{ tpl.name }}</h3>
              <span class="text-xs font-mono relative z-10" :style="`color: ${tpl.color || '#3b82f6'}`">{{ tpl.category }}</span>
          </div>

          <div class="p-6 flex-1 flex flex-col">
              <p class="text-slate-400 text-sm mb-4 flex-1">{{ tpl.description }}</p>
              <div class="flex items-center gap-2 mb-4 flex-wrap">
                  <span v-for="tech in (tpl.stack || []).slice(0, 4)" :key="tech" class="text-[10px] uppercase font-bold tracking-wider px-2 py-1 bg-slate-800 rounded text-slate-400">
                      {{ tech }}
                  </span>
              </div>

              <!-- Disabled deploy -->
              <div class="w-full text-center py-2.5 px-6 rounded-lg bg-slate-800/50 border border-white/5 text-slate-500 text-sm font-medium cursor-not-allowed">
                  Proximamente
              </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!loading && filteredTemplates.length === 0" class="text-center py-12">
      <div class="text-4xl mb-4">📭</div>
      <p class="text-slate-400">No templates found in this category.</p>
      <button v-if="selectedCategory === 'custom'" @click="showCreateModal = true" class="mt-4 glass-button">
        ✨ Create your first custom template
      </button>
    </div>

    <!-- Create Custom Template Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showCreateModal" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="showCreateModal = false"></div>
          
          <div class="relative bg-slate-900 border border-white/10 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl">
            <!-- Header -->
            <div class="sticky top-0 bg-slate-900 border-b border-white/10 p-6 flex items-center justify-between">
              <div>
                <h2 class="text-xl font-bold text-white">✨ Create Custom Template</h2>
                <p class="text-sm text-slate-400">Define a new template variant for your team</p>
              </div>
              <button @click="showCreateModal = false" class="text-slate-400 hover:text-white text-2xl">&times;</button>
            </div>

            <form @submit.prevent="createCustomTemplate" class="p-6 space-y-6">
              <!-- Basic Info -->
              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Template ID *</label>
                  <input 
                    v-model="newTemplate.id" 
                    type="text" 
                    placeholder="my-vue-dashboard"
                    pattern="[a-z0-9-]+"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    required
                  >
                  <p class="text-xs text-slate-500 mt-1">Lowercase, no spaces (a-z, 0-9, -)</p>
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Display Name *</label>
                  <input 
                    v-model="newTemplate.name" 
                    type="text" 
                    placeholder="Vue Dashboard"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    required
                  >
                </div>
              </div>

              <div>
                <label class="block text-sm font-medium text-slate-300 mb-2">Description *</label>
                <textarea 
                  v-model="newTemplate.description" 
                  rows="2"
                  placeholder="A beautiful dashboard template with charts and tables..."
                  class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  required
                ></textarea>
              </div>

              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Category *</label>
                  <select 
                    v-model="newTemplate.category"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                    required
                  >
                    <option value="frontend">Frontend</option>
                    <option value="backend">Backend</option>
                    <option value="fullstack">Full Stack</option>
                    <option value="database">Database</option>
                    <option value="workflow">Workflow</option>
                  </select>
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Base Template</label>
                  <select 
                    v-model="newTemplate.base_template"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="">None (standalone)</option>
                    <option v-for="tpl in standardTemplates" :key="tpl.id" :value="tpl.id">
                      {{ tpl.name }}
                    </option>
                  </select>
                  <p class="text-xs text-slate-500 mt-1">Inherit from an existing template</p>
                </div>
              </div>

              <div class="grid grid-cols-2 gap-4">
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Icon</label>
                  <select 
                    v-model="newTemplate.icon"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  >
                    <option value="vue">💚 Vue</option>
                    <option value="react">⚛️ React</option>
                    <option value="python">🐍 Python</option>
                    <option value="nodejs">🟢 Node.js</option>
                    <option value="mongodb">🍃 MongoDB</option>
                    <option value="cube">📦 Generic</option>
                  </select>
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Stack (comma separated)</label>
                  <input 
                    v-model="stackInput" 
                    type="text" 
                    placeholder="vue3, tailwind, charts"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  >
                </div>
              </div>

              <!-- Environments -->
              <div>
                <label class="block text-sm font-medium text-slate-300 mb-2">Supported Environments *</label>
                <p class="text-xs text-slate-500 mb-2">Apps created from this template will be tested in these environments during validation</p>
                <div class="flex gap-4">
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" v-model="newTemplate.environments" value="dev" class="rounded bg-slate-800 border-white/20 text-blue-500 focus:ring-blue-500">
                    <span class="text-slate-300">🧪 Dev</span>
                  </label>
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" v-model="newTemplate.environments" value="staging" class="rounded bg-slate-800 border-white/20 text-blue-500 focus:ring-blue-500">
                    <span class="text-slate-300">🔬 Staging</span>
                  </label>
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" v-model="newTemplate.environments" value="prod" class="rounded bg-slate-800 border-white/20 text-blue-500 focus:ring-blue-500">
                    <span class="text-slate-300">🚀 Prod</span>
                  </label>
                </div>
              </div>

              <!-- Creation Modes -->
              <div>
                <label class="block text-sm font-medium text-slate-300 mb-2">Allowed Creation Modes</label>
                <div class="flex gap-4 flex-wrap">
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" v-model="newTemplate.creation_modes" value="scaffold" class="rounded bg-slate-800 border-white/20 text-blue-500 focus:ring-blue-500">
                    <span class="text-slate-300">🏗️ Scaffold</span>
                  </label>
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" v-model="newTemplate.creation_modes" value="empty" class="rounded bg-slate-800 border-white/20 text-blue-500 focus:ring-blue-500">
                    <span class="text-slate-300">📁 Empty</span>
                  </label>
                  <label class="flex items-center gap-2 cursor-pointer">
                    <input type="checkbox" v-model="newTemplate.creation_modes" value="config-only" class="rounded bg-slate-800 border-white/20 text-blue-500 focus:ring-blue-500">
                    <span class="text-slate-300">⚙️ Config Only</span>
                  </label>
                </div>
              </div>

              <!-- K8s Settings -->
              <div class="grid grid-cols-3 gap-4">
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Default Port</label>
                  <input 
                    v-model.number="newTemplate.default_port" 
                    type="number" 
                    min="80"
                    max="65535"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  >
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Replicas</label>
                  <input 
                    v-model.number="newTemplate.default_replicas" 
                    type="number" 
                    min="1"
                    max="10"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  >
                </div>
                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-2">Health Path</label>
                  <input 
                    v-model="newTemplate.health_check_path" 
                    type="text" 
                    placeholder="/"
                    class="w-full bg-slate-800 border border-white/10 rounded-lg px-4 py-3 text-white placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  >
                </div>
              </div>

              <!-- Info box about validation -->
              <div class="p-4 bg-blue-500/10 border border-blue-500/20 rounded-lg">
                <h4 class="text-blue-400 font-semibold flex items-center gap-2 mb-2">
                  <span>🧪</span> Validation Required
                </h4>
                <p class="text-sm text-slate-400">
                  After creation, you'll need to <strong class="text-white">validate</strong> this template by deploying test apps 
                  to each environment. Only validated templates can be used for production deployments.
                </p>
              </div>

              <!-- Actions -->
              <div class="flex gap-4 pt-4 border-t border-white/10">
                <button type="button" @click="showCreateModal = false" class="flex-1 px-6 py-3 rounded-lg border border-white/10 text-slate-400 hover:bg-white/5 transition-colors">
                  Cancel
                </button>
                <button type="submit" :disabled="creating" class="flex-1 px-6 py-3 rounded-lg bg-purple-600 hover:bg-purple-500 text-white font-semibold transition-colors disabled:opacity-50">
                  {{ creating ? 'Creating...' : '✨ Create Template' }}
                </button>
              </div>
            </form>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Delete Confirmation Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showDeleteModal" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="showDeleteModal = false"></div>
          
          <div class="relative bg-slate-900 border border-red-500/30 rounded-2xl w-full max-w-md shadow-2xl p-6">
            <h2 class="text-xl font-bold text-white mb-2">🗑️ Delete Template</h2>
            <p class="text-slate-400 mb-6">
              Are you sure you want to delete <span class="text-white font-semibold">{{ templateToDelete?.name }}</span>? 
              This won't affect apps already created with this template.
            </p>
            <div class="flex gap-4">
              <button @click="showDeleteModal = false" class="flex-1 px-4 py-3 rounded-lg border border-white/10 text-slate-400 hover:bg-white/5">
                Cancel
              </button>
              <button @click="deleteTemplate" :disabled="deleting" class="flex-1 px-4 py-3 rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold disabled:opacity-50">
                {{ deleting ? 'Deleting...' : 'Delete' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Validation Progress Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showValidationModal" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="showValidationModal = false"></div>
          
          <div class="relative bg-slate-900 border border-white/10 rounded-2xl w-full max-w-lg shadow-2xl">
            <!-- Header -->
            <div class="p-6 border-b border-white/10">
              <h2 class="text-xl font-bold text-white flex items-center gap-2">
                🧪 Template Validation
              </h2>
              <p class="text-sm text-slate-400 mt-1">Testing: {{ validatingTemplate?.name }}</p>
            </div>

            <!-- Progress -->
            <div class="p-6 space-y-4">
              <!-- Status Badge -->
              <div class="flex items-center justify-between">
                <span class="text-slate-400">Status:</span>
                <span v-if="validationStatus?.status === 'draft'" class="px-3 py-1 rounded-full bg-slate-500/20 text-slate-400 text-sm">
                  📝 Draft
                </span>
                <span v-else-if="validationStatus?.status === 'validating'" class="px-3 py-1 rounded-full bg-yellow-500/20 text-yellow-400 text-sm animate-pulse">
                  🔄 Validating...
                </span>
                <span v-else-if="validationStatus?.status === 'validation_failed'" class="px-3 py-1 rounded-full bg-red-500/20 text-red-400 text-sm">
                  ❌ Failed
                </span>
                <span v-else-if="validationStatus?.status === 'ready'" class="px-3 py-1 rounded-full bg-emerald-500/20 text-emerald-400 text-sm">
                  ✅ Ready
                </span>
              </div>

              <!-- Progress Bar -->
              <div v-if="validationStatus?.progress" class="space-y-2">
                <div class="flex justify-between text-sm">
                  <span class="text-slate-400">Progress</span>
                  <span class="text-white">{{ validationStatus.progress.percentage }}%</span>
                </div>
                <div class="h-2 bg-slate-800 rounded-full overflow-hidden">
                  <div 
                    class="h-full bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-500"
                    :style="{ width: validationStatus.progress.percentage + '%' }"
                  ></div>
                </div>
              </div>

              <!-- Test Apps List -->
              <div class="space-y-2 mt-4">
                <h3 class="text-sm font-semibold text-slate-300">Test Environments:</h3>
                <div 
                  v-for="app in validationStatus?.test_apps || []" 
                  :key="app.app_name"
                  class="flex items-center justify-between p-3 rounded-lg bg-slate-800/50 border border-white/5"
                >
                  <div class="flex items-center gap-3">
                    <span v-if="app.status === 'pending'" class="text-slate-400">⏳</span>
                    <span v-else-if="app.status === 'deploying'" class="text-yellow-400 animate-spin">⚙️</span>
                    <span v-else-if="app.status === 'deployed' || app.status === 'healthy'" class="text-emerald-400">✅</span>
                    <span v-else-if="app.status === 'failed'" class="text-red-400">❌</span>
                    <div>
                      <p class="text-white text-sm font-medium">{{ app.environment.toUpperCase() }}</p>
                      <p class="text-xs text-slate-500 font-mono">{{ app.app_name }}</p>
                    </div>
                  </div>
                  <span :class="['text-xs px-2 py-1 rounded', getStatusClasses(app.status)]">
                    {{ app.status }}
                  </span>
                </div>
              </div>

              <!-- Error Message -->
              <div v-if="validationStatus?.test_apps?.some(a => a.error_message)" class="mt-4 p-4 bg-red-900/20 border border-red-500/30 rounded-lg">
                <h4 class="text-red-400 font-semibold mb-2">⚠️ Errors:</h4>
                <div v-for="app in validationStatus.test_apps.filter(a => a.error_message)" :key="app.app_name" class="text-sm text-red-300">
                  <strong>{{ app.environment }}:</strong> {{ app.error_message }}
                </div>
              </div>
            </div>

            <!-- Actions -->
            <div class="p-6 border-t border-white/10 flex gap-4">
              <button @click="showValidationModal = false" class="flex-1 px-4 py-3 rounded-lg border border-white/10 text-slate-400 hover:bg-white/5">
                Close
              </button>
              <button 
                v-if="validationStatus?.status === 'validation_failed'"
                @click="deleteTestApps"
                :disabled="actionLoading"
                class="flex-1 px-4 py-3 rounded-lg bg-red-600 hover:bg-red-500 text-white font-semibold disabled:opacity-50"
              >
                {{ actionLoading ? 'Cleaning...' : '🗑️ Delete Failed Tests' }}
              </button>
              <button 
                v-if="validationStatus?.status === 'ready'"
                @click="approveAndPublish"
                :disabled="actionLoading"
                class="flex-1 px-4 py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white font-semibold disabled:opacity-50"
              >
                {{ actionLoading ? 'Publishing...' : '🚀 Approve & Publish' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- Toast -->
    <Teleport to="body">
      <Transition name="toast">
        <div v-if="toast.show" :class="['fixed bottom-6 right-6 z-[100] px-6 py-4 rounded-xl shadow-2xl backdrop-blur-xl border', toast.type === 'success' ? 'bg-emerald-900/90 border-emerald-500/50 text-emerald-100' : 'bg-red-900/90 border-red-500/50 text-red-100']">
          <div class="flex items-center gap-3">
            <span class="text-2xl">{{ toast.type === 'success' ? '✅' : '❌' }}</span>
            <p class="font-medium">{{ toast.message }}</p>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'

const router = useRouter()
const loading = ref(false)
const templates = ref([])
const selectedCategory = ref(null)

// Create modal
const showCreateModal = ref(false)
const creating = ref(false)
const stackInput = ref('')
const newTemplate = reactive({
  id: '',
  name: '',
  description: '',
  category: 'frontend',
  icon: 'vue',
  base_template: '',
  environments: ['dev', 'prod'],
  creation_modes: ['scaffold', 'empty'],
  default_port: 80,
  default_replicas: 1,
  health_check_path: '/'
})

// Delete modal
const showDeleteModal = ref(false)
const deleting = ref(false)
const templateToDelete = ref(null)

// Validation modal
const showValidationModal = ref(false)
const validatingTemplate = ref(null)
const validationStatus = ref(null)
const actionLoading = ref(false)
let validationPollInterval = null

// Toast
const toast = reactive({ show: false, message: '', type: 'success' })

const showToast = (message, type = 'success') => {
  toast.message = message
  toast.type = type
  toast.show = true
  setTimeout(() => { toast.show = false }, 4000)
}

// Categories from API
const categories = ref([])

const loadCategories = async () => {
  try {
    const { data } = await axios.get('/api/v1/templates/catalog/categories')
    categories.value = data.categories || []
  } catch (e) {
    // Fallback to hardcoded
    categories.value = [
      { id: 'frontend', name: 'Frontend', icon: '🎨' },
      { id: 'backend', name: 'Backend', icon: '⚙️' },
      { id: 'database', name: 'Database', icon: '💾' },
      { id: 'workflow', name: 'Workflow', icon: '🔄' },
      { id: 'iot', name: 'IoT', icon: '📡' },
      { id: 'monitoring', name: 'Monitoring', icon: '📊' },
    ]
  }
}

const iconMap = {
  vue: '💚',
  python: '🐍',
  n8n: '🔄',
  mongodb: '🍃',
  nodejs: '🟢',
  react: '⚛️',
  cube: '📦',
  default: '📦'
}

const standardTemplates = computed(() => templates.value.filter(t => !t.is_custom))

const filteredTemplates = computed(() => {
  if (selectedCategory.value === 'custom') {
    return templates.value.filter(t => t.is_custom)
  }
  if (!selectedCategory.value) return templates.value
  return templates.value.filter(t => t.category === selectedCategory.value)
})

const readyTemplates = computed(() => {
  if (selectedCategory.value === 'custom') return filteredTemplates.value
  return filteredTemplates.value.filter(t => t.status === 'ready' || t.is_custom)
})

const comingSoonTemplates = computed(() => {
  if (selectedCategory.value === 'custom') return []
  return filteredTemplates.value.filter(t => t.status !== 'ready' && !t.is_custom)
})

const deploy = (tpl) => {
    router.push({ name: 'wizard', query: { template: tpl.id } })
}

const loadTemplates = async () => {
  loading.value = true
  try {
    const { data } = await axios.get('/api/v1/templates')
    templates.value = data
  } catch (e) {
    console.error('Failed to load templates:', e)
  } finally {
    loading.value = false
  }
}

const refreshTemplates = async () => {
  loading.value = true
  try {
    await axios.get('/api/v1/templates/refresh')
    await loadTemplates()
    showToast('Templates refreshed from repository')
  } catch (e) {
    console.error('Failed to refresh templates:', e)
    await loadTemplates()
  }
}

const createCustomTemplate = async () => {
  creating.value = true
  try {
    const payload = {
      ...newTemplate,
      stack: stackInput.value.split(',').map(s => s.trim()).filter(Boolean)
    }
    
    const { data } = await axios.post('/api/v1/templates/custom', payload)
    showToast(`Template "${newTemplate.name}" created! Now validate it.`)
    showCreateModal.value = false
    
    // Reset form
    Object.assign(newTemplate, {
      id: '', name: '', description: '', category: 'frontend', 
      icon: 'vue', base_template: '', environments: ['dev', 'prod'],
      creation_modes: ['scaffold', 'empty'], default_port: 80,
      default_replicas: 1, health_check_path: '/'
    })
    stackInput.value = ''
    
    await loadTemplates()
    
    // Auto-open validation modal for the new template
    const createdTemplate = templates.value.find(t => t.id === payload.id)
    if (createdTemplate) {
      validatingTemplate.value = createdTemplate
      showValidationModal.value = true
    }
  } catch (e) {
    showToast(e.response?.data?.detail || 'Failed to create template', 'error')
  } finally {
    creating.value = false
  }
}

const confirmDelete = (tpl) => {
  templateToDelete.value = tpl
  showDeleteModal.value = true
}

const deleteTemplate = async () => {
  if (!templateToDelete.value) return
  
  deleting.value = true
  try {
    await axios.delete(`/api/v1/templates/custom/${templateToDelete.value.id}`)
    showToast(`Template "${templateToDelete.value.name}" deleted`)
    showDeleteModal.value = false
    templateToDelete.value = null
    await loadTemplates()
  } catch (e) {
    showToast(e.response?.data?.detail || 'Failed to delete template', 'error')
  } finally {
    deleting.value = false
  }
}

// ======== VALIDATION FUNCTIONS ========

const getStatusClasses = (status) => {
  const map = {
    'pending': 'bg-slate-500/20 text-slate-400',
    'deploying': 'bg-yellow-500/20 text-yellow-400',
    'deployed': 'bg-emerald-500/20 text-emerald-400',
    'healthy': 'bg-emerald-500/20 text-emerald-400',
    'failed': 'bg-red-500/20 text-red-400'
  }
  return map[status] || 'bg-slate-500/20 text-slate-400'
}

const startValidation = async (tpl) => {
  validatingTemplate.value = tpl
  showValidationModal.value = true
  actionLoading.value = true
  
  try {
    await axios.post(`/api/v1/templates/custom/${tpl.id}/validate`)
    showToast(`Validation started for "${tpl.name}"`)
    startPollingValidation(tpl.id)
  } catch (e) {
    showToast(e.response?.data?.detail || 'Failed to start validation', 'error')
  } finally {
    actionLoading.value = false
  }
}

const viewValidation = async (tpl) => {
  validatingTemplate.value = tpl
  showValidationModal.value = true
  await fetchValidationStatus(tpl.id)
  
  // Start polling if still validating
  if (validationStatus.value?.status === 'validating') {
    startPollingValidation(tpl.id)
  }
}

const fetchValidationStatus = async (templateId) => {
  try {
    const { data } = await axios.get(`/api/v1/templates/custom/${templateId}/validation-status`)
    validationStatus.value = data
  } catch (e) {
    console.error('Failed to fetch validation status:', e)
  }
}

const startPollingValidation = (templateId) => {
  // Clear any existing interval
  if (validationPollInterval) {
    clearInterval(validationPollInterval)
  }
  
  // Poll every 3 seconds
  validationPollInterval = setInterval(async () => {
    await fetchValidationStatus(templateId)
    
    // Stop polling when validation is complete
    if (validationStatus.value?.status !== 'validating') {
      clearInterval(validationPollInterval)
      validationPollInterval = null
      await loadTemplates() // Refresh templates list
    }
  }, 3000)
}

const deleteTestApps = async () => {
  if (!validatingTemplate.value) return
  
  actionLoading.value = true
  try {
    await axios.delete(`/api/v1/templates/custom/${validatingTemplate.value.id}/test-apps`)
    showToast('Test apps deleted')
    await fetchValidationStatus(validatingTemplate.value.id)
    await loadTemplates()
  } catch (e) {
    showToast(e.response?.data?.detail || 'Failed to delete test apps', 'error')
  } finally {
    actionLoading.value = false
  }
}

const approveTemplate = async (tpl) => {
  validatingTemplate.value = tpl
  showValidationModal.value = true
  await fetchValidationStatus(tpl.id)
}

const approveAndPublish = async () => {
  if (!validatingTemplate.value) return
  
  actionLoading.value = true
  try {
    await axios.post(`/api/v1/templates/custom/${validatingTemplate.value.id}/approve`)
    showToast(`🎉 Template "${validatingTemplate.value.name}" is now published!`)
    showValidationModal.value = false
    await loadTemplates()
  } catch (e) {
    showToast(e.response?.data?.detail || 'Failed to approve template', 'error')
  } finally {
    actionLoading.value = false
  }
}

onMounted(() => {
  loadCategories()
  loadTemplates()
})
</script>

<style scoped>
.modal-enter-active, .modal-leave-active {
  transition: all 0.3s ease;
}
.modal-enter-from, .modal-leave-to {
  opacity: 0;
}

.toast-enter-active, .toast-leave-active {
  transition: all 0.3s ease;
}
.toast-enter-from, .toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
