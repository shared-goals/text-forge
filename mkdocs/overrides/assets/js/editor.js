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

  // Track original source for change detection
  let originalSource = null;

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
      githubLogout: document.getElementById('md-editor-github-logout'),
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
   * Update Save button state based on content changes
   */
  function updateSaveButtonState() {
    if (!els?.save || !els?.source) return;
    
    const currentContent = els.source.value;
    const hasChanges = originalSource !== null && currentContent !== originalSource;
    
    els.save.disabled = !hasChanges;
    els.save.style.opacity = hasChanges ? '1' : '0.5';
    els.save.style.cursor = hasChanges ? 'pointer' : 'not-allowed';
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
    updateSaveButtonState();
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
   * Update GitHub logout button visibility based on token status
   */
  function updateGitHubButtonVisibility() {
    if (!els?.githubLogout) return;
    
    // Show logout button only when token is present
    els.githubLogout.style.display = hasGitHubToken() ? 'inline-flex' : 'none';
  }
  
  /**
   * Prompt user to enter GitHub Personal Access Token
   */
  function promptGitHubToken() {
    const tokenUrl = 'https://github.com/settings/tokens/new?description=text-forge-editor&scopes=repo';
    
    // Show URL in the prompt directly
    const token = prompt(
      t('editor_github_token_prompt_title') + '\n\n' +
      t('editor_github_token_prompt_fork') + '\n\n' +
      t('editor_github_token_prompt_step1') + '\n\n' +
      tokenUrl + '\n\n' +
      t('editor_github_token_prompt_step2') + '\n' +
      t('editor_github_token_prompt_step3') + '\n\n' +
      t('editor_github_token_prompt_input')
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
    const localFilePath = config.localFilePath;
    
    if (!filePath) {
      setStatus(t('editor_status_save_failed'));
      return;
    }
    
    try {
      setStatus(t('editor_status_saving'));
      
      // Auto-detect save strategy based on hostname:
      // - localhost/127.0.0.1 → save to local dev server
      // - production domain → save to GitHub
      const isLocalhost = window.location.hostname === 'localhost' || 
                         window.location.hostname === '127.0.0.1' ||
                         window.location.hostname === '';
      
      // Strategy 1: Try dev server endpoint (localhost only)
      if (isLocalhost) {
        try {
          const response = await fetch('/_text_forge/save', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            filePath: localFilePath || filePath,
            content: content
          })
        });
        
        if (response.ok) {
          const result = await response.json();
          setStatus(t('editor_status_saved'));
          // Update originalSource so button becomes disabled again
          originalSource = content;
          updateSaveButtonState();
          setTimeout(() => setStatus(t('editor_status_ready')), 2000);
          return;
        }
        
        // If not 404, log error for debugging
        if (response.status !== 404) {
          console.error('Dev server error:', response.status);
        }
      } catch (devServerError) {
        // Dev server not reachable, silently continue to next strategy
      }
      }
      
      // Strategy 2: Try GitHub API (production or if dev server unavailable)
      if (config.github && config.github.owner) {
        try {
          await saveToGitHub(filePath, content);
          setStatus(t('editor_github_committed'));
          // Update originalSource so button becomes disabled again
          originalSource = content;
          updateSaveButtonState();
          setTimeout(() => setStatus(t('editor_status_ready')), 3000);
          return;
        } catch (githubError) {
          // If token issue, let user retry or fall back
          if (githubError.message.includes('token')) {
            setStatus(t('editor_github_commit_failed') + ': ' + githubError.message);
            setTimeout(() => setStatus(t('editor_status_ready')), 3000);
            return;
          }
          
          // Re-throw to prevent fallback to download
          throw githubError;
        }
      }
      
      // Strategy 3: Fallback to download
      downloadAsFile(content, filePath);
      // Update originalSource after download
      originalSource = content;
      updateSaveButtonState();
      
    } catch (error) {
      console.error('Save error:', error);
      downloadAsFile(content, filePath);
      originalSource = content;
      updateSaveButtonState();
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
   * Position sync buttons at exact pane divider
   */
  function positionSyncButtons() {
    const sourcePane = document.querySelector('.md-editor__pane--source');
    const syncs = document.querySelector('.md-editor__syncs');
    const toolbar = document.querySelector('.md-editor__toolbar');
    if (!sourcePane || !syncs || !toolbar) return;

    const rect = sourcePane.getBoundingClientRect();
    const dividerX = rect.right;
    const toolbarRect = toolbar.getBoundingClientRect();
    
    syncs.style.left = `${dividerX}px`;
    syncs.style.top = `${toolbarRect.top}px`;
    syncs.style.height = `${toolbarRect.height}px`;
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

    // Position sync buttons at divider
    requestAnimationFrame(() => {
      positionSyncButtons();
      window.addEventListener('resize', positionSyncButtons);
    });

    // Set filename in toolbar
    const filenameEl = document.getElementById('md-editor-filename');
    if (filenameEl && config.filePath) {
      // Extract just the filename from the path
      const filename = config.filePath.split('/').pop();
      filenameEl.textContent = filename;
    }

    // Disable Save button initially (no changes yet)
    if (els?.save) {
      els.save.disabled = true;
      els.save.style.opacity = '0.5';
      els.save.style.cursor = 'not-allowed';
    }

    // Load source and Pyodide in parallel
    try {
      const [source] = await Promise.all([
        fetchSource(),
        loadPyodide()
      ]);
      
      originalSource = source;
      els.source.value = source;
      updateSaveButtonState();
      await renderPreview();
    } catch (err) {
      els.source.value = `# ${t('editor_status_load_failed')}\n\n${err.message}`;
      originalSource = null;
      console.error('Editor failed to load:', err);
    }
  }

  /**
   * Close editor panel
   */
  function closeEditor() {
    if (!els?.editor) return;
    
    window.removeEventListener('resize', positionSyncButtons);
    els.editor.hidden = true;
    els.toggle.hidden = false;
    document.body.style.overflow = '';
    originalSource = null;
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
   * Sync scroll position from source to preview (left to right)
   */
  function syncScrollRight() {
    if (!els?.source || !els?.preview) return;
    
    const textarea = els.source;
    const previewParent = els.preview.parentElement;
    
    // Simple approach: match scroll percentage
    const scrollRatio = textarea.scrollTop / (textarea.scrollHeight - textarea.clientHeight);
    const targetScroll = scrollRatio * (previewParent.scrollHeight - previewParent.clientHeight);
    
    previewParent.scrollTop = targetScroll;
  }

  /**
   * Sync scroll position from preview to source (right to left)
   */
  function syncScrollLeft() {
    if (!els?.source || !els?.preview) return;
    
    const textarea = els.source;
    const previewParent = els.preview.parentElement;
    
    // Match scroll percentage from preview to source
    const scrollRatio = previewParent.scrollTop / (previewParent.scrollHeight - previewParent.clientHeight);
    const targetScroll = scrollRatio * (textarea.scrollHeight - textarea.clientHeight);
    
    textarea.scrollTop = targetScroll;
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
    els.githubLogout?.addEventListener('click', () => {
      removeGitHubToken();
      updateGitHubButtonVisibility();
      setStatus(t('editor_github_logged_out') || 'GitHub token cleared');
    });
    
    // Sync buttons
    const syncRight = document.getElementById('md-editor-sync-right');
    const syncLeft = document.getElementById('md-editor-sync-left');
    syncRight?.addEventListener('click', syncScrollRight);
    syncLeft?.addEventListener('click', syncScrollLeft);
    
    els.source?.addEventListener('input', scheduleRender);

    // ESC to close
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && els?.editor && !els.editor.hidden) {
        closeEditor();
      }
    });
    
    // Update GitHub login button visibility
    updateGitHubButtonVisibility();
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
