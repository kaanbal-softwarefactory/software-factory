import axios from 'axios'
import { authState, logout } from '@/store/auth'
import router from '@/router'

// Create axios instance with default config
const api = axios.create({
    baseURL: '/api/v1',
    timeout: 30000,
    headers: {
        'Content-Type': 'application/json'
    }
})

// Request interceptor - add auth token
api.interceptors.request.use(
    (config) => {
        if (authState.token) {
            config.headers.Authorization = `Bearer ${authState.token}`
        }
        return config
    },
    (error) => {
        return Promise.reject(error)
    }
)

// Response interceptor - handle auth errors
api.interceptors.response.use(
    (response) => response,
    (error) => {
        // Handle 401 Unauthorized - only logout if there was an active session
        if (error.response?.status === 401 && authState.isAuthenticated) {
            logout()
            router.push('/login')
        }
        return Promise.reject(error)
    }
)

export default api
