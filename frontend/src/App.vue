<template>
  <div class="app-container">
    <nav class="nav-sidebar">
      <div class="nav-brand">
        <span class="logo">🐞</span>
        <span class="name">Reverie AI</span>
      </div>
      <div class="nav-links">
        <router-link to="/" class="nav-item">Projects</router-link>
        <router-link to="/settings" class="nav-item">Settings</router-link>
      </div>
    </nav>
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<style>
:root {
  --bg-primary: #121212;
  --bg-secondary: #1a1a1a;
  --accent: #646cff;
  --text-primary: #ffffff;
  --text-secondary: #a0a0a0;
  --border: #333;
}

* { box-sizing: border-box; }
body {
  margin: 0;
  background-color: var(--bg-primary);
  color: var(--text-primary);
  font-family: 'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif;
  -webkit-font-smoothing: antialiased;
}

.app-container {
  display: flex;
  min-height: 100vh;
}

.nav-sidebar {
  width: 240px;
  background: var(--bg-secondary);
  border-right: 1px solid var(--border);
  padding: 2rem 1.5rem;
  display: flex;
  flex-direction: column;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 3rem;
}
.nav-brand .logo { font-size: 1.5rem; }
.nav-brand .name { font-weight: 700; font-size: 1.25rem; letter-spacing: -0.02em; }

.nav-links { display: flex; flex-direction: column; gap: 0.5rem; }
.nav-item {
  padding: 0.75rem 1rem;
  border-radius: 8px;
  color: var(--text-secondary);
  text-decoration: none;
  font-weight: 500;
  transition: all 0.2s;
}
.nav-item:hover { background: #252525; color: white; }
.router-link-active { background: #252525; color: var(--accent); }

.main-content {
  flex: 1;
  padding: 2rem 4rem;
  max-width: 1200px;
}

.header { margin-bottom: 2.5rem; }
.header h1 { margin: 0; font-size: 2rem; font-weight: 800; letter-spacing: -0.02em; }

.btn-primary {
  background: var(--accent);
  color: white;
  border: none;
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  transition: opacity 0.2s;
}
.btn-primary:hover:not(:disabled) { opacity: 0.9; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-secondary {
  background: transparent;
  color: var(--text-primary);
  border: 1px solid var(--border);
  padding: 0.75rem 1.5rem;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  width: 100%;
  transition: background 0.2s;
}
.btn-secondary:hover:not(:disabled) { background: #252525; border-color: #666; }
.btn-secondary:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-text {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 0;
  margin-bottom: 0.5rem;
  font-size: 0.9rem;
}
.btn-text:hover { color: white; }

.card {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 12px;
}
.clickable { cursor: pointer; }

/* Markdown Styles */
.markdown-body :deep(h1), .markdown-body h1 { font-size: 1.75rem; margin-top: 0; margin-bottom: 1.5rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; }
.markdown-body :deep(h2), .markdown-body h2 { font-size: 1.5rem; margin-top: 2rem; margin-bottom: 1rem; }
.markdown-body :deep(h3), .markdown-body h3 { font-size: 1.25rem; margin-top: 1.5rem; margin-bottom: 1rem; color: var(--accent); }
.markdown-body :deep(p), .markdown-body p { margin-bottom: 1rem; line-height: 1.7; }
.markdown-body :deep(ul), .markdown-body ul, .markdown-body :deep(ol), .markdown-body ol { margin-bottom: 1rem; padding-left: 1.5rem; }
.markdown-body :deep(li), .markdown-body li { margin-bottom: 0.5rem; }
.markdown-body :deep(code), .markdown-body code { background: #2a2a2a; padding: 0.2rem 0.4rem; border-radius: 4px; font-family: monospace; font-size: 0.9em; }
.markdown-body :deep(pre), .markdown-body pre { background: #000; padding: 1rem; border-radius: 8px; overflow-x: auto; margin-bottom: 1.5rem; border: 1px solid #333; }
.markdown-body :deep(pre code), .markdown-body pre code { background: none; padding: 0; }
.markdown-body :deep(blockquote), .markdown-body blockquote { border-left: 4px solid var(--accent); margin: 0; padding-left: 1rem; color: #888; font-style: italic; }
</style>
