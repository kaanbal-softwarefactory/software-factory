import { reactive } from 'vue'

/**
 * Decode JWT payload (no validation - that's the backend's job)
 */
function decodeToken(token) {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]))
        return payload
    } catch {
        return null
    }
}

/**
 * Check if a token is expired
 */
function isTokenExpired(token) {
    const payload = decodeToken(token)
    if (!payload || !payload.exp) return true
    // exp is in seconds, Date.now() in ms
    return Date.now() >= payload.exp * 1000
}

function getInitialState() {
    const token = localStorage.getItem('kaanbal_token')
    if (token && !isTokenExpired(token)) {
        const payload = decodeToken(token)
        return {
            token,
            isAuthenticated: true,
            username: payload?.sub || null,
            role: payload?.role || 'user'
        }
    }
    // Token absent or expired - clear it
    localStorage.removeItem('kaanbal_token')
    return {
        token: null,
        isAuthenticated: false,
        username: null,
        role: null
    }
}

export const authState = reactive(getInitialState())

export const login = (token) => {
    const payload = decodeToken(token)
    localStorage.setItem('kaanbal_token', token)
    authState.token = token
    authState.isAuthenticated = true
    authState.username = payload?.sub || null
    authState.role = payload?.role || 'user'
}

export const logout = () => {
    localStorage.removeItem('kaanbal_token')
    authState.token = null
    authState.isAuthenticated = false
    authState.username = null
    authState.role = null
}

/**
 * Check token validity (call periodically or before API calls)
 */
export const checkAuth = () => {
    const token = localStorage.getItem('kaanbal_token')
    if (!token || isTokenExpired(token)) {
        if (authState.isAuthenticated) {
            logout()
        }
        return false
    }
    return true
}
