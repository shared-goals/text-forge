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
      save: document.getElementById('md-editor-save'),
      sync: document.getElementById('md-editor-sync'),
      sync: document.getElementById('md-editor-sync'),
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
      await micropip.install(['markdown', 'pymdown-extensions']);

      // Use embedded markdown extensions config from page
      const pythonConfig = generatePythonMarkdownConfig(config.markdownExtensions, config.extensionConfigs);

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
   * Generate Python markdown configuration from extensions array
   */
  function generatePythonMarkdownConfig(markdownExtensions, extensionConfigs) {
    if (!markdownExtensions || !Array.isArray(markdownExtensions)) {
      throw new Error(t('editor_error_no_extensions'));
    }
    
    // Build extensions list
    const extList = markdownExtensions.map(ext => `'${ext}'`);
    
    // Convert JS object to Python dict format recursively
    function toPythonDict(obj) {
      if (obj === null) return 'None';
      if (obj === true) return 'True';
      if (obj === false) return 'False';
      if (typeof obj === 'number') return obj.toString();
      if (typeof obj === 'string') return `"${obj.replace(/"/g, '\\"')}"`;
      if (Array.isArray(obj)) {
        return '[' + obj.map(item => toPythonDict(item)).join(', ') + ']';
      }
      if (typeof obj === 'object') {
        const pairs = Object.keys(obj).map(key => {
          return `"${key}": ${toPythonDict(obj[key])}`;
        });
        return '{' + pairs.join(', ') + '}';
      }
      return 'None';
    }
    
    // Convert configs to Python dict format
    const configPython = extensionConfigs && Object.keys(extensionConfigs).length > 0
      ? `, extension_configs=${toPythonDict(extensionConfigs)}`
      : '';
    
    return `md = markdown.Markdown(extensions=[${extList.join(', ')}]${configPython})`;
  }

  /**
   * Strip YAML frontmatter from markdown source
   */
  function stripFrontmatter(source) {
    // Check if source starts with ---
    if (source.trim().startsWith('---')) {
      // Find the closing ---
      const lines = source.split('\n');
      let endIndex = -1;
      for (let i = 1; i < lines.length; i++) {
        if (lines[i].trim() === '---') {
          endIndex = i;
          break;
        }
      }
      // If we found closing ---, strip everything up to and including it
      if (endIndex > 0) {
        return lines.slice(endIndex + 1).join('\n');
      }
    }
    return source;
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
      // Strip frontmatter before rendering
      const sourceWithoutFrontmatter = stripFrontmatter(source);
      const html = await pyodide.runPythonAsync(`render_markdown(${JSON.stringify(sourceWithoutFrontmatter)})`);
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
   * GitHub API integration
   */
  
  const GITHUB_TOKEN_KEY = 'text_forge_github_token';
  
  /**
   * Check if GitHub token is available
   */
  function hasGitHubToken() {
    return !!localStorage.getItem(GITHUB_TOKEN_KEY);
  }
  
  /**
   * Get GitHub token from localStorage
   */
  function getGitHubToken() {
    return localStorage.getItem(GITHUB_TOKEN_KEY);
  }
  
  /**
   * Set GitHub token in localStorage
   */
  function setGitHubToken(token) {
    localStorage.setItem(GITHUB_TOKEN_KEY, token);
  }
  
  /**
   * Remove GitHub token
   */
  function removeGitHubToken() {
    localStorage.removeItem(GITHUB_TOKEN_KEY);
  }
  
  /**
   * Prompt user to enter GitHub Personal Access Token
   */
  function promptGitHubToken() {
    const token = prompt(
      t('editor_github_login') + '\n\n' +
      'Введите Personal Access Token с правами repo:\n' +
      'https://github.com/settings/tokens'
    );
    
    if (token && token.trim()) {
      setGitHubToken(token.trim());
      return token.trim();
    }
    
    return null;
  }
  
  /**
   * Save file to GitHub using Contents API
   */
  async function saveToGitHub(filePath, content) {
    if (!config.github) {
      throw new Error('GitHub configuration not available');
    }
    
    let token = getGitHubToken();
    
    // Prompt for token if not available
    if (!token) {
      token = promptGitHubToken();
      if (!token) {
        throw new Error('GitHub token required');
      }
    }
    
    const { owner, repo, branch, apiUrl } = config.github;
    
    // Step 1: Get current file SHA
    const getUrl = `${apiUrl}/repos/${owner}/${repo}/contents/${filePath}?ref=${branch}`;
    
    setStatus(t('editor_github_committing'));
    
    let sha = null;
    try {
      const getResponse = await fetch(getUrl, {
        headers: {
          'Authorization': `Bearer ${token}`,
          'Accept': 'application/vnd.github.v3+json'
        }
      });
      
      if (getResponse.ok) {
        const fileData = await getResponse.json();
        sha = fileData.sha;
      } else if (getResponse.status === 401) {
        // Token invalid or expired
        removeGitHubToken();
        throw new Error('Invalid GitHub token');
      } else if (getResponse.status !== 404) {
        // Unexpected error (404 is OK for new files)
        throw new Error(`Failed to get file: ${getResponse.status}`);
      }
    } catch (error) {
      if (error.message === 'Invalid GitHub token') {
        throw error;
      }
      // Continue with null SHA for new files
    }
    
    // Step 2: Update file content
    const putUrl = `${apiUrl}/repos/${owner}/${repo}/contents/${filePath}`;
    const commitMessage = `Edit ${filePath.split('/').pop()} via text-forge`;
    
    const putResponse = await fetch(putUrl, {
      method: 'PUT',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github.v3+json',
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        message: commitMessage,
        content: btoa(unescape(encodeURIComponent(content))), // Base64 encode UTF-8
        branch: branch,
        ...(sha ? { sha } : {}) // Include SHA for updates
      })
    });
    
    if (!putResponse.ok) {
      const errorData = await putResponse.json();
      
      if (putResponse.status === 401) {
        removeGitHubToken();
        throw new Error('Invalid GitHub token');
      } else if (putResponse.status === 403) {
        throw new Error(t('editor_github_no_permission'));
      } else if (putResponse.status === 409) {
        throw new Error('File was modified. Please refresh and try again.');
      } else {
        throw new Error(errorData.message || `HTTP ${putResponse.status}`);
      }
    }
    
    const result = await putResponse.json();
    return result;
  }
  
  /**
   * Save current source to file
   */
  async function saveSource() {
    if (!els?.source) return;
    
    const content = els.source.value;
    const filePath = config.filePath;
    
    if (!filePath) {
      setStatus(t('editor_status_save_failed'));
      return;
    }
    
    try {
      setStatus(t('editor_status_saving'));
      
      // Strategy 1: Try GitHub API if config available
      if (config.github && config.github.owner) {
        try {
          await saveToGitHub(filePath, content);
          setStatus(t('editor_github_committed'));
          setTimeout(() => setStatus(t('editor_status_ready')), 3000);
          return;
        } catch (githubError) {
          console.error('GitHub save failed:', githubError);
          
          // If token issue, let user retry or fall back
          if (githubError.message.includes('token')) {
            setStatus(t('editor_github_commit_failed') + ': ' + githubError.message);
            setTimeout(() => setStatus(t('editor_status_ready')), 3000);
            return;
          }
          
          // Otherwise fall through to dev server
        }
      }
      
      // Strategy 2: Try dev server endpoint
      const response = await fetch('/_text_forge/save', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          filePath: filePath,
          content: content
        })
      });
      
      if (response.ok) {
        const result = await response.json();
        setStatus(t('editor_status_saved'));
        setTimeout(() => setStatus(t('editor_status_ready')), 2000);
        return;
      }
      
      // Strategy 3: Fallback to download
      if (response.status === 404) {
        downloadAsFile(content, filePath);
        return;
      }
      
      const errorData = await response.text();
      console.error('Save failed:', response.status, errorData);
      throw new Error(`HTTP ${response.status}`);
      
    } catch (error) {
      console.error('Save error:', error);
      // Final fallback to download
      downloadAsFile(content, filePath);
    }
  }
  
  /**
   * Download content as file (fallback for production)
   */
  function downloadAsFile(content, filePath) {
    const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filePath.split('/').pop();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(a.href);
    
    setStatus(t('editor_status_saved'));
    setTimeout(() => setStatus(t('editor_status_ready')), 2000);
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
      // Get base path from page URL (works for both mkdocs serve and built site)
      const pathParts = window.location.pathname.split('/').filter(p => p);
      const baseUrl = pathParts.length > 0 ? '/' + pathParts[0] : '';
      const resp = await fetch(baseUrl + '/assets/js/translations.json');
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      translations = await resp.json();
      applyTranslations();
    } catch (err) {
      console.warn('Failed to load translations:', err);
      // Use empty translations as fallback
      translations = {};
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
   * Sync scroll position from source to preview
   */
  function syncScroll() {
    if (!els?.source || !els?.preview) return;
    
    const textarea = els.source;
    const previewParent = els.preview.parentElement;
    
    // Simple approach: match scroll percentage
    const scrollRatio = textarea.scrollTop / (textarea.scrollHeight - textarea.clientHeight);
    const targetScroll = scrollRatio * (previewParent.scrollHeight - previewParent.clientHeight);
    
    previewParent.scrollTop = targetScroll;
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
    els.save?.addEventListener('click', saveSource);
    els.sync?.addEventListener('click', syncScroll);
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
