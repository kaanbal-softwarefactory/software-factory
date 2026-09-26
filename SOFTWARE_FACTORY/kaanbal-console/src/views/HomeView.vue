<template>
  <div class="max-w-4xl mx-auto">
    <!-- Success Banner -->
    <div v-if="success" class="mb-8 p-4 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-3 text-emerald-400 animate-fade-in-up">
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clip-rule="evenodd" />
      </svg>
      <div>
         <span class="font-bold">Project Created!</span>
         <span class="opacity-80 ml-2">Check Bitbucket for your new repo: <a :href="repoUrl" target="_blank" class="underline hover:text-white">{{ repoUrl }}</a></span>
      </div>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8">
      <!-- Left Column: Form -->
      <div class="lg:col-span-2 space-y-8">
        <!-- Step 1: Project Details -->
        <section class="glass-panel p-6 rounded-xl relative overflow-hidden group">
          <div class="absolute top-0 left-0 w-1 h-full bg-blue-500"></div>
          <h3 class="text-xl font-bold text-white mb-6 flex items-center gap-2">
            <span class="w-8 h-8 rounded-full bg-blue-500/20 flex items-center justify-center text-blue-400 text-sm font-bold border border-blue-500/30">1</span>
            Project Details
          </h3>
          
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-slate-400 mb-1.5 ml-1">Project Name</label>
              <input v-model="form.name" type="text" placeholder="e.g., inventory-dashboard" class="glass-input w-full" />
              <p class="text-xs text-slate-500 mt-1.5 ml-1">Lowercase, hyphens only. Used for repo and DNS.</p>
            </div>
            
            <div class="grid grid-cols-2 gap-4">
               <div>
                  <label class="block text-sm font-medium text-slate-400 mb-1.5 ml-1">Project Key</label>
                  <input v-model="form.key" type="text" placeholder="INV" class="glass-input w-full uppercase" maxlength="4" />
               </div>
                <div>
                  <label class="block text-sm font-medium text-slate-400 mb-1.5 ml-1">Owner</label>
                  <input v-model="form.owner" type="text" placeholder="Team Name" class="glass-input w-full" />
               </div>
            </div>
          </div>
        </section>

        <!-- Step 2: Stack Selection -->
        <section class="glass-panel p-6 rounded-xl relative overflow-hidden">
          <div class="absolute top-0 left-0 w-1 h-full bg-purple-500"></div>
           <h3 class="text-xl font-bold text-white mb-6 flex items-center gap-2">
            <span class="w-8 h-8 rounded-full bg-purple-500/20 flex items-center justify-center text-purple-400 text-sm font-bold border border-purple-500/30">2</span>
            Technology Stack
          </h3>

          <div v-if="templatesLoading" class="text-center py-8 text-slate-400">
            <svg class="animate-spin h-8 w-8 mx-auto mb-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Loading templates...
          </div>
          
          <div v-else class="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <!-- Dynamic Template Cards -->
            <div 
              v-for="template in templates"
              :key="template.id"
              @click="form.template = template.id"
              class="relative p-4 rounded-xl border cursor-pointer transition-all duration-300 group"
              :class="form.template === template.id ? 'bg-blue-500/10 border-blue-500 shadow-lg shadow-blue-500/20' : 'bg-slate-800/50 border-white/5 hover:border-white/20 hover:bg-slate-800'"
            >
              <div class="flex items-start justify-between mb-3">
                 <div class="w-10 h-10 rounded-lg flex items-center justify-center" :style="{backgroundColor: template.color + '20'}">
                    <svg v-if="template.icon === 'vue'" viewBox="0 0 24 24" class="w-6 h-6" :style="{color: template.color, fill: 'currentColor'}">
                      <path d="M24,1.61H14.06L12,5.16,9.94,1.61H0L12,22.39ZM12,14.08,5.16,2.23H9.59L12,6.41l2.41-4.18h4.43Z"/>
                    </svg>
                    <svg v-else-if="template.icon === 'python'" viewBox="0 0 24 24" class="w-6 h-6" :style="{color: template.color, fill: 'currentColor'}">
                      <path d="M12 2L2 7l10 5 10-5-10-5zm0 9l2.5-1.25L12 8.5l-2.5 1.25L12 11zm0 2.5l-5-2.5-5 2.5L12 22l10-8.5-5-2.5-5 2.5z"/>
                    </svg>
                 </div>
                 <div v-if="form.template === template.id" class="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-3 h-3 text-white">
                      <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                    </svg>
                 </div>
              </div>
              <h4 class="font-bold text-white mb-1">{{ template.name }}</h4>
              <p class="text-xs text-slate-400 leading-relaxed">{{ template.description }}</p>
            </div>
          </div>
        </section>

        <!-- Actions -->
        <div class="flex justify-end pt-4">
           <button 
             @click="createProject" 
             :disabled="loading || !isValid"
             class="glass-button w-full sm:w-auto flex items-center justify-center gap-2 group disabled:opacity-50 disabled:cursor-not-allowed"
           >
             <svg v-if="loading" class="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
               <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
               <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
             </svg>
             <span v-else class="text-lg">Launch Project</span>
             <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" class="w-4 h-4 group-hover:translate-x-1 transition-transform">
                <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
             </svg>
           </button>
        </div>
      </div>

      <!-- Right Column: Preview/Summary -->
      <div class="space-y-6">
         <div class="glass-panel p-6 rounded-xl sticky top-6">
            <h4 class="text-sm font-bold text-slate-400 uppercase tracking-wider mb-4">Summary</h4>
            
            <div class="space-y-4">
               <div class="flex justify-between items-center py-2 border-b border-white/5">
                  <span class="text-slate-400">Cost Estimate</span>
                  <span class="text-white font-mono">$0.00 <span class="text-xs text-slate-500">/ mo</span></span>
               </div>
               <div class="flex justify-between items-center py-2 border-b border-white/5">
                  <span class="text-slate-400">Environment</span>
                  <div class="flex gap-1">
                     <span class="px-2 py-0.5 rounded bg-blue-500/10 text-blue-400 text-xs border border-blue-500/20">DEV</span>
                     <span class="px-2 py-0.5 rounded bg-purple-500/10 text-purple-400 text-xs border border-purple-500/20">PROD</span>
                  </div>
               </div>
            </div>

            <div class="mt-6 bg-slate-950/50 rounded-lg p-4 font-mono text-xs text-slate-400 overflow-x-auto border border-white/5">
               <div class="text-blue-400 mb-2">// Proposed Resource</div>
               <div>apiVersion: argoproj.io/v1alpha1</div>
               <div>kind: Application</div>
               <div>metadata:</div>
               <div class="pl-2">name: <span class="text-white">{{ form.name || '...' }}</span></div>
               <div class="pl-2">namespace: argocd</div>
            </div>
         </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue';
import axios from 'axios';
import { getConfig } from '@/config';

const form = ref({
  name: '',
  key: '',
  template: '',
  owner: 'Kaanbal BioTech'
});

const templates = ref([]);
const templatesLoading = ref(true);
const loading = ref(false);
const success = ref(false);
const repoUrl = ref('');

// Load templates on mount
onMounted(async () => {
  try {
    const response = await axios.get('/api/v1/templates');
    templates.value = response.data.filter(t => !t.coming_soon); // Filter out coming soon templates
    
    // Set default template
    if (templates.value.length > 0) {
      form.value.template = templates.value[0].id;
    }
  } catch (error) {
    console.error('Failed to load templates:', error);
    // Fallback to hardcoded template if API fails
    templates.value = [
      {
        id: 'tpl-vue3-spa-standard',
        name: 'Vue 3 SPA',
        description: 'Vite, Tailwind, and Pinia pre-configured. Best for dashboards.',
        icon: 'vue',
        color: '#42b883'
      }
    ];
    form.value.template = 'tpl-vue3-spa-standard';
  } finally {
    templatesLoading.value = false;
  }
});

const isValid = computed(() => {
   return form.value.name.length > 3 && form.value.key.length > 0 && form.value.template.length > 0;
});

const createProject = async () => {
  loading.value = true;
  success.value = false;
  
  // payload structure matches your core/examples/create-minimal.json
  const payload = {
    app: {
      name: form.value.name,
      template: form.value.template
    },
    project: {
      key: form.value.key,
      name: form.value.name // Using app name as project name for simplicity in wizard
    }
  };

  try {
    // Usa baseURL de axios configurado en main.js
    const response = await axios.post('/api/v1/apps', payload);
    
    // Determine repo URL from runtime provider config
    const provider = getConfig('gitProvider', 'bitbucket');
    const namespace = getConfig('gitNamespace', '');
    if (provider === 'github') {
      repoUrl.value = `https://github.com/${namespace || '<org>'}/${form.value.name}`;
    } else {
      repoUrl.value = `https://bitbucket.org/${namespace || '<workspace>'}/${form.value.name}`;
    }
    success.value = true;
    
    // Reset form partially
    form.value.name = '';
    
  } catch (error) {
    console.error("Failed to create project:", error);
    alert("Error creating project: " + (error.response?.data?.detail || error.message));
  } finally {
    loading.value = false;
  }
};
</script>
