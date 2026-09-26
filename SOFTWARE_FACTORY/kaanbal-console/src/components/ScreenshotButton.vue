<template>
  <div class="fixed bottom-6 right-6 z-[9999] flex flex-col items-end gap-2">
    <!-- Toast feedback -->
    <Transition name="screenshot-toast">
      <div v-if="toast" :class="['px-4 py-2 rounded-lg text-sm font-medium shadow-lg border backdrop-blur-sm', toastClasses]">
        {{ toast }}
      </div>
    </Transition>

    <!-- Screenshot Button -->
    <button
      @click="takeScreenshot"
      :disabled="capturing"
      class="group flex items-center gap-2 px-4 py-3 rounded-full shadow-2xl transition-all duration-300 border"
      :class="capturing 
        ? 'bg-blue-600/80 border-blue-400/50 cursor-wait scale-95' 
        : 'bg-slate-800/90 border-white/10 hover:bg-slate-700/90 hover:border-blue-500/50 hover:shadow-blue-500/20 hover:scale-105'"
      title="Take Screenshot (Ctrl+Shift+S)"
    >
      <!-- Camera Icon / Spinner -->
      <svg v-if="!capturing" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-slate-300 group-hover:text-blue-400 transition-colors">
        <path stroke-linecap="round" stroke-linejoin="round" d="M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316z" />
        <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0zM18.75 10.5h.008v.008h-.008V10.5z" />
      </svg>
      <svg v-else class="w-5 h-5 text-white animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
        <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
        <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
      </svg>
      
      <span class="text-sm font-medium" :class="capturing ? 'text-white' : 'text-slate-300 group-hover:text-white'">
        {{ capturing ? 'Capturing...' : '📸' }}
      </span>
    </button>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import html2canvas from 'html2canvas-pro'

const capturing = ref(false)
const toast = ref('')
const toastClasses = ref('')

let toastTimeout = null

const showToast = (message, type = 'success') => {
  clearTimeout(toastTimeout)
  toast.value = message
  toastClasses.value = type === 'success' 
    ? 'bg-emerald-500/20 border-emerald-500/30 text-emerald-300' 
    : 'bg-red-500/20 border-red-500/30 text-red-300'
  toastTimeout = setTimeout(() => { toast.value = '' }, 3000)
}

const takeScreenshot = async () => {
  if (capturing.value) return
  capturing.value = true

  try {
    // Hide the screenshot button itself during capture
    const btn = document.querySelector('.screenshot-btn-container')
    
    const canvas = await html2canvas(document.body, {
      backgroundColor: '#0f172a',
      scale: 2,
      useCORS: true,
      logging: false,
      ignoreElements: (el) => el.classList?.contains('screenshot-ignore')
    })

    // Try clipboard first, fallback to download
    try {
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'))
      await navigator.clipboard.write([
        new ClipboardItem({ 'image/png': blob })
      ])
      showToast('✅ Copied to clipboard!')
    } catch {
      // Clipboard failed — fallback to download
      const link = document.createElement('a')
      const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
      link.download = `kaanbal-screenshot-${timestamp}.png`
      link.href = canvas.toDataURL('image/png')
      link.click()
      showToast('✅ Screenshot downloaded!')
    }
  } catch (err) {
    console.error('Screenshot failed:', err)
    showToast('❌ Screenshot failed', 'error')
  } finally {
    capturing.value = false
  }
}

// Keyboard shortcut: Ctrl+Shift+S
const handleKeydown = (e) => {
  if (e.ctrlKey && e.shiftKey && e.key === 'S') {
    e.preventDefault()
    takeScreenshot()
  }
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleKeydown))
</script>

<style scoped>
.screenshot-toast-enter-active,
.screenshot-toast-leave-active {
  transition: all 0.3s ease;
}
.screenshot-toast-enter-from,
.screenshot-toast-leave-to {
  opacity: 0;
  transform: translateY(10px);
}
</style>
