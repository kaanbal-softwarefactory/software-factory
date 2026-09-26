<template>
  <div class="space-y-6">
    <div class="glass-panel p-6 rounded-lg">
      <h1 class="text-3xl font-bold bg-gradient-to-r from-blue-400 to-purple-500 bg-clip-text text-transparent">Settings</h1>
      <p class="mt-2 text-slate-400">Manage your factory configuration, credentials and API tokens.</p>
    </div>

    <!-- TABS -->
    <div class="flex gap-4 border-b border-white/10 pb-2">
      <button
        @click="activeTab = 'system'"
        :class="['px-4 py-2 rounded-t-lg transition-all', activeTab === 'system' ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-white']"
      >
        ⚙️ System Configuration
      </button>
      <button
        @click="activeTab = 'credentials'"
        :class="['px-4 py-2 rounded-t-lg transition-all', activeTab === 'credentials' ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-white']"
      >
        🔑 Credentials
      </button>
      <button
        @click="activeTab = 'tokens'"
        :class="['px-4 py-2 rounded-t-lg transition-all', activeTab === 'tokens' ? 'bg-white/10 text-white' : 'text-slate-400 hover:text-white']"
      >
        🎫 API Tokens
      </button>
    </div>

    <!-- SYSTEM CONFIGURATION TAB -->
    <div v-if="activeTab === 'system'" class="glass-panel p-6 rounded-lg max-w-2xl">
        <h2 class="text-xl font-semibold text-white mb-6 flex items-center gap-2">
            <span class="text-2xl">⚙️</span> System Configuration
        </h2>

        <div v-if="loadingSystem" class="text-center py-8 text-slate-400">Loading configuration...</div>

        <form v-else @submit.prevent="saveSystemSettings" class="space-y-6">
            <!-- General -->
            <div class="space-y-4 border-b border-white/5 pb-6">
                <h3 class="text-lg font-medium text-blue-400">General</h3>

                <div class="grid grid-cols-2 gap-4">
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Domain</label>
                      <input v-model="systemForm.domain" type="text" class="glass-input w-full" placeholder="e.g. mydomain.com" />
                      <p class="text-xs text-slate-500 mt-1">Used for DNS and URLs</p>
                  </div>
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Tailscale DNS Suffix</label>
                      <input v-model="systemForm.tailscale_dns_suffix" type="text" class="glass-input w-full" placeholder="e.g. tail1234.ts.net" />
                      <p class="text-xs text-slate-500 mt-1">For private access</p>
                  </div>
                </div>

                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-1">Cluster SSH Host</label>
                  <input v-model="systemForm.cluster_ssh_host" type="text" class="glass-input w-full" placeholder="e.g. 203.0.113.10 or your-server-ip" />
                  <p class="text-xs text-slate-500 mt-1">Used to generate copy/paste SSH tunnel commands (Mongo local access)</p>
                </div>
            </div>

            <!-- ArgoCD -->
            <div class="space-y-4 border-b border-white/5 pb-6">
                <h3 class="text-lg font-medium text-blue-400">ArgoCD</h3>

                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">ArgoCD URL</label>
                    <input v-model="systemForm.argocd_url" type="url" class="glass-input w-full" placeholder="https://cd.mydomain.com" />
                    <p class="text-xs text-slate-500 mt-1">Used for links to GitOps dashboard</p>
                </div>

                <div v-if="systemForm.argocd_url" class="bg-blue-500/10 border border-blue-500/20 rounded-lg p-3">
                  <p class="text-xs text-blue-300">Preview: <a :href="systemForm.argocd_url" target="_blank" class="text-blue-400 hover:underline">{{ systemForm.argocd_url }}</a></p>
                </div>
            </div>

            <!-- Vault -->
            <div class="space-y-4 border-b border-white/5 pb-6">
                <h3 class="text-lg font-medium text-blue-400">Vault</h3>

                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">Vault Hostname (Tailscale)</label>
                    <input v-model="systemForm.vault_hostname" type="text" class="glass-input w-full" placeholder="e.g. vault-vault-ui-ingress" />
                    <p class="text-xs text-slate-500 mt-1">Hostname for accessing Vault UI via Tailscale</p>
                </div>

                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">Vault Internal Address</label>
                    <input v-model="systemForm.vault_addr" type="text" class="glass-input w-full" placeholder="http://vault.vault.svc.cluster.local:8200" />
                    <p class="text-xs text-slate-500 mt-1">Used by deployer to write secrets (in-cluster address)</p>
                </div>

                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">Vault Token</label>
                    <div class="relative">
                        <input v-model="systemForm.vault_token" :type="showVaultToken ? 'text' : 'password'" class="glass-input w-full pr-20" :placeholder="systemForm.vault_token_masked || '••••••••'" />
                        <button type="button" @click="showVaultToken = !showVaultToken" class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white text-sm">
                            {{ showVaultToken ? 'Hide' : 'Show' }}
                        </button>
                    </div>
                    <p class="text-xs text-slate-500 mt-1">Current: {{ systemForm.vault_token_masked || 'Not configured' }}</p>
                </div>

                <div v-if="systemForm.vault_hostname && systemForm.tailscale_dns_suffix" class="bg-purple-500/10 border border-purple-500/20 rounded-lg p-3">
                  <p class="text-xs text-purple-300">
                    Preview: <a :href="`https://${systemForm.vault_hostname}.${systemForm.tailscale_dns_suffix}/ui/`" target="_blank" class="text-purple-400 hover:underline">
                      https://{{ systemForm.vault_hostname }}.{{ systemForm.tailscale_dns_suffix }}/ui/
                    </a>
                  </p>
                </div>
            </div>

            <!-- Integration & Repos -->
            <div class="space-y-4 border-b border-white/5 pb-6">
                <h3 class="text-lg font-medium text-blue-400">Integration & Repositories</h3>

                <div class="grid grid-cols-2 gap-4">
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Bitbucket Workspace</label>
                      <input v-model="systemForm.bitbucket_workspace" type="text" class="glass-input w-full" placeholder="my-workspace" />
                  </div>
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Templates Repo</label>
                      <input v-model="systemForm.templates_repo" type="text" class="glass-input w-full" placeholder="kaanbal-templates" />
                  </div>
                </div>
            </div>

            <!-- Activity Logs -->
            <div class="space-y-4 border-b border-white/5 pb-6">
                <h3 class="text-lg font-medium text-blue-400">Activity Logs</h3>

                <div class="grid grid-cols-2 gap-4">
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Retention Days</label>
                      <input v-model.number="systemForm.logs_retention_days" type="number" min="1" max="3650" class="glass-input w-full" />
                      <p class="text-xs text-slate-500 mt-1">Mongo TTL auto-cleanup window</p>
                  </div>
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Webhook Min Level</label>
                      <select v-model="systemForm.logs_forwarding_min_level" class="glass-input w-full">
                        <option value="debug">debug</option>
                        <option value="info">info</option>
                        <option value="warn">warn</option>
                        <option value="error">error</option>
                      </select>
                  </div>
                </div>

                <div>
                  <label class="block text-sm font-medium text-slate-300 mb-1">Error Forwarding Webhook URL</label>
                  <input
                    v-model="systemForm.logs_forwarding_webhook_url"
                    type="url"
                    class="glass-input w-full"
                    :placeholder="systemForm.logs_forwarding_webhook_url_masked || 'https://your-observability-endpoint.example/webhook'"
                  />
                  <p class="text-xs text-slate-500 mt-1">
                    Optional. Critical logs are forwarded server-side. Current: {{ systemForm.logs_forwarding_webhook_url_masked || 'Not configured' }}
                  </p>
                </div>
            </div>

            <div class="flex justify-end pt-4">
                <button type="submit" :disabled="savingSystem" class="glass-button flex items-center">
                    <span v-if="savingSystem" class="animate-spin mr-2">⚙️</span>
                    {{ savingSystem ? 'Saving...' : 'Save Configuration' }}
                </button>
            </div>

            <div v-if="systemMessage" :class="`p-4 rounded-lg text-sm text-center ${systemMessageClass}`">
                {{ systemMessage }}
            </div>
        </form>
    </div>

    <!-- CREDENTIALS TAB -->
    <div v-if="activeTab === 'credentials'" class="glass-panel p-6 rounded-lg max-w-2xl">
        <h2 class="text-xl font-semibold text-white mb-6 flex items-center gap-2">
            <span class="text-2xl">🔑</span> Provider Credentials
        </h2>
        
        <div v-if="loadingCreds" class="text-center py-8 text-slate-400">Loading credentials...</div>

        <form v-else @submit.prevent="saveSettings" class="space-y-6">
            <!-- Bitbucket -->
            <div class="space-y-4 border-b border-white/5 pb-6">
                <h3 class="text-lg font-medium text-blue-400">Bitbucket / Git</h3>
                
                <div class="grid grid-cols-2 gap-4">
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Username</label>
                      <input v-model="form.git_username" type="text" class="glass-input w-full" placeholder="e.g. your-github-user" />
                  </div>
                  <div>
                      <label class="block text-sm font-medium text-slate-300 mb-1">Email (for API)</label>
                      <input v-model="form.bitbucket_email" type="email" class="glass-input w-full" placeholder="your@email.com" />
                  </div>
                </div>

                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">App Password / Token</label>
                    <div class="relative">
                        <input v-model="form.git_token" :type="showGitToken ? 'text' : 'password'" class="glass-input w-full pr-20" :placeholder="credentials.git_token_masked || '••••••••'" />
                        <button type="button" @click="showGitToken = !showGitToken" class="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white text-sm">
                            {{ showGitToken ? 'Hide' : 'Show' }}
                        </button>
                    </div>
                    <p class="text-xs text-slate-500 mt-1">Current: {{ credentials.git_token_masked }}</p>
                </div>
            </div>

            <!-- Docker Hub -->
            <div class="space-y-4 border-b border-white/5 pb-6">
                <h3 class="text-lg font-medium text-blue-400">Docker Hub</h3>
                
                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">Username</label>
                    <input v-model="form.dockerhub_username" type="text" class="glass-input w-full" :placeholder="credentials.dockerhub_username || 'e.g. abardales'" />
                </div>

                <div>
                    <label class="block text-sm font-medium text-slate-300 mb-1">Access Token (PAT)</label>
                    <input v-model="form.dockerhub_token" type="password" class="glass-input w-full" :placeholder="credentials.dockerhub_token_masked || '••••••••'" />
                    <p class="text-xs text-slate-500 mt-1">Current: {{ credentials.dockerhub_token_masked }}</p>
                </div>
            </div>

            <!-- Read-only info -->
            <div class="space-y-4 bg-white/5 p-4 rounded-lg">
                <h3 class="text-lg font-medium text-slate-400">System Info (read-only)</h3>
                <div class="grid grid-cols-2 gap-4 text-sm">
                    <div>
                        <span class="text-slate-500">Workspace:</span>
                        <span class="text-white ml-2">{{ credentials.bitbucket_workspace }}</span>
                    </div>
                    <div>
                        <span class="text-slate-500">Domain:</span>
                        <span class="text-white ml-2">{{ credentials.domain }}</span>
                    </div>
                    <div class="col-span-2">
                        <span class="text-slate-500">Infra Repo:</span>
                        <span class="text-white ml-2 text-xs">{{ credentials.infra_repo_url }}</span>
                    </div>
                </div>
            </div>

            <div class="flex justify-end pt-4">
                <button type="submit" :disabled="saving" class="glass-button flex items-center">
                    <span v-if="saving" class="animate-spin mr-2">⚙️</span>
                    {{ saving ? 'Saving...' : 'Save Configuration' }}
                </button>
            </div>

            <div v-if="message" :class="`p-4 rounded-lg text-sm text-center ${messageClass}`">
                {{ message }}
            </div>
        </form>
    </div>

    <!-- API TOKENS TAB -->
    <div v-if="activeTab === 'tokens'" class="space-y-6">
      <div class="glass-panel p-6 rounded-lg max-w-3xl">
        <div class="flex justify-between items-center mb-6">
          <div>
            <h2 class="text-xl font-semibold text-white flex items-center gap-2">
              <span class="text-2xl">🎫</span> API Tokens
            </h2>
            <p class="text-sm text-slate-400 mt-1">Create tokens to access Kaanbal API from external systems (Jira, CI/CD, scripts)</p>
          </div>
          <button @click="showCreateToken = true" class="glass-button">+ New Token</button>
        </div>

        <div v-if="loadingTokens" class="text-center py-8 text-slate-400">Loading tokens...</div>
        
        <div v-else-if="tokens.length === 0" class="text-center py-8 text-slate-500">
          No API tokens yet. Create one to integrate with external systems.
        </div>

        <div v-else class="space-y-3">
          <div v-for="token in tokens" :key="token.id" class="flex items-center justify-between p-4 bg-white/5 rounded-lg">
            <div>
              <div class="font-medium text-white">{{ token.name }}</div>
              <div class="text-xs text-slate-400 font-mono">{{ token.key_prefix }}</div>
              <div class="flex gap-2 mt-1">
                <span v-for="scope in token.scopes" :key="scope" class="text-xs px-2 py-0.5 bg-blue-500/20 text-blue-300 rounded">{{ scope }}</span>
              </div>
            </div>
            <div class="text-right">
              <div class="text-xs text-slate-500">{{ token.last_used_at ? `Last used: ${formatDate(token.last_used_at)}` : 'Never used' }}</div>
              <button @click="revokeToken(token.id)" class="text-red-400 hover:text-red-300 text-sm mt-2">Revoke</button>
            </div>
          </div>
        </div>
      </div>

      <!-- Create Token Modal -->
      <div v-if="showCreateToken" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="showCreateToken = false">
        <div class="glass-panel p-6 rounded-lg w-full max-w-md">
          <h3 class="text-xl font-semibold text-white mb-4">Create API Token</h3>
          <div class="space-y-4">
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-1">Token Name</label>
              <input v-model="newToken.name" type="text" class="glass-input w-full" placeholder="e.g. Jira Integration" />
            </div>
            <div>
              <label class="block text-sm font-medium text-slate-300 mb-2">Scopes (Permissions)</label>
              <div class="grid grid-cols-2 gap-2">
                <label v-for="scope in availableScopes" :key="scope" class="flex items-center gap-2 text-sm text-slate-300">
                  <input type="checkbox" v-model="newToken.scopes" :value="scope" class="rounded bg-white/10 border-white/20" />
                  {{ scope }}
                </label>
              </div>
            </div>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button @click="showCreateToken = false" class="px-4 py-2 text-slate-400 hover:text-white">Cancel</button>
            <button @click="createToken" :disabled="!newToken.name || newToken.scopes.length === 0" class="glass-button">Create Token</button>
          </div>
        </div>
      </div>

      <!-- Show Created Token Modal -->
      <div v-if="createdToken" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div class="glass-panel p-6 rounded-lg w-full max-w-lg">
          <h3 class="text-xl font-semibold text-emerald-400 mb-4">✅ Token Created!</h3>
          <div class="bg-yellow-500/10 border border-yellow-500/30 rounded-lg p-4 mb-4">
            <p class="text-yellow-200 text-sm">⚠️ Copy this token now. You won't be able to see it again!</p>
          </div>
          <div class="bg-black/30 rounded-lg p-4 font-mono text-sm break-all text-emerald-300">{{ createdToken.key }}</div>
          <div class="flex justify-between items-center mt-4">
            <button @click="copyToken" class="text-blue-400 hover:text-blue-300 text-sm">📋 Copy to clipboard</button>
            <button @click="createdToken = null; loadTokens()" class="glass-button">Done</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import axios from 'axios'

const activeTab = ref('system')

// System Configuration
const loadingSystem = ref(true)
const savingSystem = ref(false)
const systemMessage = ref('')
const systemMessageClass = ref('')

const systemForm = reactive({
    domain: '',
    argocd_url: '',
  cluster_ssh_host: '',
    vault_hostname: '',
    vault_addr: '',
    vault_token: '',
    vault_token_masked: '',
    tailscale_dns_suffix: '',
    bitbucket_workspace: '',
    templates_repo: '',
    logs_retention_days: 90,
    logs_forwarding_webhook_url: '',
    logs_forwarding_webhook_url_masked: '',
    logs_forwarding_min_level: 'error'
})

const showVaultToken = ref(false)

// Credentials
const loadingCreds = ref(true)
const showGitToken = ref(false)
const saving = ref(false)
const message = ref('')
const messageClass = ref('')

const credentials = reactive({
    git_username: '',
    git_token_masked: '****',
    bitbucket_email: '',
    bitbucket_workspace: '',
    infra_repo_url: '',
    domain: '',
    dockerhub_username: '',
    dockerhub_token_masked: '****'
})

const form = reactive({
    git_username: '',
    git_token: '',
    bitbucket_email: '',
    dockerhub_username: '',
    dockerhub_token: ''
})

// Tokens
const loadingTokens = ref(true)
const tokens = ref([])
const showCreateToken = ref(false)
const createdToken = ref(null)
const availableScopes = ['read', 'write', 'apps:create', 'apps:delete', 'templates:manage', 'admin']
const newToken = reactive({ name: '', scopes: ['read'] })

onMounted(async () => {
    await Promise.all([loadSystemSettings(), loadCredentials(), loadTokens()])
})

const loadSystemSettings = async () => {
    loadingSystem.value = true
    try {
        const { data } = await axios.get('/api/v1/admin/settings')
        Object.assign(systemForm, data)
    } catch (e) {
        console.error('Failed to load system settings:', e)
        systemMessage.value = 'Failed to load settings'
        systemMessageClass.value = 'bg-red-900/50 text-red-200 border border-red-500/20'
    } finally {
        loadingSystem.value = false
    }
}

const saveSystemSettings = async () => {
    savingSystem.value = true
    systemMessage.value = ''
    try {
        // Build payload excluding display-only fields
        const payload = { ...systemForm }
        delete payload.vault_token_masked
        delete payload.logs_forwarding_webhook_url_masked
        // Only send vault_token if actually changed (not empty)
        if (!payload.vault_token) delete payload.vault_token
        if (!payload.logs_forwarding_webhook_url) delete payload.logs_forwarding_webhook_url
        await axios.put('/api/v1/admin/settings', payload)
        systemMessage.value = 'System configuration saved successfully.'
        systemMessageClass.value = 'bg-emerald-900/50 text-emerald-200 border border-emerald-500/20'
        // Reload to get updated masked values
        await loadSystemSettings()
        systemForm.vault_token = ''
    } catch (e) {
        systemMessage.value = 'Failed to save settings: ' + (e.response?.data?.detail || e.message)
        systemMessageClass.value = 'bg-red-900/50 text-red-200 border border-red-500/20'
    } finally {
        savingSystem.value = false
    }
}

const loadCredentials = async () => {
    loadingCreds.value = true
    try {
        const { data } = await axios.get('/api/v1/system/credentials')
        Object.assign(credentials, data)
        form.git_username = data.git_username
        form.bitbucket_email = data.bitbucket_email
        form.dockerhub_username = data.dockerhub_username
    } catch (e) {
        console.error('Failed to load credentials:', e)
    } finally {
        loadingCreds.value = false
    }
}

const saveSettings = async () => {
    saving.value = true
    message.value = ''
    try {
        const payload = {}
        if (form.git_username) payload.git_username = form.git_username
        if (form.git_token) payload.git_token = form.git_token
        if (form.bitbucket_email) payload.bitbucket_email = form.bitbucket_email
        if (form.dockerhub_username) payload.dockerhub_username = form.dockerhub_username
        if (form.dockerhub_token) payload.dockerhub_token = form.dockerhub_token

        await axios.put('/api/v1/system/credentials', payload)
        message.value = 'Settings saved successfully.'
        messageClass.value = 'bg-emerald-900/50 text-emerald-200 border border-emerald-500/20'
        await loadCredentials()
        form.git_token = ''
        form.dockerhub_token = ''
    } catch (e) {
        message.value = 'Failed to save settings: ' + (e.response?.data?.detail || e.message)
        messageClass.value = 'bg-red-900/50 text-red-200 border border-red-500/20'
    } finally {
        saving.value = false
    }
}

const loadTokens = async () => {
    loadingTokens.value = true
    try {
        const { data } = await axios.get('/api/v1/system/tokens')
        tokens.value = data
    } catch (e) {
        console.error('Failed to load tokens:', e)
    } finally {
        loadingTokens.value = false
    }
}

const createToken = async () => {
    try {
        const { data } = await axios.post('/api/v1/system/tokens', { name: newToken.name, scopes: newToken.scopes })
        createdToken.value = data
        showCreateToken.value = false
        newToken.name = ''
        newToken.scopes = ['read']
    } catch (e) {
        alert('Failed to create token: ' + (e.response?.data?.detail || e.message))
    }
}

const revokeToken = async (tokenId) => {
    if (!confirm('Are you sure you want to revoke this token?')) return
    try {
        await axios.delete(`/api/v1/system/tokens/${tokenId}`)
        await loadTokens()
    } catch (e) {
        alert('Failed to revoke token: ' + (e.response?.data?.detail || e.message))
    }
}

const copyToken = () => {
    navigator.clipboard.writeText(createdToken.value.key)
    alert('Token copied to clipboard!')
}

const formatDate = (dateStr) => new Date(dateStr).toLocaleDateString()
</script>
