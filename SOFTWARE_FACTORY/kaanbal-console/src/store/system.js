import { reactive, ref } from 'vue'
import api from '@/services/api'

// System state
export const systemState = reactive({
    // Sync status
    isSyncing: false,
    syncProgress: null,
    lastSyncAt: null,
    lastSyncResult: null,
    lastSyncErrors: [],
    
    // System health
    health: null,
    
    // System stats
    stats: null,
    
    // Loading states
    isLoadingHealth: false,
    isLoadingStats: false
})

// Error state
export const systemError = ref(null)

/**
 * Trigger global sync
 * Syncs ArgoCD status and pipeline status for all apps
 */
export const triggerGlobalSync = async () => {
    if (systemState.isSyncing) {
        return { status: 'already_running' }
    }
    
    try {
        systemState.isSyncing = true
        systemState.syncProgress = { stage: 'starting', percent: 0 }
        systemError.value = null
        
        const response = await api.post('/system/sync')
        
        // Start polling for status
        pollSyncStatus()
        
        return response.data
    } catch (error) {
        console.error('Failed to trigger sync:', error)
        systemError.value = error.response?.data?.detail || 'Failed to start sync'
        systemState.isSyncing = false
        throw error
    }
}

/**
 * Poll sync status until complete
 */
let pollInterval = null
export const pollSyncStatus = async () => {
    // Clear any existing poll
    if (pollInterval) {
        clearInterval(pollInterval)
    }
    
    pollInterval = setInterval(async () => {
        try {
            const response = await api.get('/system/sync/status')
            const data = response.data
            
            systemState.isSyncing = data.is_syncing
            systemState.syncProgress = data.progress
            systemState.lastSyncAt = data.last_sync_at
            systemState.lastSyncResult = data.last_sync_result
            systemState.lastSyncErrors = data.last_sync_errors || []
            
            // Stop polling when sync is complete
            if (!data.is_syncing) {
                clearInterval(pollInterval)
                pollInterval = null
                
                // Emit custom event for components to refresh
                window.dispatchEvent(new CustomEvent('kaanbal:sync-complete', { 
                    detail: data.last_sync_result 
                }))
            }
        } catch (error) {
            console.error('Failed to get sync status:', error)
            clearInterval(pollInterval)
            pollInterval = null
            systemState.isSyncing = false
        }
    }, 1000) // Poll every second
}

/**
 * Get sync status without polling
 */
export const getSyncStatus = async () => {
    try {
        const response = await api.get('/system/sync/status')
        const data = response.data
        
        systemState.isSyncing = data.is_syncing
        systemState.syncProgress = data.progress
        systemState.lastSyncAt = data.last_sync_at
        systemState.lastSyncResult = data.last_sync_result
        systemState.lastSyncErrors = data.last_sync_errors || []
        
        // If syncing, start polling
        if (data.is_syncing && !pollInterval) {
            pollSyncStatus()
        }
        
        return data
    } catch (error) {
        console.error('Failed to get sync status:', error)
        throw error
    }
}

/**
 * Get system health
 */
export const getSystemHealth = async () => {
    try {
        systemState.isLoadingHealth = true
        const response = await api.get('/system/health')
        systemState.health = response.data
        return response.data
    } catch (error) {
        console.error('Failed to get system health:', error)
        systemState.health = { status: 'error', error: error.message }
        throw error
    } finally {
        systemState.isLoadingHealth = false
    }
}

/**
 * Get system stats
 */
export const getSystemStats = async () => {
    try {
        systemState.isLoadingStats = true
        const response = await api.get('/system/stats')
        systemState.stats = response.data
        return response.data
    } catch (error) {
        console.error('Failed to get system stats:', error)
        throw error
    } finally {
        systemState.isLoadingStats = false
    }
}

/**
 * Format time ago
 */
export const formatTimeAgo = (dateString) => {
    if (!dateString) return 'Never'
    
    const date = new Date(dateString)
    const now = new Date()
    const seconds = Math.floor((now - date) / 1000)
    
    if (seconds < 60) return 'Just now'
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`
    return `${Math.floor(seconds / 86400)}d ago`
}
