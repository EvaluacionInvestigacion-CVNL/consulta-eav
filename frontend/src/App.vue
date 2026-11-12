<script setup>
import { onMounted } from 'vue'
import { init, state, toggleSidebar } from './store.js'
import Sidebar from './components/Sidebar.vue'
import TopBar from './components/TopBar.vue'
import ResultsPanel from './components/ResultsPanel.vue'
import ChatPanel from './components/ChatPanel.vue'

onMounted(init)
</script>

<template>
  <div class="flex h-dvh overflow-hidden bg-cream">
    <Sidebar />
    <!-- En el teléfono el panel va encima: tocar fuera lo cierra. -->
    <div
      v-if="state.sidebarOpen"
      class="md:hidden fixed inset-0 z-30 bg-black/30"
      @click="toggleSidebar"
    />
    <main class="flex-1 flex flex-col overflow-hidden">
      <TopBar />
      <ChatPanel v-if="state.queryMode === 'ai'" />
      <ResultsPanel v-else />
    </main>
  </div>
</template>
