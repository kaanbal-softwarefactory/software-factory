/**
 * Kaanbal Console - Centralized Configuration
 * ==========================================
 * Single source of truth for all configurable values.
 * 
 * Priority:
 *   1. Runtime config from API (/api/v1/admin/settings-public) - loaded on mount
 *   2. Build-time env vars (VITE_*) - baked into the build
 *   3. Fallback defaults below
 */
import { reactive } from 'vue'

// Build-time configuration from environment variables
const buildConfig = {
  apiUrl: import.meta.env.VITE_API_URL || '',
  domain: import.meta.env.VITE_DOMAIN || '',
  argocdUrl: import.meta.env.VITE_ARGOCD_URL || '',
  tailscaleSuffix: import.meta.env.VITE_TAILSCALE_SUFFIX || '',
}

// Runtime configuration (loaded from API, overrides build config)
export const runtimeConfig = reactive({
  domain: '',
  argocd_url: '',
  cluster_ssh_host: '',
  vault_hostname: '',
  tailscale_dns_suffix: '',
  git_provider: 'bitbucket',
  bitbucket_workspace: '',
  github_org: '',
  templates_repo: '',
  loaded: false,
})

/**
 * Load runtime configuration from the public settings API.
 * Called once on app mount. Non-blocking - falls back to build config on failure.
 */
export async function loadRuntimeConfig() {
  try {
    const response = await fetch((buildConfig.apiUrl || '') + '/api/v1/admin/settings-public')
    if (response.ok) {
      const data = await response.json()
      Object.assign(runtimeConfig, data, { loaded: true })
    }
  } catch (e) {
    console.warn('[config] Could not load runtime config:', e.message)
  }
}

/**
 * Get a configuration value with runtime > build-time > fallback priority.
 */
export function getConfig(key, fallback = '') {
  const runtimeMap = {
    domain: runtimeConfig.domain,
    argocdUrl: runtimeConfig.argocd_url,
    clusterSshHost: runtimeConfig.cluster_ssh_host,
    tailscaleSuffix: runtimeConfig.tailscale_dns_suffix,
    vaultHostname: runtimeConfig.vault_hostname,
    gitProvider: runtimeConfig.git_provider,
    bitbucketWorkspace: runtimeConfig.bitbucket_workspace,
    githubOrg: runtimeConfig.github_org,
    templatesRepo: runtimeConfig.templates_repo,
    gitNamespace: runtimeConfig.git_provider === 'github' ? runtimeConfig.github_org : runtimeConfig.bitbucket_workspace,
  }

  return runtimeMap[key] || buildConfig[key] || fallback
}

/**
 * Get the API base URL (used by axios).
 */
export function getApiUrl() {
  return buildConfig.apiUrl
}

export default buildConfig
