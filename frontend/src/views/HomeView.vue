<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const projects = ref([])
const router = useRouter()

async function fetchProjects() {
  const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
  const res = await fetch(`${baseUrl}/api/projects`)
  projects.value = await res.json()
}

onMounted(fetchProjects)
</script>

<template>
  <div class="home">
    <header class="header">
      <h1>Projects</h1>
    </header>

    <div class="project-grid">
      <div v-for="p in projects" :key="p.tag" class="card clickable" @click="router.push('/project/' + p.tag)">
        <div class="card-header">
          <h2>{{ p.name }}</h2>
          <span class="badge">{{ p.tag }}</span>
        </div>
        <p class="path">{{ p.root_path }}</p>
        <div class="card-footer">
          <span>{{ p.min_severity }} severity</span>
          <span>{{ p.max_iterations }} iterations</span>
        </div>
      </div>
      
      <div v-if="projects.length === 0" class="empty">
        No projects found. Initialize a project via CLI to get started.
      </div>
    </div>
  </div>
</template>

<style scoped>
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.5rem;
}
.card {
  padding: 1.5rem;
  background: #1e1e1e;
  border-radius: 12px;
  border: 1px solid #333;
  transition: transform 0.2s, border-color 0.2s;
}
.card:hover {
  transform: translateY(-4px);
  border-color: #646cff;
}
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}
.card-header h2 {
  margin: 0;
  font-size: 1.25rem;
}
.badge {
  background: #333;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
  font-size: 0.75rem;
  font-family: monospace;
}
.path {
  font-size: 0.875rem;
  color: #888;
  word-break: break-all;
  margin-bottom: 1rem;
}
.card-footer {
  display: flex;
  justify-content: space-between;
  font-size: 0.75rem;
  color: #666;
}
.empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 4rem;
  color: #666;
  border: 2px dashed #333;
  border-radius: 12px;
}
</style>
