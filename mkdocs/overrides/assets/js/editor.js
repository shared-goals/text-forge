/**
 * Live Markdown Editor (text-forge)
 * 
 * KISS implementation:
 * - Fetches raw markdown from GitHub
 * - Uses Pyodide + pymdown-extensions for rendering
 * - Debounced live preview
 * - Download edited file
 */

(function () {
  'use strict';

  // Exit early if editor is not configured
  if (!window.__MD_EDITOR__) return;

  const config = window.__MD_EDITOR__;
  
  // Translations (loaded separately)
  let translations = {};
  
  /**
   * Get translated string by key
   */
  function t(key) {
    return translations[key] || key;
  }
  
  // DOM elements (lazy init)
  let els = null;
  
  // Pyodide instance (loaded on first open)
  let pyodide = null;
  let pyodideReady = false;
  let pyodideLoading = false;

  // Debounce timer
  let renderTimer = null;
  const RENDER_DELAY = 500; // ms

  /**
   * Initialize DOM element references
   */
  function initElements() {
    if (els) return;
    els = {
      editor: document.getElementById('md-editor'),
      toggle: document.getElementById('md-editor-toggle'),
      close: document.getElementById('md-editor-close'),
      download: document.getElementById('md-editor-download'),
      source: document.getElementById('md-editor-source'),
      preview: document.getElementById('md-editor-preview'),
      status: document.getElementById('md-editor-status')
    };
  }

  /**
   * Set status message
   */
  function setStatus(msg) {
    if (els?.status) {
      els.status.textContent = msg;
    }
  }

  /**
   * Load Pyodide and pymdown-extensions
   */
  async function loadPyodide() {
    if (pyodideReady) return;
    if (pyodideLoading) {
      // Wait for existing load
      while (pyodideLoading) {
        await new Promise(r => setTimeout(r, 100));
      }
      return;
    }

    pyodideLoading = true;
    setStatus(t('editor_status_loading_pyodide'));

    try {
      // Load Pyodide from CDN
      if (!window.loadPyodide) {
        await loadScript('https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js');
      }

      pyodide = await window.loadPyodide();
      setStatus(t('editor_status_loading_pyodide'));

      // Install required packages
      await pyodide.loadPackage('micropip');
      const micropip = pyodide.pyimport('micropip');
      await micropip.install(['markdown', 'pymdown-extensions', 'pyyaml']);

      // Fetch and parse mkdocs.yml for markdown extensions config
      const mkdocsConfig = await fetchMkdocsConfig();
      const pythonConfig = generatePythonMarkdownConfig(mkdocsConfig);

      // Initialize Python markdown renderer with dynamic config
      await pyodide.runPythonAsync(`
import markdown
from pymdownx import blocks

${pythonConfig}

def render_markdown(text):
    """Render markdown to HTML, reset state for each render"""
    md.reset()
    return md.convert(text)
`);

      pyodideReady = true;
      setStatus(t('editor_status_ready'));
    } catch (err) {
      console.error('Pyodide load error:', err);
      setStatus(t('editor_status_load_failed') + ': ' + err.message);
      throw err;
    } finally {
      pyodideLoading = false;
    }
  }

  /**
   * Load a script dynamically
   */
  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = src;
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  /**
   * Fetch markdown source from GitHub
   */
  async function fetchSource() {
    // Use embedded content if available (local dev mode)
    if (config.sourceContent) {
      setStatus(t('editor_status_ready'));
      return config.sourceContent;
    }

    // Otherwise fetch from GitHub (production)
    setStatus(t('editor_loading'));
    try {
      const resp = await fetch(config.sourceUrl);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const text = await resp.text();
      setStatus(t('editor_status_ready'));
      return text;
    } catch (err) {
      console.error('Fetch error:', err);
      setStatus(t('editor_status_load_failed') + ': ' + err.message);
      throw err;
    }
  }

  /**
   * Fetch mkdocs.yml configuration
   */
  async function fetchMkdocsConfig() {
    // Try local first (dev mode)
    let url = '/mkdocs.yml';
    let resp = await fetch(url);
    
    // If not found locally, try GitHub (production)
    if (!resp.ok && config.repoUrl) {
      const [owner, repo] = config.repoUrl.replace('https://github.com/', '').split('/');
      url = `https://raw.githubusercontent.com/${owner}/${repo}/master/mkdocs.yml`;
      resp = await fetch(url);
    }
    
    if (!resp.ok) {
      throw new Error(t('editor_error_mkdocs_fetch').replace('{status}', resp.status));
    }
    
    return await resp.text();
  }

  /**
   * Generate Python markdown configuration from mkdocs.yml
   */
  function generatePythonMarkdownConfig(mkdocsYaml) {
    if (!mkdocsYaml) {
      throw new Error(t('editor_error_mkdocs_not_found'));
    }

    // Extract markdown_extensions section from mkdocs.yml
    // Find the markdown_extensions key and extract all indented content under it
    const extensionsMatch = mkdocsYaml.match(/^markdown_extensions:\s*$([\s\S]*?)^(?=\S)/m);
    
    if (!extensionsMatch) {
      throw new Error(t('editor_error_config_section'));
    }

    const configSection = 'markdown_extensions:\n' + extensionsMatch[1];
    
    // Parse YAML using Pyodide (already loaded)
    const parsed = pyodide.runPython(`
import yaml
import json
config_text = ${JSON.stringify(configSection)}
parsed = yaml.safe_load(config_text)
json.dumps(parsed)
`);
    
    const config = JSON.parse(parsed);
    const extensions = config.markdown_extensions || [];
    
    if (extensions.length === 0) {
      throw new Error(t('editor_error_no_extensions'));
    }
    
    // Build extensions list and configs
    const extList = [];
    const extConfigs = {};
    
    extensions.forEach(ext => {
      if (typeof ext === 'string') {
        extList.push(`'${ext}'`);
      } else if (typeof ext === 'object') {
        const key = Object.keys(ext)[0];
        extList.push(`'${key}'`);
        extConfigs[key] = ext[key];
      }
    });
    
    // Convert configs to Python dict format
    const configPython = Object.keys(extConfigs).length > 0
      ? `, extension_configs=${JSON.stringify(extConfigs).replace(/"/g, "'").replace(/'/g, '"').replace(/true/g, 'True').replace(/false/g, 'False')}`
      : '';
    
    return `md = markdown.Markdown(extensions=[${extList.join(', ')}]${configPython})`;
  }

  /**
   * Render markdown to preview pane
   */
  async function renderPreview() {
    if (!pyodideReady || !els?.source || !els?.preview) return;

    const source = els.source.value;
    if (!source.trim()) {
      els.preview.innerHTML = `<p><em>${t('editor_empty_document')}</em></p>`;
      return;
    }

    try {
      setStatus(t('editor_status_ready_to_render'));
      const html = await pyodide.runPythonAsync(`render_markdown(${JSON.stringify(source)})`);
      els.preview.innerHTML = html;
      setStatus(t('editor_status_ready'));
    } catch (err) {
      console.error('Render error:', err);
      els.preview.innerHTML = `<pre style="color:red;">${t('editor_status_rendering_error')}:\n${err.message}</pre>`;
      setStatus(t('editor_status_rendering_error'));
    }
  }

  /**
   * Debounced render
   */
  function scheduleRender() {
    clearTimeout(renderTimer);
    renderTimer = setTimeout(renderPreview, RENDER_DELAY);
  }

  /**
   * Download current source as .md file
   */
  function downloadSource() {
    if (!els?.source) return;
    
    const blob = new Blob([els.source.value], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = config.fileName || 'document.md';
    a.click();
    URL.revokeObjectURL(url);
  }

  /**
   * Open editor panel
   */
  async function openEditor() {
    initElements();
    if (!els?.editor) return;

    els.editor.hidden = false;
    els.toggle.hidden = true;
    document.body.style.overflow = 'hidden';

    // Load source and Pyodide in parallel
    try {
      const [source] = await Promise.all([
        fetchSource(),
        loadPyodide()
      ]);
      
      els.source.value = source;
      await renderPreview();
    } catch (err) {
      els.source.value = `# ${t('editor_status_load_failed')}\n\n${err.message}`;
    }
  }

  /**
   * Close editor panel
   */
  function closeEditor() {
    if (!els?.editor) return;
    
    els.editor.hidden = true;
    els.toggle.hidden = false;
    document.body.style.overflow = '';
  }

  /**
   * Load translations from JSON file
   */
  async function loadTranslations() {
    try {
      const baseUrl = document.querySelector('link[rel="stylesheet"][href*="/assets/"]')?.href?.split('/assets/')[0] || '';
      const resp = await fetch(baseUrl + '/assets/js/translations.json');
      translations = await resp.json();
      applyTranslations();
    } catch (err) {
      console.warn('Failed to load translations:', err);
    }
  }

  /**
   * Apply translations to DOM elements with data-i18n attributes
   */
  function applyTranslations() {
    // Translate text content
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      el.textContent = t(key);
    });

    // Translate title attributes
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
      const key = el.getAttribute('data-i18n-title');
      el.setAttribute('title', t(key));
    });

    // Translate placeholder attributes
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
      const key = el.getAttribute('data-i18n-placeholder');
      el.setAttribute('placeholder', t(key));
    });
  }

  /**
   * Initialize event listeners
   */
  function init() {
    initElements();
    if (!els?.toggle) return;

    // Load translations first
    loadTranslations();

    els.toggle.addEventListener('click', openEditor);
    els.close?.addEventListener('click', closeEditor);
    els.download?.addEventListener('click', downloadSource);
    els.source?.addEventListener('input', scheduleRender);

    // ESC to close
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && els?.editor && !els.editor.hidden) {
        closeEditor();
      }
    });
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
