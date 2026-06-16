import { defineStore } from 'pinia'

export const useSettingsStore = defineStore('settings', {
  state: () => ({
    settings: {
      LLM_MODEL: 'gemini/gemini-1.5-flash',
      LLM_API_KEY: '',
      LLM_BASE_URL: '',
      EMBEDDING_MODEL: 'gemini/gemini-embedding-001',
      EMBEDDING_API_KEY: '',
      TAVILY_API_KEY: '',
      LLM_RPM: 15
    }
  }),
  actions: {
    async fetchSettings() {
      try {
        const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
        const res = await fetch(`${baseUrl}/api/settings`)
        const data = await res.json()
        this.settings = data
      } catch (e) {
        console.error('Failed to fetch settings', e)
      }
    },
    async saveSettings(newSettings) {
      try {
        const baseUrl = import.meta.env.DEV ? 'http://localhost:8000' : ''
        await fetch(`${baseUrl}/api/settings`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(newSettings)
        })
        this.settings = newSettings
      } catch (e) {
        console.error('Failed to save settings', e)
      }
    }
  }
})
