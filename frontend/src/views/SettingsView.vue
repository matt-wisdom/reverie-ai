<script setup>
import { onMounted } from 'vue'
import { useSettingsStore } from '../store/settings'

const store = useSettingsStore()

onMounted(store.fetchSettings)

async function save() {
  await store.saveSettings(store.settings)
  alert('Settings saved successfully!')
}
</script>

<template>
  <div class="settings">
    <header class="header">
      <h1>Global Settings</h1>
    </header>

    <div class="settings-form card">
      <section>
        <h3>Chat Model (LiteLLM)</h3>
        <p class="section-desc">Supports 100+ providers. Format: <code>provider/model</code> (e.g. <code>openai/gpt-4o</code>)</p>
        
        <div class="form-group">
          <label>Model Name</label>
          <input v-model="store.settings.LLM_MODEL" placeholder="gemini/gemini-1.5-flash">
        </div>
        
        <div class="form-group">
          <label>API Key</label>
          <input v-model="store.settings.LLM_API_KEY" type="password" placeholder="Your API Key">
        </div>

        <div class="form-group">
          <label>Base URL (Optional)</label>
          <input v-model="store.settings.LLM_BASE_URL" placeholder="https://api.openai.com/v1">
        </div>
      </section>

      <section>
        <h3>Embedding Model</h3>
        <div class="form-group">
          <label>Model Name</label>
          <input v-model="store.settings.EMBEDDING_MODEL" placeholder="gemini/gemini-embedding-001">
        </div>
        
        <div class="form-group">
          <label>Embedding API Key (Optional)</label>
          <input v-model="store.settings.EMBEDDING_API_KEY" type="password" placeholder="Defaults to Chat API Key if empty">
        </div>
      </section>

      <section>
        <h3>Performance & Tools</h3>
        <div class="form-group">
          <label>Rate Limit (Requests per minute)</label>
          <input v-model.number="store.settings.LLM_RPM" type="number" min="1" max="1000">
        </div>
        
        <div class="form-group">
          <label>Tavily API Key (Search)</label>
          <input v-model="store.settings.TAVILY_API_KEY" type="password" placeholder="tvly-...">
        </div>
      </section>

      <button class="btn-primary" @click="save">Save All Settings</button>
      <p class="hint">Settings are saved to <code>~/.reverie/.env</code></p>
    </div>

    <div class="tip-box">
      <h4>Need Help?</h4>
      <p>Reverie uses <strong>LiteLLM</strong>. You can use any provider by prefixing the model name:</p>
      <ul>
        <li><code>openai/gpt-4o</code></li>
        <li><code>anthropic/claude-3-5-sonnet-20240620</code></li>
        <li><code>groq/llama3-70b-8192</code></li>
        <li><code>ollama/llama3</code></li>
      </ul>
    </div>
  </div>
</template>

<style scoped>
.settings-form { max-width: 600px; padding: 2rem; }
section { margin-bottom: 2rem; border-bottom: 1px solid #333; padding-bottom: 2rem; }
section:last-of-type { border-bottom: none; }
h3 { margin-bottom: 0.5rem; font-size: 1.1rem; }
.section-desc { font-size: 0.85rem; color: #666; margin-bottom: 1.5rem; }
.form-group { margin-bottom: 1.25rem; }
label { display: block; font-size: 0.8rem; color: #888; margin-bottom: 0.5rem; }
input { width: 100%; padding: 0.75rem; background: #2a2a2a; border: 1px solid #444; color: white; border-radius: 6px; }
.hint { font-size: 0.8rem; color: #666; margin-top: 1.5rem; text-align: center; }

.tip-box { margin-top: 2rem; padding: 1.5rem; background: #1a1a1a; border-left: 4px solid #646cff; border-radius: 4px; max-width: 600px; }
.tip-box h4 { margin: 0 0 0.5rem 0; color: #646cff; }
.tip-box ul { font-size: 0.85rem; color: #888; margin-top: 0.5rem; padding-left: 1.2rem; }
.tip-box li { margin-bottom: 0.25rem; }
code { background: #000; padding: 0.1rem 0.3rem; border-radius: 3px; font-family: monospace; }
</style>
