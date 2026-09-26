<template>
  <div class="min-h-screen flex items-center justify-center p-4">
    <div class="glass-panel w-full max-w-md p-8 rounded-2xl relative overflow-hidden">
        <!-- Background Glow -->
        <div class="absolute top-0 right-0 w-64 h-64 bg-blue-500/10 rounded-full blur-3xl pointer-events-none -translate-y-1/2 translate-x-1/2"></div>
        
        <div class="text-center mb-8 relative z-10">
             <div class="w-16 h-16 rounded-xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-blue-500/30 mx-auto mb-4">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-8 h-8 text-white">
                    <path fill-rule="evenodd" d="M9.315 7.584C12.195 3.883 16.695 1.5 21.75 1.5a.75.75 0 01.75.75c0 5.056-2.383 9.555-6.084 12.436A6.753 6.753 0 0119.75 20.25a.75.75 0 01-1.5 0 2.25 2.25 0 00-2.25-2.25.75.75 0 010-1.5c.875 0 1.714.16 2.492.457A9.006 9.006 0 0021 16.5c0-4.66-3.56-8.495-8.156-8.916zM6.671 18.006A6.746 6.746 0 011.5 15.75a.75.75 0 011.5 0 2.25 2.25 0 002.25 2.25.75.75 0 010 1.5c0 .875.16 1.714.457 2.492A9.006 9.006 0 009.75 21a.75.75 0 01.75.75 6.753 6.753 0 01-3.829-3.744z" clip-rule="evenodd" />
                </svg>
            </div>
            <h1 class="text-2xl font-bold text-white">Welcome Back</h1>
            <p class="text-slate-400">Sign in to access your Factory Console</p>
        </div>

        <form @submit.prevent="handleLogin" class="space-y-6 relative z-10">
            <div>
                <label class="block text-sm font-medium text-slate-300 mb-1">Username</label>
                <input v-model="username" type="text" class="glass-input w-full" placeholder="admin" required />
            </div>

            <div>
                <label class="block text-sm font-medium text-slate-300 mb-1">Password</label>
                <input v-model="password" type="password" class="glass-input w-full" placeholder="••••••••" required />
            </div>

            <button type="submit" :disabled="loading" class="w-full glass-button flex justify-center items-center">
                 <span v-if="loading" class="animate-spin mr-2">⚙️</span>
                 {{ loading ? 'Signing in...' : 'Sign In' }}
            </button>
            
            <div v-if="error" class="p-3 bg-red-900/40 border border-red-500/20 rounded-lg text-sm text-red-200 text-center">
                {{ error }}
            </div>
        </form>
        
        <div class="mt-6 text-center text-xs text-slate-500">
            <p>Protected by Kaanbal Security</p>
        </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { login } from '@/store/auth'

const router = useRouter()
const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

const handleLogin = async () => {
    loading.value = true
    error.value = ''
    
    try {
        const formData = new FormData()
        formData.append('username', username.value)
        formData.append('password', password.value)

        // API Call - usa el baseURL configurado en main.js
        const response = await axios.post('/api/v1/auth/token', formData)
        
        // Store Token & update auth state
        login(response.data.access_token)

        // Redirect
        router.push('/dashboard')

    } catch (e) {
        if (e.response && e.response.status === 401) {
            error.value = 'Invalid credentials'
        } else {
            error.value = 'Connection failed. Is the API reachable?'
        }
    } finally {
        loading.value = false
    }
}
</script>
