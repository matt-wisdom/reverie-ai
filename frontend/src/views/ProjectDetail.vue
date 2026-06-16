<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt()
const route = useRoute()
const router = useRouter()
const tag = route.params.tag

const project = ref(null)
const summary = ref(null)
const reports = ref([])
const isRunning = ref(false)
const isIngesting = ref(false)
const reviewMode = ref('full')
const customPrompt = ref('')

const renderedSummary = computed(() => {
  return summary.value ? md.render(summary.value) : ''
})

async function fetchData() {
  const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
  const pRes = await fetch(`${baseUrl}/api/projects/${tag}`)
  project.value = await pRes.json()

  const sRes = await fetch(`${baseUrl}/api/projects/${tag}/summary`)
  const sData = await sRes.json()
  summary.value = sData.summary

  const rRes = await fetch(`${baseUrl}/api/projects/${tag}/reports`)
  reports.value = await rRes.json()
}

async function rebuildKG() {
  if (!confirm('This will re-index the entire codebase. Continue?')) return
  isIngesting.value = true
  const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
  try {
    const res = await fetch(`${baseUrl}/api/projects/${tag}/ingest?force=true`, {
      method: 'POST'
    })
    if (res.ok) {
      alert('Ingestion started! The graph will be updated in the background.')
    }
  } catch (e) {
    alert('Ingestion failed: ' + e.message)
  } finally {
    isIngesting.value = false
  }
}

async function runReview() {
  isRunning.value = true
  const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
  try {
    const res = await fetch(`${baseUrl}/api/projects/${tag}/review?mode=${reviewMode.value}&prompt=${encodeURIComponent(customPrompt.value)}`, {
      method: 'POST'
    })
    if (res.ok) {
      await fetchData() // Refresh history
      alert('Review completed successfully!')
    }
  } catch (e) {
    alert('Review failed: ' + e.message)
  } finally {
    isRunning.value = false
  }
}

onMounted(fetchData)
</script>

<template>
  <div v-if="project" class="project-detail">
    <header class="header">
      <button class="btn-text" @click="router.push('/')">← Back</button>
      <h1>{{ project.name }}</h1>
    </header>

    <div class="layout">
      <aside class="sidebar">
        <section>
          <h3>Configuration</h3>
          <div class="info-list">
            <div class="item"><label>Path:</label> <span>{{ project.root_path }}</span></div>
            <div class="item"><label>Min Severity:</label> <span>{{ project.min_severity }}</span></div>
            <div class="item"><label>Recursion Depth:</label> <span>{{ project.max_recursion_depth }}</span></div>
          </div>
          <button class="btn-secondary" @click="rebuildKG" :disabled="isIngesting" style="margin-top: 1rem;">
            {{ isIngesting ? 'Rebuilding...' : 'Rebuild Knowledge Graph' }}
          </button>
        </section>

        <section class="review-box">
          <h3>Run New Review</h3>
          <div class="form-group">
            <label>Mode</label>
            <select v-model="reviewMode" :disabled="isRunning">
              <option value="full">Full Review</option>
              <option value="bug_detect">Bug Detection</option>
              <option value="security">Security Audit</option>
              <option value="smell">Code Smells</option>
              <option value="bug_detect,security">Bugs + Security</option>
            </select>
          </div>
          <div class="form-group">
            <label>Custom Instructions</label>
            <textarea v-model="customPrompt" placeholder="e.g. Focus on memory safety..." :disabled="isRunning"></textarea>
          </div>
          <button class="btn-primary" @click="runReview" :disabled="isRunning">
            {{ isRunning ? 'Reviewing...' : 'Start Review' }}
          </button>
        </section>
      </aside>

      <main class="content">
        <section v-if="summary" class="summary-section">
          <h3>Architectural Summary</h3>
          <div class="summary-text markdown-body" v-html="renderedSummary"></div>
        </section>

        <section class="history">
          <h3>Report History</h3>
          <div class="report-list">
            <div v-for="r in reports" :key="r.id" class="report-item" @click="router.push(`/project/${tag}/report/${r.id}`)">
              <span class="name">{{ r.name }}</span>
              <span class="date">{{ new Date(r.timestamp).toLocaleString() }}</span>
            </div>
            <div v-if="reports.length === 0" class="empty-mini">No reports yet.</div>
          </div>
        </section>
      </main>
    </div>
  </div>
</template>

<style scoped>
.layout {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 2rem;
}
section { margin-bottom: 2rem; }
h3 { font-size: 0.9rem; text-transform: uppercase; color: #666; letter-spacing: 0.05em; margin-bottom: 1rem; }

.info-list .item { display: flex; flex-direction: column; margin-bottom: 0.75rem; }
.info-list label { font-size: 0.75rem; color: #666; }
.info-list span { font-size: 0.875rem; color: #eee; word-break: break-all; }

.review-box { padding: 1.25rem; background: #1a1a1a; border-radius: 8px; border: 1px solid #333; }
.form-group { margin-bottom: 1rem; }
.form-group label { display: block; font-size: 0.75rem; margin-bottom: 0.5rem; }
textarea { width: 100%; height: 80px; background: #2a2a2a; border: 1px solid #444; color: white; padding: 0.5rem; border-radius: 4px; resize: none; font-family: inherit; }
select { width: 100%; padding: 0.5rem; background: #2a2a2a; border: 1px solid #444; color: white; border-radius: 4px; }

.summary-text { padding: 1.5rem; background: #1e1e1e; border-radius: 8px; line-height: 1.6; white-space: pre-wrap; font-size: 0.95rem; }

.report-list { border: 1px solid #333; border-radius: 8px; overflow: hidden; }
.report-item { padding: 1rem; border-bottom: 1px solid #333; display: flex; justify-content: space-between; cursor: pointer; transition: background 0.2s; }
.report-item:last-child { border-bottom: none; }
.report-item:hover { background: #252525; }
.report-item .name { font-weight: 500; }
.report-item .date { font-size: 0.8rem; color: #666; }
</style>
