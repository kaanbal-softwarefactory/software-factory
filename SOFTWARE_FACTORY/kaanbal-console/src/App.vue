<template>
  <div class="flex h-screen w-full overflow-hidden">
    <!-- Sidebar (authenticated only) -->
    <aside v-if="authState.isAuthenticated" class="w-64 glass-panel border-r border-white/5 flex flex-col z-20">
      <div class="p-6 flex items-center gap-3">
        <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-lg shadow-blue-500/30">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-5 h-5 text-white">
            <path fill-rule="evenodd" d="M9.315 7.584C12.195 3.883 16.695 1.5 21.75 1.5a.75.75 0 01.75.75c0 5.056-2.383 9.555-6.084 12.436A6.753 6.753 0 0119.75 20.25a.75.75 0 01-1.5 0 2.25 2.25 0 00-2.25-2.25.75.75 0 010-1.5c.875 0 1.714.16 2.492.457A9.006 9.006 0 0021 16.5c0-4.66-3.56-8.495-8.156-8.916zM6.671 18.006A6.746 6.746 0 011.5 15.75a.75.75 0 011.5 0 2.25 2.25 0 002.25 2.25.75.75 0 010 1.5c0 .875.16 1.714.457 2.492A9.006 9.006 0 009.75 21a.75.75 0 01.75.75 6.753 6.753 0 01-3.829-3.744z" clip-rule="evenodd" />
          </svg>
        </div>
        <h1 class="text-lg font-bold tracking-tight text-white">Kaanbal<span class="text-blue-400">Console</span></h1>
      </div>

      <nav class="flex-1 px-4 space-y-2 mt-4">
        <router-link to="/dashboard" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
          </svg>
          <span class="font-medium">Dashboard</span>
        </router-link>

        <router-link to="/apps" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21 7.5l-9-5.25L3 7.5m18 0l-9 5.25m9-5.25v9l-9 5.25M3 7.5l9 5.25M3 7.5v9l9 5.25m0-9v9" />
          </svg>
          <span class="font-medium">Applications</span>
        </router-link>

        <router-link to="/templates" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 4.5l7.5 7.5-7.5 7.5m-6-15l7.5 7.5-7.5 7.5" />
          </svg>
          <span class="font-medium">Templates</span>
        </router-link>

        <router-link to="/stacks" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M6.429 9.75L2.25 12l4.179 2.25m0-4.5l5.571 3 5.571-3m-11.142 0L2.25 7.5 12 2.25l9.75 5.25-4.179 2.25m0 0L21.75 12l-4.179 2.25m0 0l4.179 2.25L12 21.75 2.25 16.5l4.179-2.25m11.142 0l-5.571 3-5.571-3" />
          </svg>
          <span class="font-medium">Stacks</span>
        </router-link>

        <router-link to="/settings" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.324.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.24-.438.613-.431.992a6.759 6.759 0 010 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.992a6.932 6.932 0 010-.255c.007-.378-.138-.75-.43-.99l-1.004-.828a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281z" />
            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span class="font-medium">Settings</span>
        </router-link>

        <router-link to="/logs" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M19.5 13.5V19.125A2.625 2.625 0 0116.875 21.75H7.125A2.625 2.625 0 014.5 19.125V4.875A2.625 2.625 0 017.125 2.25h7.5A2.625 2.625 0 0117.25 4.875V6.75m-8.25 4.5h6.75m-6.75 3h4.5m5.25-6.75l-3-3m0 0l-3 3m3-3V15" />
          </svg>
          <span class="font-medium">Logs</span>
        </router-link>

         <div class="pt-4 pb-2">
          <p class="px-2 text-xs font-semibold text-slate-500 uppercase tracking-wider">Infrastructure</p>
        </div>

        <router-link to="/domains" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
          </svg>
          <span class="font-medium">Domains</span>
        </router-link>

        <router-link to="/security" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
          </svg>
          <span class="font-medium">Acceso</span>
        </router-link>

        <router-link to="/updates" class="nav-item" active-class="active">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 7.5h-.75A2.25 2.25 0 004.5 9.75v7.5a2.25 2.25 0 002.25 2.25h7.5a2.25 2.25 0 002.25-2.25v-7.5a2.25 2.25 0 00-2.25-2.25h-.75m-6 3.75l3-3m0 0l3 3m-3-3v11.25m6-2.25h.75a2.25 2.25 0 002.25-2.25v-7.5a2.25 2.25 0 00-2.25-2.25h-.75" />
          </svg>
          <span class="font-medium">Updates</span>
          <span
            v-if="engine.updateAvailable"
            class="ml-auto flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300"
            :title="engine.pendingLabel"
          >
            <span class="relative flex h-2 w-2">
              <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
              <span class="relative inline-flex rounded-full h-2 w-2 bg-amber-400"></span>
            </span>
            Nuevo
          </span>
        </router-link>

        <button @click="infraModal.show = true" class="nav-item group w-full">
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 group-hover:text-orange-400 transition-colors">
            <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
          </svg>
          <span class="font-medium">Infrastructure</span>
        </button>
      </nav>

      <!-- Status Indicator -->
      <div class="p-4 border-t border-white/5 bg-slate-900/40">
        <div class="flex items-center gap-3">
          <div class="relative flex h-3 w-3">
            <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span class="relative inline-flex rounded-full h-3 w-3 bg-emerald-500"></span>
          </div>
          <div class="flex flex-col">
            <span class="text-xs font-medium text-white">System Online</span>
            <router-link
              to="/updates"
              class="text-[10px] font-mono hover:underline"
              :class="engine.updateAvailable ? 'text-amber-300' : 'text-slate-400'"
              :title="engine.updateAvailable ? engine.pendingLabel : 'Versión del engine en esta célula'"
            >{{ engine.version }}</router-link>
          </div>
        </div>
      </div>
      <div class="px-4 py-4 border-t border-white/5">
             <button @click="handleLogout" class="flex items-center gap-3 w-full px-4 py-3 rounded-xl text-slate-400 hover:text-white hover:bg-white/5 transition-colors">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M15.75 9V5.25A2.25 2.25 0 0013.5 3h-6a2.25 2.25 0 00-2.25 2.25v13.5A2.25 2.25 0 007.5 21h6a2.25 2.25 0 002.25-2.25V15m3 0l3-3m0 0l-3-3m3 3H9" />
                </svg>
                <span class="font-medium">Sign Out</span>
             </button>
        </div>
    </aside>

    <!-- Main Content -->
    <main class="flex-1 overflow-auto bg-slate-900 relative">
      <div class="absolute inset-0 bg-[radial-gradient(circle_at_50%_120%,rgba(120,119,198,0.1),rgba(0,0,0,0))]"></div>
      <div class="relative z-10 p-8 container mx-auto">
        <header v-if="authState.isAuthenticated" class="mb-8 flex items-center justify-between">
          <div>
            <h2 class="text-2xl font-bold text-white mb-1">Project Wizard</h2>
            <p class="text-slate-400">Deploy a new production-ready application in seconds.</p>
          </div>
          
          <div class="flex items-center gap-4">
            <!-- Global Sync Button -->
            <div class="relative">
              <button 
                @click="handleGlobalSync"
                :disabled="systemState.isSyncing"
                class="flex items-center gap-2 px-4 py-2 rounded-lg transition-all duration-200"
                :class="systemState.isSyncing 
                  ? 'bg-blue-500/20 text-blue-400 cursor-wait' 
                  : 'bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-white/10'"
              >
                <!-- Sync Icon with Animation -->
                <svg 
                  xmlns="http://www.w3.org/2000/svg" 
                  fill="none" 
                  viewBox="0 0 24 24" 
                  stroke-width="1.5" 
                  stroke="currentColor" 
                  class="w-5 h-5"
                  :class="{ 'animate-spin': systemState.isSyncing }"
                >
                  <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                </svg>
                <span class="text-sm font-medium">
                  {{ systemState.isSyncing ? 'Syncing...' : 'Sync All' }}
                </span>
              </button>
              
              <!-- Sync Progress Tooltip -->
              <div 
                v-if="systemState.isSyncing && systemState.syncProgress"
                class="absolute top-full right-0 mt-2 w-64 p-3 bg-slate-800 rounded-lg border border-white/10 shadow-xl"
              >
                <div class="flex items-center justify-between mb-2">
                  <span class="text-xs text-slate-400 capitalize">{{ systemState.syncProgress.stage?.replace('_', ' ') }}</span>
                  <span class="text-xs font-mono text-blue-400">{{ systemState.syncProgress.percent }}%</span>
                </div>
                <div class="w-full bg-slate-700 rounded-full h-1.5">
                  <div 
                    class="bg-blue-500 h-1.5 rounded-full transition-all duration-300" 
                    :style="{ width: `${systemState.syncProgress.percent}%` }"
                  ></div>
                </div>
                <p v-if="systemState.syncProgress.current_app" class="text-xs text-slate-500 mt-2 truncate">
                  Processing: {{ systemState.syncProgress.current_app }}
                </p>
              </div>
            </div>
            
            <!-- Last Sync Indicator -->
            <div 
              v-if="systemState.lastSyncAt && !systemState.isSyncing"
              class="text-xs text-slate-500"
              :title="`Last sync: ${new Date(systemState.lastSyncAt).toLocaleString()}`"
            >
              Synced {{ formatTimeAgo(systemState.lastSyncAt) }}
            </div>
            
            <div class="h-10 w-10 rounded-full bg-slate-800 border border-white/10 flex items-center justify-center text-slate-400">
              <span class="text-sm font-bold">AB</span>
            </div>
          </div>
        </header>

        <div class="relative">
          <router-view></router-view>
        </div>
      </div>
    </main>
    
    <!-- Sync Complete Toast -->
    <Teleport to="body">
      <Transition name="toast">
        <div 
          v-if="showSyncToast"
          class="fixed bottom-6 right-6 z-50 flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg"
          :class="syncToastType === 'success' 
            ? 'bg-emerald-500/20 border border-emerald-500/30 text-emerald-300' 
            : 'bg-amber-500/20 border border-amber-500/30 text-amber-300'"
        >
          <svg v-if="syncToastType === 'success'" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
            <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clip-rule="evenodd" />
          </svg>
          <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-5 h-5">
            <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
          </svg>
          <span class="text-sm font-medium">{{ syncToastMessage }}</span>
        </div>
      </Transition>
    </Teleport>
    
    <!-- Background Decor -->
    <div class="absolute top-0 right-0 w-[500px] h-[500px] bg-blue-600/10 rounded-full blur-[120px] pointer-events-none -z-0 translate-x-1/2 -translate-y-1/2"></div>
    <div class="absolute bottom-0 left-0 w-[500px] h-[500px] bg-purple-600/10 rounded-full blur-[120px] pointer-events-none -z-0 -translate-x-1/2 translate-y-1/2"></div>

    <!-- Node fleet (phase 0) -->
    <NodeFleet class="screenshot-ignore" />

    <!-- Screenshot Floating Button -->
    <ScreenshotButton class="screenshot-ignore" />

    <!-- Infrastructure Modal -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="infraModal.show" class="fixed inset-0 z-50 flex items-center justify-center p-4">
          <!-- Backdrop -->
          <div class="absolute inset-0 bg-black/70 backdrop-blur-sm" @click="infraModal.show = false"></div>

          <!-- Modal Content -->
          <div class="relative bg-gradient-to-b from-slate-800 to-slate-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-3xl overflow-hidden transform transition-all">
            <!-- Accent Bar -->
            <div class="h-1 bg-gradient-to-r from-orange-500 via-amber-500 to-orange-500"></div>

            <!-- Header -->
            <div class="flex items-center justify-between px-6 pt-5 pb-4">
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500/20 to-amber-500/20 border border-orange-500/20 flex items-center justify-center">
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-orange-400">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
                  </svg>
                </div>
                <div>
                  <h3 class="text-lg font-semibold text-white">Infrastructure</h3>
                  <p class="text-xs text-slate-400">Core services and cluster management</p>
                </div>
              </div>
              <button @click="infraModal.show = false" class="text-slate-400 hover:text-white transition-colors p-1 rounded-lg hover:bg-white/5">
                <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <!-- Tabs -->
            <div class="px-6 flex gap-1 border-b border-white/5">
              <button
                v-for="tab in infraTabs"
                :key="tab.id"
                @click="infraModal.activeTab = tab.id"
                class="relative px-4 py-2.5 text-sm font-medium rounded-t-lg transition-all"
                :class="infraModal.activeTab === tab.id
                  ? 'text-orange-400 bg-orange-500/10'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'"
              >
                <span class="flex items-center gap-2">
                  <component :is="'span'" v-html="tab.icon" />
                  {{ tab.label }}
                </span>
                <div v-if="infraModal.activeTab === tab.id" class="absolute bottom-0 left-0 right-0 h-0.5 bg-orange-400 rounded-full"></div>
              </button>
            </div>

            <!-- Tab Content -->
            <div class="p-6 max-h-[65vh] overflow-y-auto">

              <!-- ========== OVERVIEW TAB ========== -->
              <div v-if="infraModal.activeTab === 'overview'" class="space-y-6">
                <div class="grid grid-cols-2 md:grid-cols-3 gap-3">
                  <!-- ArgoCD Card -->
                  <div class="p-4 rounded-xl border border-white/5 bg-slate-800/40 hover:border-orange-500/20 transition-all group">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="w-9 h-9 rounded-lg bg-orange-500/10 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-orange-400">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 006.16-12.12A14.98 14.98 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 01-2.448-2.448 14.9 14.9 0 01.06-.312m-2.24 2.39a4.493 4.493 0 00-1.757 4.306 4.493 4.493 0 004.306-1.758M16.5 9a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z" />
                        </svg>
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-semibold text-white">ArgoCD</span>
                          <span class="flex h-2 w-2 rounded-full" :class="infraModal.argoInfo.connected !== false ? 'bg-emerald-400' : 'bg-red-400'"></span>
                        </div>
                        <span class="text-[11px] text-slate-500">GitOps Delivery</span>
                      </div>
                    </div>
                    <div class="flex items-center justify-between text-xs">
                      <span class="text-slate-400">
                        <span class="text-white font-medium">{{ infraModal.argoInfo.totalApps ?? '-' }}</span> apps
                        <span class="mx-1 text-slate-600">|</span>
                        <span class="text-emerald-400 font-medium">{{ infraModal.argoInfo.healthyApps ?? '-' }}</span> healthy
                      </span>
                      <a :href="argoCdUrl" target="_blank" v-if="argoCdUrl" class="text-orange-400/60 hover:text-orange-400 transition-colors" title="Open ArgoCD">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" /></svg>
                      </a>
                    </div>
                  </div>

                  <!-- Vault Card -->
                  <div class="p-4 rounded-xl border border-white/5 bg-slate-800/40 hover:border-purple-500/20 transition-all group">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="w-9 h-9 rounded-lg bg-purple-500/10 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-purple-400">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" />
                        </svg>
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-semibold text-white">Vault</span>
                          <span class="flex h-2 w-2 rounded-full" :class="infraModal.vault.status?.reachable ? 'bg-emerald-400' : 'bg-amber-400'"></span>
                        </div>
                        <span class="text-[11px] text-slate-500">Secret Management</span>
                      </div>
                    </div>
                    <div class="flex items-center justify-between text-xs">
                      <span class="text-slate-400">
                        <span :class="infraModal.vault.status?.sealed === false ? 'text-emerald-400' : 'text-amber-400'" class="font-medium">
                          {{ infraModal.vault.status?.sealed === false ? 'Unsealed' : (infraModal.vault.status?.sealed ? 'Sealed' : '--') }}
                        </span>
                        <span v-if="infraModal.vault.status?.version" class="ml-1 text-slate-500">v{{ infraModal.vault.status.version }}</span>
                      </span>
                      <button @click="infraModal.activeTab = 'vault'" class="text-purple-400/60 hover:text-purple-400 transition-colors text-[11px]">
                        Browse secrets
                      </button>
                    </div>
                  </div>

                  <!-- MongoDB / Datastore Card -->
                  <div class="p-4 rounded-xl border border-white/5 bg-slate-800/40 hover:border-emerald-500/20 transition-all group">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="w-9 h-9 rounded-lg bg-emerald-500/10 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-emerald-400">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375m16.5 0v3.75m-16.5-3.75v3.75m16.5 0v3.75C20.25 16.153 16.556 18 12 18s-8.25-1.847-8.25-4.125v-3.75m16.5 0c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125" />
                        </svg>
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-semibold text-white">MongoDB</span>
                          <span class="flex h-2 w-2 rounded-full bg-emerald-400"></span>
                        </div>
                        <span class="text-[11px] text-slate-500">Datastore</span>
                      </div>
                    </div>
                    <div class="text-xs text-slate-400">
                      <span class="text-white font-medium">prod</span> namespace
                      <span class="mx-1 text-slate-600">|</span>
                      Tailscale-only
                    </div>
                  </div>

                  <!-- Tailscale Card -->
                  <div class="p-4 rounded-xl border border-white/5 bg-slate-800/40 hover:border-blue-500/20 transition-all group">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-blue-400">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
                        </svg>
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-semibold text-white">Tailscale</span>
                          <span class="flex h-2 w-2 rounded-full bg-emerald-400"></span>
                        </div>
                        <span class="text-[11px] text-slate-500">VPN Mesh</span>
                      </div>
                    </div>
                    <div class="text-xs text-slate-400 truncate" :title="infraModal.tailscaleSuffix">
                      <span class="text-slate-500 font-mono">{{ infraModal.tailscaleSuffix || '--' }}</span>
                    </div>
                  </div>

                  <!-- Cloudflare Card -->
                  <div class="p-4 rounded-xl border border-white/5 bg-slate-800/40 hover:border-amber-500/20 transition-all group">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="w-9 h-9 rounded-lg bg-amber-500/10 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-amber-400">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M12 21a9.004 9.004 0 008.716-6.747M12 21a9.004 9.004 0 01-8.716-6.747M12 21c2.485 0 4.5-4.03 4.5-9S14.485 3 12 3m0 18c-2.485 0-4.5-4.03-4.5-9S9.515 3 12 3m0 0a8.997 8.997 0 017.843 4.582M12 3a8.997 8.997 0 00-7.843 4.582m15.686 0A11.953 11.953 0 0112 10.5c-2.998 0-5.74-1.1-7.843-2.918m15.686 0A8.959 8.959 0 0121 12c0 .778-.099 1.533-.284 2.253m0 0A17.919 17.919 0 0112 16.5c-3.162 0-6.133-.815-8.716-2.247m0 0A9.015 9.015 0 013 12c0-1.605.42-3.113 1.157-4.418" />
                        </svg>
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-semibold text-white">Cloudflare</span>
                          <span class="flex h-2 w-2 rounded-full bg-emerald-400"></span>
                        </div>
                        <span class="text-[11px] text-slate-500">Tunnel + DNS</span>
                      </div>
                    </div>
                    <div class="text-xs text-slate-400 truncate">
                      <span class="text-slate-500 font-mono">{{ infraModal.domain || '--' }}</span>
                    </div>
                  </div>

                  <!-- Ingress Nginx Card -->
                  <div class="p-4 rounded-xl border border-white/5 bg-slate-800/40 hover:border-sky-500/20 transition-all group">
                    <div class="flex items-center gap-3 mb-3">
                      <div class="w-9 h-9 rounded-lg bg-sky-500/10 flex items-center justify-center">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-sky-400">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
                        </svg>
                      </div>
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <span class="text-sm font-semibold text-white">Nginx</span>
                          <span class="flex h-2 w-2 rounded-full bg-emerald-400"></span>
                        </div>
                        <span class="text-[11px] text-slate-500">Ingress Controller</span>
                      </div>
                    </div>
                    <div class="text-xs text-slate-400">
                      Public load balancer
                    </div>
                  </div>
                </div>

                <!-- Quick Stats -->
                <div class="p-4 rounded-xl bg-slate-800/30 border border-white/5">
                  <div class="flex items-center justify-between mb-3">
                    <h4 class="text-sm font-semibold text-slate-300">Cluster Summary</h4>
                    <span class="text-[11px] text-slate-500 font-mono">K3s</span>
                  </div>
                  <div class="grid grid-cols-4 gap-4 text-center">
                    <div>
                      <div class="text-xl font-bold text-white">{{ infraModal.argoInfo.totalApps ?? '-' }}</div>
                      <div class="text-[11px] text-slate-500 mt-0.5">ArgoCD Apps</div>
                    </div>
                    <div>
                      <div class="text-xl font-bold text-emerald-400">{{ infraModal.argoInfo.healthyApps ?? '-' }}</div>
                      <div class="text-[11px] text-slate-500 mt-0.5">Healthy</div>
                    </div>
                    <div>
                      <div class="text-xl font-bold" :class="(infraModal.argoInfo.syncedApps ?? 0) === (infraModal.argoInfo.totalApps ?? 0) ? 'text-emerald-400' : 'text-amber-400'">{{ infraModal.argoInfo.syncedApps ?? '-' }}</div>
                      <div class="text-[11px] text-slate-500 mt-0.5">Synced</div>
                    </div>
                    <div>
                      <div class="text-xl font-bold" :class="infraModal.vault.status?.sealed === false ? 'text-emerald-400' : 'text-amber-400'">
                        {{ infraModal.vault.status?.sealed === false ? 'OK' : '--' }}
                      </div>
                      <div class="text-[11px] text-slate-500 mt-0.5">Vault</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ========== ARGOCD TAB ========== -->
              <div v-if="infraModal.activeTab === 'argocd'">
                <!-- Quick Actions -->
                <div class="mb-6">
                  <h4 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Quick Actions</h4>
                  <div class="grid grid-cols-2 gap-3">
                    <!-- Hard Refresh -->
                    <button
                      @click="handleArgoRefresh"
                      :disabled="infraModal.refreshing"
                      class="flex items-center gap-3 p-4 rounded-xl border transition-all duration-200"
                      :class="infraModal.refreshing
                        ? 'bg-orange-500/10 border-orange-500/20 cursor-wait'
                        : 'bg-slate-800/50 border-white/5 hover:border-orange-500/30 hover:bg-orange-500/5'"
                    >
                      <div class="w-10 h-10 rounded-lg bg-orange-500/10 flex items-center justify-center shrink-0">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-orange-400" :class="{ 'animate-spin': infraModal.refreshing }">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0l3.181 3.183a8.25 8.25 0 0013.803-3.7M4.031 9.865a8.25 8.25 0 0113.803-3.7l3.181 3.182m0-4.991v4.99" />
                        </svg>
                      </div>
                      <div class="text-left">
                        <span class="block text-sm font-medium text-white">{{ infraModal.refreshing ? 'Refreshing...' : 'Force Refresh' }}</span>
                        <span class="block text-xs text-slate-400">Hard refresh all apps from Git</span>
                      </div>
                    </button>

                    <!-- Open ArgoCD UI -->
                    <a
                      :href="argoCdUrl"
                      target="_blank"
                      class="flex items-center gap-3 p-4 rounded-xl border bg-slate-800/50 border-white/5 hover:border-blue-500/30 hover:bg-blue-500/5 transition-all duration-200"
                    >
                      <div class="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center shrink-0">
                        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-5 h-5 text-blue-400">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M13.5 6H5.25A2.25 2.25 0 003 8.25v10.5A2.25 2.25 0 005.25 21h10.5A2.25 2.25 0 0018 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25" />
                        </svg>
                      </div>
                      <div class="text-left">
                        <span class="block text-sm font-medium text-white">Open ArgoCD</span>
                        <span class="block text-xs text-slate-400">Full dashboard in new tab</span>
                      </div>
                    </a>
                  </div>
                </div>

                <!-- Refresh Result -->
                <Transition name="slide">
                  <div v-if="infraModal.refreshResult" class="mb-6 p-4 rounded-xl border" :class="infraModal.refreshResult.failed > 0 ? 'bg-amber-500/10 border-amber-500/20' : 'bg-emerald-500/10 border-emerald-500/20'">
                    <div class="flex items-center gap-2 mb-2">
                      <svg v-if="infraModal.refreshResult.failed === 0" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-emerald-400">
                        <path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clip-rule="evenodd" />
                      </svg>
                      <svg v-else xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="w-4 h-4 text-amber-400">
                        <path fill-rule="evenodd" d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.17 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z" clip-rule="evenodd" />
                      </svg>
                      <span class="text-sm font-medium" :class="infraModal.refreshResult.failed === 0 ? 'text-emerald-300' : 'text-amber-300'">
                        {{ infraModal.refreshResult.refreshed }} app(s) refreshed
                        <span v-if="infraModal.refreshResult.failed > 0">, {{ infraModal.refreshResult.failed }} failed</span>
                      </span>
                    </div>
                    <div v-if="infraModal.refreshResult.apps && infraModal.refreshResult.apps.length > 0" class="flex flex-wrap gap-1.5 mt-2">
                      <span v-for="app in infraModal.refreshResult.apps" :key="app" class="inline-flex items-center px-2 py-0.5 rounded-md text-xs font-mono bg-white/5 text-slate-300 border border-white/5">
                        {{ app }}
                      </span>
                    </div>
                    <div v-if="infraModal.refreshResult.message" class="text-xs mt-2" :class="infraModal.refreshResult.failed > 0 ? 'text-amber-300' : 'text-slate-300'">
                      {{ infraModal.refreshResult.message }}
                    </div>
                  </div>
                </Transition>

                <div v-if="infraModal.argoInfo.connected === false" class="mb-4 p-3 rounded-lg bg-amber-500/10 border border-amber-500/20 text-amber-200 text-xs">
                  ArgoCD is not connected from the API. {{ infraModal.argoInfo.reason || 'Check argocd_server/argocd_username/argocd_password in Settings.' }}
                </div>

                <!-- ArgoCD Info -->
                <div>
                  <h4 class="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3">Cluster Overview</h4>
                  <div class="grid grid-cols-3 gap-3">
                    <div class="p-3 rounded-xl bg-slate-800/50 border border-white/5 text-center">
                      <div class="text-2xl font-bold text-white">{{ infraModal.argoInfo.totalApps ?? '--' }}</div>
                      <div class="text-xs text-slate-400 mt-1">Total Apps</div>
                    </div>
                    <div class="p-3 rounded-xl bg-slate-800/50 border border-white/5 text-center">
                      <div class="text-2xl font-bold text-emerald-400">{{ infraModal.argoInfo.healthyApps ?? '--' }}</div>
                      <div class="text-xs text-slate-400 mt-1">Healthy</div>
                    </div>
                    <div class="p-3 rounded-xl bg-slate-800/50 border border-white/5 text-center">
                      <div class="text-2xl font-bold" :class="(infraModal.argoInfo.syncedApps ?? 0) === (infraModal.argoInfo.totalApps ?? 0) ? 'text-emerald-400' : 'text-amber-400'">{{ infraModal.argoInfo.syncedApps ?? '--' }}</div>
                      <div class="text-xs text-slate-400 mt-1">Synced</div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- ========== VAULT TAB ========== -->
              <div v-if="infraModal.activeTab === 'vault'" class="space-y-5">
                <div class="flex items-center justify-between gap-3">
                  <div>
                    <h4 class="text-white font-medium">HashiCorp Vault</h4>
                    <p class="text-sm text-slate-400">Private by design (Tailscale-only). Browse secrets by environment.</p>
                  </div>
                  <div class="flex items-center gap-2">
                    <button
                      @click="loadVaultData()"
                      :disabled="infraModal.vault.loading"
                      class="px-3 py-1.5 rounded-lg text-xs border border-white/10 bg-white/5 hover:bg-white/10 text-slate-200 disabled:opacity-60"
                    >
                      {{ infraModal.vault.loading ? 'Refreshing...' : 'Refresh' }}
                    </button>
                    <a
                      v-if="infraModal.vault.status?.vault_ui_url"
                      :href="infraModal.vault.status.vault_ui_url + '/ui/vault/secrets'"
                      target="_blank"
                      class="px-3 py-1.5 rounded-lg text-xs border border-purple-500/20 bg-purple-500/10 hover:bg-purple-500/20 text-purple-300"
                    >
                      Open Vault UI
                    </a>
                  </div>
                </div>

                <div class="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <div class="p-3 rounded-xl bg-slate-800/50 border border-white/5 text-center">
                    <div class="text-lg font-bold" :class="infraModal.vault.status?.configured ? 'text-emerald-400' : 'text-red-400'">
                      {{ infraModal.vault.status?.configured ? 'YES' : 'NO' }}
                    </div>
                    <div class="text-xs text-slate-400 mt-1">Configured</div>
                  </div>
                  <div class="p-3 rounded-xl bg-slate-800/50 border border-white/5 text-center">
                    <div class="text-lg font-bold" :class="infraModal.vault.status?.reachable ? 'text-emerald-400' : 'text-amber-400'">
                      {{ infraModal.vault.status?.reachable ? 'UP' : 'DOWN' }}
                    </div>
                    <div class="text-xs text-slate-400 mt-1">Reachable</div>
                  </div>
                  <div class="p-3 rounded-xl bg-slate-800/50 border border-white/5 text-center">
                    <div class="text-lg font-bold" :class="infraModal.vault.status?.sealed === false ? 'text-emerald-400' : 'text-amber-400'">
                      {{ infraModal.vault.status?.sealed === false ? 'UNSEALED' : 'SEALED' }}
                    </div>
                    <div class="text-xs text-slate-400 mt-1">Seal State</div>
                  </div>
                  <div class="p-3 rounded-xl bg-slate-800/50 border border-white/5 text-center">
                    <div class="text-lg font-bold text-slate-200">
                      {{ infraModal.vault.status?.version || '--' }}
                    </div>
                    <div class="text-xs text-slate-400 mt-1">Version</div>
                  </div>
                </div>

                <div v-if="infraModal.vault.error" class="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-sm text-red-300">
                  {{ infraModal.vault.error }}
                </div>

                <div class="flex items-center gap-2">
                  <button
                    v-for="env in ['dev', 'staging', 'prod']"
                    :key="env"
                    @click="changeVaultEnv(env)"
                    class="px-3 py-1.5 rounded-lg text-xs border transition-all"
                    :class="infraModal.vault.selectedEnv === env
                      ? 'bg-purple-500/20 text-purple-300 border-purple-500/30'
                      : 'bg-slate-800/50 text-slate-400 border-white/10 hover:text-slate-200'"
                  >
                    {{ env }}
                  </button>
                </div>

                <div class="grid md:grid-cols-2 gap-4">
                  <div class="rounded-xl border border-white/10 bg-slate-900/40 p-3 max-h-64 overflow-y-auto">
                    <p class="text-xs text-slate-500 uppercase mb-2">Secrets in {{ infraModal.vault.selectedEnv }}</p>
                    <div v-if="!currentVaultSecrets.length" class="text-sm text-slate-500">No secrets found</div>
                    <button
                      v-for="appName in currentVaultSecrets"
                      :key="appName"
                      @click="selectVaultSecret(appName)"
                      class="w-full text-left px-2 py-1.5 rounded text-sm border mb-1 transition-all"
                      :class="infraModal.vault.selectedSecret === appName
                        ? 'bg-purple-500/20 border-purple-500/30 text-purple-200'
                        : 'bg-white/5 border-white/5 text-slate-300 hover:bg-white/10'"
                    >
                      {{ appName }}
                    </button>
                  </div>

                  <div class="rounded-xl border border-white/10 bg-slate-900/40 p-3 max-h-64 overflow-y-auto">
                    <div class="flex items-center justify-between mb-2">
                      <p class="text-xs text-slate-500 uppercase">Secret values</p>
                      <button
                        v-if="infraModal.vault.selectedSecret"
                        @click="toggleRevealVaultSecret()"
                        class="px-2 py-1 rounded text-[11px] border border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
                      >
                        {{ infraModal.vault.revealValues ? 'Mask values' : 'Reveal values' }}
                      </button>
                    </div>
                    <div v-if="infraModal.vault.secretLoading" class="text-sm text-slate-500">Loading secret...</div>
                    <div v-else-if="!infraModal.vault.secretDetail" class="text-sm text-slate-500">Select a secret from the left panel</div>
                    <div v-else class="space-y-2">
                      <div v-for="(value, key) in infraModal.vault.secretDetail.data" :key="key" class="p-2 rounded bg-black/30 border border-white/5">
                        <div class="text-[11px] text-slate-500">{{ key }}</div>
                        <code class="text-xs text-slate-200 break-all">{{ value }}</code>
                      </div>
                    </div>
                  </div>
                </div>
              </div>

            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { authState, logout } from '@/store/auth'
import { systemState, triggerGlobalSync, getSyncStatus, formatTimeAgo } from '@/store/system'
import { loadRuntimeConfig, getConfig } from '@/config'
import ScreenshotButton from '@/components/ScreenshotButton.vue'
import NodeFleet from '@/components/NodeFleet.vue'
import api from '@/services/api'

const router = useRouter()

// Settings/Infrastructure URLs - loaded from centralized config
const argoCdUrl = ref('')

// Infrastructure modal state
const infraModal = reactive({
  show: false,
  activeTab: 'overview',
  refreshing: false,
  refreshResult: null,
  tailscaleSuffix: '',
  domain: '',
  argoInfo: {
    totalApps: null,
    healthyApps: null,
    syncedApps: null,
    connected: null,
    reason: ''
  },
  vault: {
    loading: false,
    error: '',
    status: null,
    secretsByEnv: {
      dev: [],
      staging: [],
      prod: []
    },
    selectedEnv: 'dev',
    selectedSecret: '',
    revealValues: false,
    secretLoading: false,
    secretDetail: null
  }
})

const currentVaultSecrets = computed(() => {
  const env = infraModal.vault.selectedEnv
  return infraModal.vault.secretsByEnv?.[env] || []
})

const infraTabs = [
  { id: 'overview', label: 'Overview', icon: '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" /></svg>' },
  { id: 'argocd', label: 'ArgoCD', icon: '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M15.59 14.37a6 6 0 01-5.84 7.38v-4.8m5.84-2.58a14.98 14.98 0 006.16-12.12A14.98 14.98 0 009.631 8.41m5.96 5.96a14.926 14.926 0 01-5.841 2.58m-.119-8.54a6 6 0 00-7.381 5.84h4.8m2.581-5.84a14.927 14.927 0 00-2.58 5.84m2.699 2.7c-.103.021-.207.041-.311.06a15.09 15.09 0 01-2.448-2.448 14.9 14.9 0 01.06-.312m-2.24 2.39a4.493 4.493 0 00-1.757 4.306 4.493 4.493 0 004.306-1.758M16.5 9a1.5 1.5 0 11-3 0 1.5 1.5 0 013 0z" /></svg>' },
  { id: 'vault', label: 'Vault', icon: '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" class="w-4 h-4"><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 10-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 002.25-2.25v-6.75a2.25 2.25 0 00-2.25-2.25H6.75a2.25 2.25 0 00-2.25 2.25v6.75a2.25 2.25 0 002.25 2.25z" /></svg>' }
]

// Fetch ArgoCD overview info
const loadArgoInfo = async () => {
  try {
    const response = await api.get('/apps/argocd/all')
    const payload = response.data || {}
    const apps = Array.isArray(payload) ? payload : (payload.apps || [])
    infraModal.argoInfo.totalApps = payload.count ?? apps.length
    infraModal.argoInfo.healthyApps = payload.stats?.healthy ?? apps.filter(a => a.isHealthy).length
    infraModal.argoInfo.syncedApps = payload.stats?.synced ?? apps.filter(a => a.isSynced).length
    infraModal.argoInfo.connected = payload.connected ?? true
    infraModal.argoInfo.reason = payload.connection_reason || ''
  } catch {
    infraModal.argoInfo = { totalApps: null, healthyApps: null, syncedApps: null, connected: null, reason: '' }
  }
}

// Handle ArgoCD force refresh
const handleArgoRefresh = async () => {
  infraModal.refreshing = true
  infraModal.refreshResult = null
  try {
    const response = await api.post('/system/argocd/refresh')
    infraModal.refreshResult = response.data
    loadArgoInfo()
  } catch (error) {
    infraModal.refreshResult = { refreshed: 0, failed: 1, errors: [{ app: 'all', error: error.response?.data?.detail || error.message }] }
  } finally {
    infraModal.refreshing = false
  }
}

const loadVaultStatus = async () => {
  const { data } = await api.get('/system/vault/status')
  infraModal.vault.status = data
}

const loadVaultSecrets = async () => {
  const { data } = await api.get('/system/vault/secrets')
  infraModal.vault.secretsByEnv = {
    dev: data?.envs?.dev || [],
    staging: data?.envs?.staging || [],
    prod: data?.envs?.prod || []
  }
}

const loadVaultData = async () => {
  infraModal.vault.loading = true
  infraModal.vault.error = ''
  try {
    await Promise.all([loadVaultStatus(), loadVaultSecrets()])
  } catch (error) {
    infraModal.vault.error = error.response?.data?.detail || error.message || 'Failed to load Vault data'
  } finally {
    infraModal.vault.loading = false
  }
}

const changeVaultEnv = (env) => {
  infraModal.vault.selectedEnv = env
  infraModal.vault.selectedSecret = ''
  infraModal.vault.secretDetail = null
  infraModal.vault.revealValues = false
}

const selectVaultSecret = async (appName) => {
  infraModal.vault.selectedSecret = appName
  infraModal.vault.secretLoading = true
  infraModal.vault.error = ''
  try {
    const { data } = await api.get(
      `/system/vault/secrets/${infraModal.vault.selectedEnv}/${appName}`,
      { params: { reveal: infraModal.vault.revealValues } }
    )
    infraModal.vault.secretDetail = data
  } catch (error) {
    infraModal.vault.error = error.response?.data?.detail || error.message || 'Failed to load secret detail'
    infraModal.vault.secretDetail = null
  } finally {
    infraModal.vault.secretLoading = false
  }
}

const toggleRevealVaultSecret = async () => {
  if (!infraModal.vault.selectedSecret) return
  infraModal.vault.revealValues = !infraModal.vault.revealValues
  await selectVaultSecret(infraModal.vault.selectedSecret)
}

// Load infra data when modal opens
watch(() => infraModal.show, (show) => {
  if (show) {
    infraModal.refreshResult = null
    loadArgoInfo()
    loadVaultStatus()
    infraModal.tailscaleSuffix = getConfig('tailscaleSuffix')
    infraModal.domain = getConfig('domain')
  }
})

watch(() => infraModal.activeTab, (tab) => {
  if (tab === 'vault' && infraModal.show) {
    loadVaultData()
  }
})

// Load public settings via centralized config module
const loadPublicSettings = async () => {
  await loadRuntimeConfig()
  argoCdUrl.value = getConfig('argocdUrl')
  infraModal.tailscaleSuffix = getConfig('tailscaleSuffix')
  infraModal.domain = getConfig('domain')
}

// Toast state
const showSyncToast = ref(false)
const syncToastMessage = ref('')
const syncToastType = ref('success')

// Handle logout
const handleLogout = () => {
  logout()
  router.push('/login')
}

// Handle global sync
const handleGlobalSync = async () => {
  try {
    await triggerGlobalSync()
  } catch (error) {
    showToast('Failed to start sync', 'error')
  }
}

// Show toast notification
const showToast = (message, type = 'success') => {
  syncToastMessage.value = message
  syncToastType.value = type
  showSyncToast.value = true
  setTimeout(() => {
    showSyncToast.value = false
  }, 4000)
}

// Listen for sync complete
const onSyncComplete = (event) => {
  const result = event.detail
  if (result) {
    const errors = result.errors?.length || 0
    if (errors > 0) {
      showToast(`Sync completed with ${errors} error(s)`, 'warning')
    } else {
      showToast(`Synced ${result.apps_updated || 0} apps successfully`, 'success')
    }
  }
}

// ── Versión del engine y aviso de actualización ──────────────────────────
// La versión sale de la procedencia real de la célula (antes era un texto fijo
// que no correspondía a nada). Cada consulta pregunta a GitHub, así que se
// revisa al entrar y cada 10 minutos, no en cada navegación.
const ENGINE_CHECK_MS = 10 * 60 * 1000
const engine = reactive({ version: '…', updateAvailable: false, pendingLabel: '' })
let engineTimer = null

const applyEngineStatus = (data) => {
  engine.version = data.current?.version || 'unknown'
  engine.updateAvailable = !!data.update_available
  const pending = data.upstream?.ahead_by
  engine.pendingLabel = data.update_available
    ? (pending ? `${pending} commit(s) sin aplicar` : `Disponible: ${data.latest?.version}`)
    : ''
}

const checkEngine = async () => {
  try {
    const { data } = await api.get('/core/updates')
    applyEngineStatus(data)
  } catch (e) {
    // Sin GitHub o sin permisos la consola sigue funcionando; solo no avisa.
  }
}

const startEngineChecks = () => {
  checkEngine()
  clearInterval(engineTimer)
  engineTimer = setInterval(checkEngine, ENGINE_CHECK_MS)
}

watch(() => authState.isAuthenticated, (loggedIn) => {
  if (loggedIn) startEngineChecks()
  else clearInterval(engineTimer)
})

// Updates.vue comparte el resultado cuando revisa a mano: la barra se actualiza
// sin volver a consultar GitHub.
const onEngineChecked = (event) => { if (event.detail) applyEngineStatus(event.detail) }

onMounted(() => {
  // Load public settings (ArgoCD URL, Tailscale info, etc.)
  loadPublicSettings()

  // Only call authenticated endpoints if user is logged in
  if (authState.isAuthenticated) {
    getSyncStatus().catch(() => {})
    startEngineChecks()
  }

  // Listen for sync complete events
  window.addEventListener('kaanbal:sync-complete', onSyncComplete)
  window.addEventListener('kaanbal:engine-checked', onEngineChecked)
})

onUnmounted(() => {
  window.removeEventListener('kaanbal:sync-complete', onSyncComplete)
  window.removeEventListener('kaanbal:engine-checked', onEngineChecked)
  clearInterval(engineTimer)
})
</script>

<style>
/* Toast animation */
.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}

/* Modal animation */
.modal-enter-active,
.modal-leave-active {
  transition: all 0.3s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-from .relative,
.modal-leave-to .relative {
  transform: scale(0.95) translateY(10px);
}

/* Slide animation for results */
.slide-enter-active,
.slide-leave-active {
  transition: all 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  opacity: 0;
  transform: translateY(-8px);
}
</style>
