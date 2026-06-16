<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarkdownIt from 'markdown-it'

const md = new MarkdownIt()
const route = useRoute()
const router = useRouter()
const { tag, id } = route.params
const report = ref(null)

const renderedMarkdown = computed(() => {
  return report.value ? md.render(report.value.content) : ''
})

function downloadFile(content, filename, contentType) {
  const blob = new Blob([content], { type: contentType })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function downloadMD() {
  downloadFile(report.value.content, `reverie_report_${id}.md`, 'text/markdown')
}

function downloadHTML() {
  const htmlContent = `
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="UTF-8">
      <title>Reverie Report - ${id}</title>
      <style>
        body { font-family: sans-serif; padding: 2rem; line-height: 1.6; max-width: 800px; margin: 0 auto; color: #333; }
        pre { background: #f4f4f4; padding: 1rem; border-radius: 4px; overflow-x: auto; }
        code { font-family: monospace; background: #eee; padding: 0.2rem 0.4rem; border-radius: 3px; }
        h1, h2, h3 { color: #222; }
      </style>
    </head>
    <body>
      ${renderedMarkdown.value}
    </body>
    </html>
  `
  downloadFile(htmlContent, `reverie_report_${id}.html`, 'text/html')
}

async function downloadSARIF() {
  const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
  const res = await fetch(`${baseUrl}/api/projects/${tag}/reports/${id}/sarif`)
  const data = await res.json()
  downloadFile(JSON.stringify(data, null, 2), `reverie_results_${id}.sarif`, 'application/json')
}

async function fetchReport() {
  const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
  const res = await fetch(`${baseUrl}/api/projects/${tag}/reports/${id}`)
  report.value = await res.json()
}

onMounted(fetchReport)
</script>

<template>
  <div class="report-view">
    <header class="header">
      <div class="header-top">
        <button class="btn-text" @click="router.push(`/project/${tag}`)">← Back to Project</button>
        <div class="actions">
          <button class="btn-secondary btn-sm" @click="downloadSARIF">Download SARIF</button>
          <button class="btn-secondary btn-sm" @click="downloadMD">Download MD</button>
          <button class="btn-secondary btn-sm" @click="downloadHTML">Download HTML</button>
        </div>
      </div>
      <h1>Report: {{ id }}</h1>
    </header>

    <main v-if="report" class="markdown-body" v-html="renderedMarkdown"></main>
  </div>
</template>

<style scoped>
.header-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}
.actions {
  display: flex;
  gap: 0.75rem;
}
.btn-sm {
  padding: 0.4rem 0.8rem;
  font-size: 0.8rem;
  width: auto;
}
.markdown-body {
  background: #1e1e1e;
  padding: 2.5rem;
  border-radius: 12px;
  border: 1px solid #333;
  line-height: 1.6;
  color: #eee;
}
</style>
