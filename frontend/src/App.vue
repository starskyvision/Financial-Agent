<template>
  <div class="app-layout">
    <nav class="sidebar">
      <div class="logo">📊 金融Agent</div>
      <router-link to="/" class="nav-item">💬 对话</router-link>
      <router-link to="/rag" class="nav-item">📚 知识库</router-link>
      <router-link to="/dashboard" class="nav-item">📈 仪表盘</router-link>
    </nav>
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
</script>

<style scoped>
.app-layout { display: flex; min-height: 100vh; }
.sidebar { width: 200px; background: #1a1a2e; color: #fff; padding: 20px 0; display: flex; flex-direction: column; }
.logo { font-size: 16px; font-weight: bold; padding: 0 20px 24px; border-bottom: 1px solid #2a2a4e; margin-bottom: 12px; }
.nav-item { color: #a0a0c0; text-decoration: none; padding: 10px 20px; font-size: 14px; transition: 0.2s; }
.nav-item:hover, .router-link-active { color: #fff; background: #2a2a4e; }
.main-content { flex: 1; padding: 24px; overflow-y: auto; }
</style>
