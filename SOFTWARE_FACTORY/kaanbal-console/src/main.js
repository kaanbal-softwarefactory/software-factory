
import './index.css'

import { createApp } from 'vue'
import App from './App.vue'
import router from './router'

import axios from 'axios'
import { getApiUrl } from './config'

// Global Axios defaults - uses VITE_API_URL env var, empty in production (same-origin)
const API_URL = getApiUrl()
axios.defaults.baseURL = API_URL

if (API_URL) {
  console.log('[kaanbal] API URL:', API_URL)
}

axios.interceptors.request.use(config => {
    const token = localStorage.getItem('kaanbal_token')
    if (token) {
        config.headers.Authorization = `Bearer ${token}`
    }
    return config
})

const app = createApp(App)

app.use(router)
app.mount('#app')
