/**
 * prodComp Platform — Frontend Alpine.js application v2.0
 * Covers all features F01-F74 (except F68 which was excluded).
 */

function app() {
  return {
    // Auth
    authenticated: false,
    loginForm: { username: 'admin', password: '' },
    loginError: '',

    // UI state
    darkMode: localStorage.getItem('darkMode') === 'true',
    currentView: 'dashboard',
    selectedProduct: null,
    productMatches: [],          // competitor matches for the selected product
    productMatchesLoading: false,
    selectedCompetitor: null,
    toasts: [],
    _toastId: 0,

    // Nav items
    navItems: [
      { id: 'dashboard',    icon: '📊', label: 'Dashboard',        badge: 0 },
      { id: 'products',     icon: '📦', label: 'Products',          badge: 0 },
      { id: 'competitors',  icon: '🏪', label: 'Competitors',       badge: 0 },
      { id: 'pricing',      icon: '💰', label: 'Price Comparison',  badge: 0 },
      { id: 'scans',        icon: '🔍', label: 'Scans',             badge: 0 },
      { id: 'find-product',    icon: '🔎', label: 'Find Product',       badge: 0 },
      { id: 'beat-price',      icon: '💡', label: 'Beat This Price',    badge: 0 },
      { id: 'scheduler',    icon: '⏰', label: 'Scheduler',         badge: 0 },
      { id: 'reports',      icon: '📋', label: 'Reports',           badge: 0 },
      { id: 'export',       icon: '📤', label: 'Export',            badge: 0 },
      { id: 'settings',     icon: '⚙️',  label: 'Settings',         badge: 0 },
    ],

    // Dashboard
    stats: {},

    // Products
    productData: { products: [], total: 0, page: 1, pages: 1 },
    productFilters: { search: '', manufacturer: '', category: '', source_site: '', min_price: '', max_price: '' },
    filterOptions: { manufacturers: [], categories: [], source_sites: [] },
    loadingProducts: false,
    productSelected: {},          // { product_id: true/false }
    productCompMax: 5,
    productCompRunning: false,
    productCompIsParallel: false,           // true when using parallel endpoint (2+ products)
    productCompProgress: null,    // { product_title, found, max, phase, current_domain }
    productCompMode: false,                 // true while search-mode view is active
    productCompSearchProducts: [],          // [{id, title, price, primary_image}] — products being searched
    productCompCounts: {},                  // {product_id: {found, target, done, searching, current_domain}}
    productCompPauseState: null,            // {product_id, product_title, found, visited, max} when paused
    productCompNetworkError: false,         // true if the search completed with 0 found AND the internet was unreachable
    priceComparison: null,
    priceHistory: null,
    loadingPriceComp: false,

    // Scans
    scanSessions: { sessions: [] },
    sourceSites: [],
    scanRunning: false,
    activeScanId: null,
    scanStatus: { message: '', current: 0, total: 0 },

    // Dashboard live log tail
    logTail: [],
    logLevelFilter: 'all',  // 'all' | 'INFO' | 'WARNING' | 'CRITICAL'
    _logPollTimer: null,

    // Find This Product
    findProductQuery: '',
    findProductModelNumber: '',
    findProductCategory: '',
    findProductMinFuzzyScore: 0,
    findProductIds: [],
    findProductCatalogSearch: '',
    findProductCatalogResults: [],
    findProductMaxResults: 5,
    findProductResults: [],
    findProductCompResults: [],
    findProductLoading: false,
    findProductSearched: false,
    findProductHistory: [],
    findProductHistoryOpen: false,

    // Beat This Price
    beatPriceForm: { description: '', price_min: '', price_max: '', max_results: 10 },
    beatPriceChars: { size: '', color: '', manufacturer: '', country_of_origin: '', features: '' },
    beatPriceResults: [],            // Flat list when free-text only
    beatPriceGroupedResults: [],     // Per-product groups when products selected
    beatPriceLoading: false,
    beatPriceProductIds: [],         // IDs of selected master products
    beatPriceCatalogSearch: '',
    beatPriceCatalogResults: [],
    beatPriceProgress: '',           // Status text while running multi-product
    beatPriceHistory: [],
    beatPriceHistoryOpen: false,

    taskList: [],

    // Competitors
    competitors: { competitors: [], total: 0 },
    competitorPage: 1,
    competitorSearch: '',
    discoverForm: { max_results: 20, session_name: '' },
    discoverKeywords: ['commercial donut fryer', 'bakery equipment dealer', 'donut equipment wholesale'],
    newKeyword: '',
    keywordEditIndex: -1,
    keywordEditText: '',
    bulkImportText: '',
    bulkImportSessionName: '',
    competitorScanForm: { ids: [], session_name: '', find_similar: false, max_pages: 100, criteria: {} },
    competitorScanRunning: false,
    webSearchRunning: false,
    webSearchCheckpoint: null,
    webSearchUrlLog: [],
    webSearchMaxResults: 20,
    webSearchProductLimit: 100,
    competitorProfile: null,
    competitorProfileSaving: false,
    productSort: { col: '', dir: 'asc' },
    competitorSort: { col: '', dir: 'asc' },
    competitorCols: ['domain', 'matches', 'session', 'last_scanned'],
    competitorDragFrom: null,
    competitorScanCriteria: {
      use_model_number: true, use_manufacturer: true, use_title_fuzzy: true,
      use_title_exact: true, use_price: false, fuzzy_threshold: 70,
    },
    competitorDetail: null,
    discoverRunning: false,
    competitorEditId: null,
    competitorEditForm: { name: '', base_url: '' },
    competitorSelected: [],
    competitorDeleteModal: false,
    competitorDeleteExclude: false,

    // Pricing matrix
    priceMatrix: { rows: [], competitors: [], total: 0, page: 1, pages: 1 },
    priceMatrixPage: 1,
    priceMatrixSortDir: 'asc',  // 'asc' = cheapest first, 'desc' = most expensive first
    priceMatrixFilters: { search: '', manufacturer: '', category: '', source_site: '' },
    priceMatrixSelected: {},
    priceMatrixHasSearched: false,
    loadingMatrix: false,

    // Scheduler
    jobs: [],
    newJob: {
      name: '', job_type: 'source_scan', target: '',
      schedule_type: 'daily', schedule_value: '09:00', config_json: ''
    },

    // Reports
    reportFrame: '',
    reportType: 'summary',
    reportParams: { threshold: 5.0, days: 7, competitor_id: '', product_id: '' },

    // Export
    exportHistory: { records: [] },
    exportForm: { fmt: 'xlsx', include_competitors: true, include_price_history: false },

    // Settings
    settingsData: {},
    webhookForm: { url: '', events: ['price_alert', 'scan_complete', 'competitor_scan_complete'], secret: '' },
    managedLists: { manufacturers: [], excluded: [], competitors: [] },
    newManagedUrl: { manufacturer: '', excluded: '', competitor: '' },

    // WebSocket
    ws: null,
    wsConnected: false,
    _wsReconnectTimer: null,

    // -----------------------------------------------------------------------
    // Lifecycle
    // -----------------------------------------------------------------------
    async init() {
      this.$watch('darkMode', v => localStorage.setItem('darkMode', v));
      await this.checkAuth();
      if (this.authenticated) await this.postLoginInit();
    },

    async postLoginInit() {
      await Promise.all([
        this.loadStats(),
        this.loadFilterOptions(),
        this.loadScanSessions(),
        this.loadSettings(),
        this.loadManagedLists(),
        this.loadCompetitors(),
        this.loadJobs(),
        this.loadExportHistory(),
      ]);
      this.loadSourceSites();
      this.connectWebSocket();
      // Initial population; subsequent updates arrive via the WebSocket
      // 'log_tail' event (see handleWsMessage). The setInterval poll is a
      // safety net in case the WS disconnects and the reconnect lags.
      this.loadLogTail();
      this._logPollTimer = setInterval(() => {
        if (!this.wsConnected) this.loadLogTail();
      }, 5000);
      // Wire up column resizers for every current and future table.
      this._initColumnResize();
    },

    // -----------------------------------------------------------------------
    // Resizable table columns
    // Drag the right edge of any <th> to resize. Widths persist per
    // (table-key, column-index) in localStorage so reloads keep user choices.
    // -----------------------------------------------------------------------
    _initColumnResize() {
      if (this._colResizeInit) return;
      this._colResizeInit = true;
      const wire = () => document.querySelectorAll('table').forEach(t => this._wireTableResize(t));
      wire();
      // Re-wire when new tables/rows appear from x-for templates.
      const obs = new MutationObserver(muts => {
        let touched = false;
        for (const m of muts) {
          for (const n of m.addedNodes) {
            if (n.nodeType !== 1) continue;
            if (n.tagName === 'TABLE' || n.querySelector?.('table')) { touched = true; break; }
          }
          if (touched) break;
        }
        if (touched) wire();
      });
      obs.observe(document.body, { childList: true, subtree: true });
    },

    _tableKey(table) {
      // Identify a table by its closest view container (x-show="currentView === '...'")
      // plus its position within that container, so persisted widths survive re-renders.
      let view = 'global';
      let el = table.parentElement;
      while (el) {
        const m = (el.getAttribute?.('x-show') || '').match(/currentView\s*===\s*'([^']+)'/);
        if (m) { view = m[1]; break; }
        el = el.parentElement;
      }
      const sameViewTables = Array.from(document.querySelectorAll(`[x-show*="${view}"] table, [x-show*="'${view}'"] table`));
      const idx = sameViewTables.indexOf(table);
      return `colw:${view}:${idx >= 0 ? idx : 0}`;
    },

    _wireTableResize(table) {
      if (table.__colResizeWired) return;
      const ths = table.querySelectorAll(':scope > thead > tr > th');
      if (!ths.length) return;
      table.__colResizeWired = true;

      const key = this._tableKey(table);
      let saved = {};
      try { saved = JSON.parse(localStorage.getItem(key) || '{}'); } catch {}
      const hasSaved = Object.keys(saved).length > 0;

      // Pin the table to fixed layout (using either saved widths or each
      // column's current natural width). Called once, before the first
      // resize event or immediately if there are persisted widths.
      const pinTable = () => {
        if (table.__pinned) return;
        ths.forEach((th, i) => {
          const w = saved[i] || th.offsetWidth;
          if (w > 0) {
            th.style.width = w + 'px';
            th.style.minWidth = w + 'px';
          }
        });
        table.style.tableLayout = 'fixed';
        table.classList.add('col-resize-active');
        table.__pinned = true;
      };
      if (hasSaved) pinTable();

      ths.forEach((th, i) => {
        const cs = getComputedStyle(th);
        if (cs.position === 'static') th.style.position = 'relative';
        if (i === ths.length - 1) return;  // skip grip on last column
        const grip = document.createElement('span');
        grip.className = 'col-resize-grip';
        grip.title = 'Drag to resize · double-click to reset';
        th.appendChild(grip);

        let startX = 0, startW = 0;
        const onMove = e => {
          const dx = e.pageX - startX;
          const w = Math.max(40, startW + dx);
          th.style.width = w + 'px';
          th.style.minWidth = w + 'px';
        };
        const onUp = () => {
          document.removeEventListener('mousemove', onMove);
          document.removeEventListener('mouseup', onUp);
          document.body.style.cursor = '';
          document.body.classList.remove('col-resizing');
          try {
            const cur = JSON.parse(localStorage.getItem(key) || '{}');
            cur[i] = Math.round(th.offsetWidth);
            localStorage.setItem(key, JSON.stringify(cur));
          } catch {}
        };
        grip.addEventListener('mousedown', e => {
          e.preventDefault();
          e.stopPropagation();
          pinTable();
          startX = e.pageX;
          startW = th.offsetWidth;
          document.body.style.cursor = 'col-resize';
          document.body.classList.add('col-resizing');
          document.addEventListener('mousemove', onMove);
          document.addEventListener('mouseup', onUp);
        });
        grip.addEventListener('dblclick', e => {
          e.preventDefault();
          e.stopPropagation();
          th.style.width = '';
          th.style.minWidth = '';
          try {
            const cur = JSON.parse(localStorage.getItem(key) || '{}');
            delete cur[i];
            localStorage.setItem(key, JSON.stringify(cur));
          } catch {}
        });
      });
    },

    // -----------------------------------------------------------------------
    // Auth
    // -----------------------------------------------------------------------
    async checkAuth() {
      try {
        const r = await fetch('/api/auth/status');
        const d = await r.json();
        if (d.authenticated || !d.auth_enabled) this.authenticated = true;
      } catch {}
    },

    async doLogin() {
      this.loginError = '';
      try {
        const r = await fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(this.loginForm),
        });
        if (r.ok) {
          this.authenticated = true;
          await this.postLoginInit();
        } else {
          this.loginError = (await r.json()).detail || 'Invalid credentials';
        }
      } catch { this.loginError = 'Could not reach server.'; }
    },

    async doLogout() {
      await fetch('/api/auth/logout', { method: 'POST' });
      this.authenticated = false;
      if (this.ws) this.ws.close();
    },

    // -----------------------------------------------------------------------
    // Toasts
    // -----------------------------------------------------------------------
    toast(message, type = 'info', duration = 4000) {
      const id = ++this._toastId;
      const icons = { success: '✅', error: '❌', info: 'ℹ️', warning: '⚠️' };
      this.toasts.push({ id, message, type, icon: icons[type] || 'ℹ️' });
      setTimeout(() => this.removeToast(id), duration);
    },
    removeToast(id) { this.toasts = this.toasts.filter(t => t.id !== id); },

    // -----------------------------------------------------------------------
    // API helper
    // -----------------------------------------------------------------------
    async api(path, options = {}) {
      const r = await fetch(path, {
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
      });
      if (r.status === 401) { this.authenticated = false; return null; }
      if (!r.ok) {
        let msg = `HTTP ${r.status}`;
        try { msg = (await r.json()).detail || msg; } catch {}
        throw new Error(msg);
      }
      const ct = r.headers.get('content-type') || '';
      if (ct.includes('text/html')) return r.text();
      if (ct.includes('application/json')) return r.json();
      return r.blob();
    },

    // -----------------------------------------------------------------------
    // Dashboard
    // -----------------------------------------------------------------------
    async loadStats() {
      try {
        this.stats = await this.api('/api/stats') || {};
        const compNav = this.navItems.find(n => n.id === 'competitors');
        if (compNav) compNav.badge = this.stats.total_competitors || 0;
      } catch (e) { this.toast('Failed to load stats: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Products
    // -----------------------------------------------------------------------
    async loadProducts(page = 1) {
      this.loadingProducts = true;
      try {
        const params = new URLSearchParams({ page, per_page: 50 });
        if (this.productFilters.search)       params.set('search', this.productFilters.search);
        if (this.productFilters.manufacturer) params.set('manufacturer', this.productFilters.manufacturer);
        if (this.productFilters.category)     params.set('category', this.productFilters.category);
        if (this.productFilters.source_site)  params.set('source_site', this.productFilters.source_site);
        if (this.productFilters.min_price)    params.set('min_price', this.productFilters.min_price);
        if (this.productFilters.max_price)    params.set('max_price', this.productFilters.max_price);
        if (this.productSort.col) {
          params.set('sort_by', this.productSort.col);
          params.set('sort_order', this.productSort.dir);
        }
        this.productData = await this.api(`/api/products?${params}`) || { products: [], total: 0 };
      } catch (e) { this.toast('Failed to load products: ' + e.message, 'error'); }
      finally { this.loadingProducts = false; }
    },

    async loadFilterOptions() {
      try { this.filterOptions = await this.api('/api/products/filters/options') || {}; } catch {}
    },

    async openProduct(product) {
      try { this.selectedProduct = await this.api(`/api/products/${product.id}`) || product; }
      catch { this.selectedProduct = product; }
      this.productMatches = [];
      await this.loadProductMatches(product.id);
    },

    async loadProductMatches(productId) {
      this.productMatchesLoading = true;
      try {
        const res = await this.api(`/api/products/${productId}/competitor-matches`);
        this.productMatches = res?.matches || [];
      } catch {}
      finally { this.productMatchesLoading = false; }
    },

    async denyProductMatch(productId, matchId) {
      await this.api(`/api/products/${productId}/competitor-matches/${matchId}`, { method: 'DELETE' });
      this.productMatches = this.productMatches.filter(m => m.id !== matchId);
      this.toast('Match denied and removed', 'info');
    },

    async runProductCompSearch() {
      const ids = Object.keys(this.productSelected).filter(k => this.productSelected[k]).map(Number);
      if (!ids.length) { this.toast('Select at least one product', 'warning'); return; }
      if (this.productCompRunning) return;

      const target = Math.max(1, parseInt(this.productCompMax) || 5);

      // Switch to search-mode view showing only the selected products
      this.productCompSearchProducts = (this.productData.products || [])
        .filter(p => ids.includes(p.id))
        .map(p => ({ id: p.id, title: p.title || p.canonical_title, price: p.price, primary_image: p.primary_image }));
      this.productCompCounts = {};
      for (const p of this.productCompSearchProducts) {
        this.productCompCounts[p.id] = { found: 0, target, done: false, searching: false, current_domain: null };
      }
      const useParallel = ids.length > 1;
      this.productCompMode = true;
      this.productCompRunning = true;
      this.productCompIsParallel = useParallel;
      this.productCompProgress = null;
      this.productCompPauseState = null;
      this.productCompNetworkError = false;

      try {
        if (useParallel) {
          await this.api('/api/products/parallel-competitor-search', {
            method: 'POST',
            body: JSON.stringify({
              product_ids: ids,
              max_competitors: target,
              num_workers: Math.min(4, ids.length),
              max_urls: 150,
            }),
          });
        } else {
          await this.api('/api/products/competitor-search', {
            method: 'POST',
            body: JSON.stringify({
              product_ids: ids,
              max_competitors: target,
              max_urls: 150,
              num_fetchers: 4,
              pause_after: 100,
            }),
          });
        }
      } catch (e) {
        this.productCompRunning = false;
        this.productCompMode = false;
        this.toast('Failed to start competitor search: ' + e.message, 'error');
      }
    },

    async resumeCompSearch() {
      this.productCompPauseState = null;
      try {
        await this.api('/api/products/competitor-search/resume', { method: 'POST' });
      } catch (e) {
        this.toast('Resume failed: ' + e.message, 'error');
      }
    },

    async stopCompSearch() {
      this.productCompPauseState = null;
      this.productCompRunning = false;
      const endpoint = this.productCompIsParallel
        ? '/api/products/parallel-competitor-search/stop'
        : '/api/products/competitor-search/stop';
      try {
        await this.api(endpoint, { method: 'POST' });
      } catch (e) {
        this.toast('Stop failed: ' + e.message, 'error');
      }
    },

    clearProductSelection() {
      this.productSelected = {};
    },

    exitCompSearchMode() {
      this.productCompMode = false;
      this.productCompSearchProducts = [];
      this.productCompCounts = {};
      this.productCompPauseState = null;
      this.loadProducts();
    },

    // Triggered from the Find This Product page using its own selection model.
    async runFindProductCompSearch() {
      const ids = (this.findProductIds || []).map(Number);
      if (!ids.length) { this.toast('Select at least one product from the catalog', 'warning'); return; }
      if (this.productCompRunning) return;
      this.productCompRunning = true;
      this.productCompProgress = null;
      try {
        await this.api('/api/products/competitor-search', {
          method: 'POST',
          body: JSON.stringify({
            product_ids: ids,
            max_competitors: Math.max(1, parseInt(this.productCompMax) || 5),
            max_urls: 30,
          }),
        });
        this.toast(`Competitor search started for ${ids.length} product${ids.length !== 1 ? 's' : ''}`, 'info');
      } catch (e) {
        this.productCompRunning = false;
        this.toast('Failed to start competitor search: ' + e.message, 'error');
      }
    },

    toggleAllProducts() {
      const all = this.sortedProducts();
      const allSelected = all.every(p => this.productSelected[p.id]);
      all.forEach(p => { this.productSelected[p.id] = !allSelected; });
    },

    async loadPriceComparison(productId) {
      this.loadingPriceComp = true;
      this.priceComparison = null;
      try {
        this.priceComparison = await this.api(`/api/products/${productId}/price-comparison`);
      } catch (e) { this.toast('Failed to load price comparison: ' + e.message, 'error'); }
      finally { this.loadingPriceComp = false; }
    },

    async aiCategorize(productIds) {
      try {
        await this.api('/api/ai/categorize', { method: 'POST', body: JSON.stringify({ product_ids: productIds }) });
        this.toast('AI categorization started...', 'info');
      } catch (e) { this.toast('AI categorize failed: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Scans
    // -----------------------------------------------------------------------
    loadSourceSites() {
      if (this.settingsData?.source_sites) {
        this.sourceSites = this.settingsData.source_sites.filter(s => s.enabled);
      }
    },

    async startScan(siteFilter = null) {
      if (this.scanRunning) return;
      this.scanRunning = true;
      this.scanStatus = { message: 'Starting scan...', current: 0, total: 0 };
      try {
        const body = siteFilter ? { site_filter: siteFilter } : {};
        const r = await this.api('/api/scan/sources', { method: 'POST', body: JSON.stringify(body) });
        if (r) {
          this.activeScanId = r.scan_session_id;
          this.toast('Source scan started', 'info');
          await this.loadScanSessions();
        }
      } catch (e) {
        this.scanRunning = false;
        this.toast('Failed to start scan: ' + e.message, 'error');
      }
    },

    async loadScanSessions() {
      try {
        this.scanSessions = await this.api('/api/scan/sessions?per_page=20') || { sessions: [] };
        const running = (this.scanSessions.sessions || []).find(s => s.status === 'running');
        if (running && !this.scanRunning) {
          this.scanRunning = true;
          this.activeScanId = running.id;
          this.scanStatus = { message: 'Scan in progress...' };
        } else if (!running && this.scanRunning) {
          this.scanRunning = false;
          this.scanStatus = {};
          await this.loadStats();
          this.toast('Scan completed', 'success');
        }
      } catch {}
    },

    // -----------------------------------------------------------------------
    // Dashboard — live log tail + cycle status helpers
    // -----------------------------------------------------------------------
    async loadLogTail() {
      try {
        const r = await this.api('/api/logs/tail?lines=50');
        if (r === null) {
          // 401 — session expired, stop polling
          if (this._logPollTimer) { clearInterval(this._logPollTimer); this._logPollTimer = null; }
          return;
        }
        this.logTail = r.lines || [];
      } catch {}
    },

    logLineClass(line) {
      // Color-code by Python logging level — formatter writes "[LEVEL]" tokens.
      if (!line) return 'text-gray-400';
      if (/\[CRITICAL\]/.test(line)) return 'bg-red-900 text-red-200 font-bold';
      if (/\[ERROR\]|\bTraceback\b/.test(line)) return 'text-red-400';
      if (/\[WARNING\]|\[WARN\]/.test(line)) return 'text-amber-300';
      if (/\[DEBUG\]/.test(line)) return 'text-gray-500';
      if (/\[INFO\]/.test(line)) return 'text-sky-300';
      return 'text-gray-200';
    },

    // Detect a log level token at the start of a record line. Continuation
    // lines (no timestamp) return null and inherit the previous record's level.
    _lineLevel(line) {
      if (!line) return null;
      if (/\[CRITICAL\]/.test(line)) return 'CRITICAL';
      if (/\[ERROR\]|\bTraceback\b/.test(line)) return 'ERROR';
      if (/\[WARNING\]|\[WARN\]/.test(line)) return 'WARNING';
      if (/\[INFO\]/.test(line)) return 'INFO';
      if (/\[DEBUG\]/.test(line)) return 'DEBUG';
      return null;
    },

    get filteredLogTail() {
      const lines = this.logTail || [];
      if (this.logLevelFilter === 'all') return lines;
      const target = this.logLevelFilter;
      const out = [];
      let currentLevel = null;
      for (const ln of lines) {
        const lvl = this._lineLevel(ln);
        if (lvl) currentLevel = lvl;
        if (currentLevel === target) out.push(ln);
      }
      return out;
    },


    // -----------------------------------------------------------------------
    // Find This Product
    // -----------------------------------------------------------------------
    async findProductSearchCatalog() {
      try {
        const params = new URLSearchParams({ per_page: 20 });
        if (this.findProductCatalogSearch) params.set('search', this.findProductCatalogSearch);
        const r = await this.api(`/api/products?${params}`);
        this.findProductCatalogResults = r?.products || [];
      } catch {}
    },

    findProductToggle(id) {
      const idx = this.findProductIds.indexOf(id);
      if (idx >= 0) {
        this.findProductIds = this.findProductIds.filter(x => x !== id);
      } else if (this.findProductIds.length < 5) {
        this.findProductIds = [...this.findProductIds, id];
      } else {
        this.toast('Maximum 5 products can be selected', 'info');
      }
    },

    findProductAllResults() {
      const web = (this.findProductResults || []).map(r => ({ ...r, result_type: 'web' }));
      const comp = (this.findProductCompResults || [])
        .filter(r => r.fuzzy_score >= this.findProductMinFuzzyScore)
        .map(r => ({ ...r, result_type: 'competitor', domain: r.domain || r.competitor_domain }));
      return [...web, ...comp];
    },

    async loadFindProductHistory() {
      try {
        const res = await this.api('/api/search/find-product/history?limit=20');
        this.findProductHistory = res?.searches || [];
      } catch {}
    },

    async runFindProduct() {
      if (!this.findProductQuery && !this.findProductIds.length) {
        this.toast('Enter a query or select products from the catalog', 'info');
        return;
      }
      this.findProductLoading = true;
      this.findProductSearched = false;
      this.findProductResults = [];
      this.findProductCompResults = [];
      try {
        const res = await this.api('/api/search/find-product', {
          method: 'POST',
          body: JSON.stringify({
            product_ids: this.findProductIds.length ? this.findProductIds : null,
            query: this.findProductQuery || null,
            model_number: this.findProductModelNumber || null,
            category: this.findProductCategory || null,
            max_results: this.findProductMaxResults,
            min_fuzzy_score: this.findProductMinFuzzyScore || 0,
            search_competitor_sites: true,
          }),
        });
        this.findProductResults = res?.results || [];
        this.findProductCompResults = res?.competitor_results || [];
        await this.loadFindProductHistory();
      } catch (e) { this.toast('Search failed: ' + e.message, 'error'); }
      finally { this.findProductLoading = false; this.findProductSearched = true; }
    },

    // -----------------------------------------------------------------------
    // Beat This Price
    // -----------------------------------------------------------------------
    async beatPriceSearchCatalog() {
      try {
        const params = new URLSearchParams({ per_page: 20 });
        if (this.beatPriceCatalogSearch) params.set('search', this.beatPriceCatalogSearch);
        const r = await this.api(`/api/products?${params}`);
        this.beatPriceCatalogResults = r?.products || [];
      } catch {}
    },

    beatPriceToggleProduct(id) {
      const i = this.beatPriceProductIds.indexOf(id);
      if (i >= 0) this.beatPriceProductIds = this.beatPriceProductIds.filter(x => x !== id);
      else this.beatPriceProductIds = [...this.beatPriceProductIds, id];
    },

    beatPriceClearProducts() {
      this.beatPriceProductIds = [];
    },

    beatPriceReset() {
      this.beatPriceProductIds = [];
      this.beatPriceResults = [];
      this.beatPriceGroupedResults = [];
      this.beatPriceForm = { description: '', price_min: '', price_max: '', max_results: 10 };
      this.beatPriceChars = {};
      this.beatPriceCatalogSearch = '';
      this.beatPriceCatalogResults = [];
    },

    async runBeatPrice() {
      const hasProducts = this.beatPriceProductIds.length > 0;
      const hasDescription = !!(this.beatPriceForm.description || '').trim();
      if (!hasProducts && !hasDescription) {
        this.toast('Select at least one product or enter a description', 'info');
        return;
      }

      this.beatPriceLoading = true;
      this.beatPriceResults = [];
      this.beatPriceGroupedResults = [];
      this.beatPriceProgress = hasProducts ? `Searching ${this.beatPriceProductIds.length} product(s)...` : '';

      const chars = Object.fromEntries(Object.entries(this.beatPriceChars).filter(([, v]) => v));
      const payload = {
        description: this.beatPriceForm.description || null,
        product_ids: hasProducts ? this.beatPriceProductIds : null,
        price_min: this.beatPriceForm.price_min ? parseFloat(this.beatPriceForm.price_min) : null,
        price_max: this.beatPriceForm.price_max ? parseFloat(this.beatPriceForm.price_max) : null,
        characteristics: Object.keys(chars).length ? chars : null,
        max_results: this.beatPriceForm.max_results || 10,
      };

      try {
        const res = await this.api('/api/search/beat-price', { method: 'POST', body: JSON.stringify(payload) });
        this.beatPriceResults = res?.results || [];
        this.beatPriceGroupedResults = res?.groups || [];
        const total = this.beatPriceResults.length + (res?.groups || []).reduce((n, g) => n + (g.results?.length || 0), 0);
        if (!total) this.toast('No suppliers found — try broadening the description', 'info');
        else this.toast(`${total} supplier result${total !== 1 ? 's' : ''} found`, 'success');
      } catch (e) {
        this.toast('Search failed: ' + e.message, 'error');
      } finally {
        this.beatPriceLoading = false;
        this.beatPriceProgress = '';
        await this.loadBeatPriceHistory();
      }
    },

    async loadBeatPriceHistory() {
      try {
        const res = await this.api('/api/search/beat-price/history?limit=20');
        this.beatPriceHistory = res?.searches || [];
      } catch {}
    },

    // -----------------------------------------------------------------------
    // Tasks
    // -----------------------------------------------------------------------
    async loadTaskList() {
      try {
        this.taskList = (await this.api('/api/tasks')).tasks || [];
      } catch {}
    },

    diffClass(hasDiff) {
      return hasDiff ? 'text-red-600 dark:text-red-400 font-semibold' : 'text-green-600 dark:text-green-400';
    },

    // -----------------------------------------------------------------------
    // Competitors (F12-F21)
    // -----------------------------------------------------------------------
    async loadCompetitors(page = 1) {
      try {
        this.competitorPage = page;
        this.competitors = await this.api(`/api/competitors?page=${page}&per_page=50`) || { competitors: [], total: 0 };
      } catch (e) { this.toast('Failed to load competitors: ' + e.message, 'error'); }
    },

    async discoverCompetitors() {
      this.discoverRunning = true;
      try {
        const body = {
          max_results: this.discoverForm.max_results,
          session_name: this.discoverForm.session_name || undefined,
          custom_keywords: this.discoverKeywords.length ? this.discoverKeywords : undefined,
        };
        await this.api('/api/competitors/discover', { method: 'POST', body: JSON.stringify(body) });
        this.toast('Competitor discovery started...', 'info');
      } catch (e) {
        this.discoverRunning = false;
        this.toast('Discovery failed: ' + e.message, 'error');
      }
    },

    addKeyword() {
      const kw = this.newKeyword.trim();
      if (!kw || this.discoverKeywords.includes(kw)) return;
      this.discoverKeywords.push(kw);
      this.newKeyword = '';
    },

    removeKeyword(i) {
      this.discoverKeywords.splice(i, 1);
    },

    startEditKeyword(i) {
      this.keywordEditIndex = i;
      this.keywordEditText = this.discoverKeywords[i];
    },

    saveKeyword() {
      const kw = this.keywordEditText.trim();
      if (kw) this.discoverKeywords[this.keywordEditIndex] = kw;
      this.keywordEditIndex = -1;
      this.keywordEditText = '';
    },

    cancelKeywordEdit() {
      this.keywordEditIndex = -1;
      this.keywordEditText = '';
    },

    async bulkImportCompetitors() {
      const domains = this.bulkImportText.split('\n').map(d => d.trim()).filter(Boolean);
      if (!domains.length) return;
      try {
        const r = await this.api('/api/competitors/bulk-import', {
          method: 'POST',
          body: JSON.stringify({ domains, session_name: this.bulkImportSessionName || undefined }),
        });
        this.toast(`Imported ${r.added} new competitors (${r.parsed} parsed)`, 'success');
        this.bulkImportText = '';
        await this.loadCompetitors();
      } catch (e) { this.toast('Bulk import failed: ' + e.message, 'error'); }
    },

    async scanCompetitors(ids) {
      if (!ids || !ids.length) { this.toast('Select at least one competitor', 'warning'); return; }
      try {
        const body = {
          competitor_ids: ids,
          session_name: this.competitorScanForm.session_name || undefined,
          find_similar: this.competitorScanForm.find_similar,
          max_pages: this.competitorScanForm.max_pages,
          criteria: this.competitorScanCriteria,
        };
        await this.api('/api/competitors/scan', { method: 'POST', body: JSON.stringify(body) });
        this.competitorScanRunning = true;
        this.toast(`Scanning ${ids.length} competitor(s)...`, 'info');
      } catch (e) { this.toast('Competitor scan failed: ' + e.message, 'error'); }
    },

    async scanAllCompetitors() {
      if (this.competitorScanRunning) return;
      if (!this.competitors.competitors.length) await this.loadCompetitors();
      const ids = this.competitors.competitors.map(c => c.id);
      if (!ids.length) { this.toast('No competitors configured yet', 'warning'); return; }
      await this.scanCompetitors(ids);
    },

    async startWebSearchScan() {
      if (this.webSearchRunning) return;
      const n = Math.max(1, Math.min(100, parseInt(this.webSearchMaxResults) || 20));
      const limit = parseInt(this.webSearchProductLimit) || null;
      this.webSearchMaxResults = n;
      this.webSearchRunning = true;
      this.webSearchCheckpoint = null;
      try {
        await this.api('/api/competitors/web-search-scan', {
          method: 'POST',
          body: JSON.stringify({ max_results: n, product_limit: limit || null }),
        });
        const productDesc = limit ? `${limit} products` : 'all products';
        this.toast(`Web search scan started — ${productDesc}, top ${n} results each`, 'info');
      } catch (e) {
        this.webSearchRunning = false;
        this.toast('Failed to start web search scan: ' + e.message, 'error');
      }
    },

    async stopWebSearchScan() {
      try {
        await this.api('/api/competitors/web-search-scan/stop', { method: 'POST' });
        this.toast('Stop requested — scan will halt after current product', 'info');
      } catch (e) {
        this.toast('Failed to stop scan: ' + e.message, 'error');
      }
    },

    async openCompetitor(comp) {
      try {
        this.competitorDetail = await this.api(`/api/competitors/${comp.id}`);
        this.competitorProfile = null;
        this.loadCompetitorProfile(comp.id);
      } catch (e) { this.toast('Failed to load competitor: ' + e.message, 'error'); }
    },

    async loadCompetitorProfile(id) {
      try {
        this.competitorProfile = await this.api(`/api/competitors/${id}/profile`);
      } catch (e) { this.competitorProfile = null; }
    },

    async saveCompetitorProfile() {
      if (!this.competitorDetail || !this.competitorProfile) return;
      this.competitorProfileSaving = true;
      try {
        await this.api(`/api/competitors/${this.competitorDetail.id}/profile`, {
          method: 'PUT',
          body: JSON.stringify({
            preferred_scraper: this.competitorProfile.preferred_scraper,
            min_crawl_interval_hours: this.competitorProfile.min_crawl_interval_hours,
            request_delay_ms: this.competitorProfile.request_delay_ms,
            max_pages_per_scan: this.competitorProfile.max_pages_per_scan,
            notes: this.competitorProfile.notes,
          }),
        });
        this.toast('Scraping profile saved', 'success');
      } catch (e) {
        this.toast('Failed to save profile: ' + e.message, 'error');
      } finally {
        this.competitorProfileSaving = false;
      }
    },

    _sortRows(rows, col, dir, accessor) {
      if (!col) return rows;
      return [...rows].sort((a, b) => {
        const av = accessor(a, col), bv = accessor(b, col);
        if (av == null && bv == null) return 0;
        if (av == null) return 1;
        if (bv == null) return -1;
        const cmp = (typeof av === 'number' && typeof bv === 'number')
          ? av - bv
          : String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' });
        return dir === 'asc' ? cmp : -cmp;
      });
    },
    setSort(state, col) {
      if (state.col === col) state.dir = state.dir === 'asc' ? 'desc' : 'asc';
      else { state.col = col; state.dir = 'asc'; }
      if (state === this.productSort) this.loadProducts(1);
    },
    sortIcon(state, col) {
      if (state.col !== col) return '⇅';
      return state.dir === 'asc' ? '↑' : '↓';
    },
    sortedProducts() {
      // Sort is server-side; return current page data as-is
      return this.productData?.products || [];
    },
    sortedCompetitors() {
      const rows = this.competitors?.competitors || [];
      return this._sortRows(rows, this.competitorSort.col, this.competitorSort.dir, (c, col) => {
        if (col === 'domain') return c.domain || '';
        if (col === 'matches') return c.total_matching_products || 0;
        if (col === 'session') return c.scan_session_name || '';
        if (col === 'last_scanned') return c.last_scanned_at || '';
        return '';
      });
    },
    competitorColLabel(col) {
      const labels = { domain: 'Domain', matches: 'Matches', session: 'Session', last_scanned: 'Last Scanned' };
      return labels[col] || col;
    },
    competitorColDrop(toCol) {
      if (!this.competitorDragFrom || this.competitorDragFrom === toCol) { this.competitorDragFrom = null; return; }
      const cols = [...this.competitorCols];
      const fi = cols.indexOf(this.competitorDragFrom);
      const ti = cols.indexOf(toCol);
      if (fi < 0 || ti < 0) { this.competitorDragFrom = null; return; }
      cols.splice(fi, 1);
      cols.splice(ti, 0, this.competitorDragFrom);
      this.competitorCols = cols;
      this.competitorDragFrom = null;
    },

    deleteCompetitor(id) {
      this.competitorSelected = [id];
      this.competitorDeleteExclude = false;
      this.competitorDeleteModal = true;
    },

    toggleCompetitorSelect(id) {
      const idx = this.competitorSelected.indexOf(id);
      if (idx >= 0) this.competitorSelected.splice(idx, 1);
      else this.competitorSelected.push(id);
    },

    isCompetitorSelected(id) {
      return this.competitorSelected.includes(id);
    },

    selectAllCompetitors() {
      const all = (this.competitors?.competitors || []).map(c => c.id);
      this.competitorSelected = this.competitorSelected.length === all.length ? [] : [...all];
    },

    openBulkDeleteModal() {
      this.competitorDeleteExclude = false;
      this.competitorDeleteModal = true;
    },

    async confirmDeleteCompetitors() {
      const ids = [...this.competitorSelected];
      if (!ids.length) return;
      try {
        const r = await this.api('/api/competitors/bulk-delete', {
          method: 'POST',
          body: JSON.stringify({ ids, exclude: this.competitorDeleteExclude }),
        });
        const rm = r?.removed || {};
        const n = ids.length;
        const detail = `matches=${rm.matches || 0}, prices=${rm.price_history || 0}, scans=${rm.scans || 0}`;
        this.toast(`${n} competitor${n !== 1 ? 's' : ''} deleted (${detail})`, 'success');
        this.competitorSelected = [];
        this.competitorDeleteModal = false;
        this.competitorEditId = null;
        this.competitorDetail = null;
        await this.loadCompetitors();
        this.loadStats();
      } catch (e) { this.toast('Failed to delete: ' + e.message, 'error'); }
    },

    startEditCompetitor(c) {
      this.competitorEditId = c.id;
      this.competitorEditForm = { name: c.name || '', base_url: c.base_url || '' };
    },

    cancelEditCompetitor() {
      this.competitorEditId = null;
      this.competitorEditForm = { name: '', base_url: '' };
    },

    async saveCompetitor() {
      try {
        await this.api(`/api/competitors/${this.competitorEditId}`, {
          method: 'PUT',
          body: JSON.stringify(this.competitorEditForm),
        });
        this.toast('Competitor updated', 'success');
        this.competitorEditId = null;
        await this.loadCompetitors();
      } catch (e) { this.toast('Update failed: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Price Comparison Matrix (F26)
    // -----------------------------------------------------------------------
    async loadPriceMatrix(page = 1) {
      this.loadingMatrix = true;
      this.priceMatrixPage = page;
      this.priceMatrixHasSearched = true;
      const f = this.priceMatrixFilters;
      const params = new URLSearchParams({ page, per_page: 25 });
      if (f.search)       params.set('search',       f.search);
      if (f.manufacturer) params.set('manufacturer', f.manufacturer);
      if (f.category)     params.set('category',     f.category);
      if (f.source_site)  params.set('source_site',  f.source_site);
      try {
        this.priceMatrix = await this.api(`/api/price-comparison?${params}`) || { rows: [], competitors: [] };
      } catch (e) { this.toast('Failed to load price matrix: ' + e.message, 'error'); }
      finally { this.loadingMatrix = false; }
    },

    toggleAllPriceMatrix() {
      const rows = this.priceMatrix.rows || [];
      const allSelected = rows.length > 0 && rows.every(r => this.priceMatrixSelected[r.product_id]);
      if (allSelected) {
        rows.forEach(r => { delete this.priceMatrixSelected[r.product_id]; });
      } else {
        rows.forEach(r => { this.priceMatrixSelected[r.product_id] = true; });
      }
      this.priceMatrixSelected = { ...this.priceMatrixSelected };
    },

    priceDiff(ourPrice, theirPrice) {
      if (!ourPrice || !theirPrice) return null;
      return ((theirPrice - ourPrice) / ourPrice * 100).toFixed(1);
    },

    priceDiffClass(diff) {
      if (diff === null) return '';
      return parseFloat(diff) < 0 ? 'text-red-600 font-bold' : 'text-green-600 font-bold';
    },

    // Dollar difference: positive = competitor costs more (green/good), negative = they're cheaper (red/bad)
    priceDiffDollar(ourPrice, theirPrice) {
      if (ourPrice == null || theirPrice == null) return null;
      return theirPrice - ourPrice;
    },

    priceDiffDollarClass(diff) {
      if (diff === null) return 'hidden';
      return diff < 0 ? 'text-red-600 font-bold text-[10px]' : 'text-green-600 font-bold text-[10px]';
    },

    fmtDollarDiff(diff) {
      if (diff === null) return '';
      const abs = Math.abs(diff).toFixed(2);
      return diff >= 0 ? `+$${abs}` : `-$${abs}`;
    },

    // Return matched competitors for a row, sorted by price per the page's
    // current sort direction (default 'asc' = cheapest first).
    matchedCompetitors(row) {
      const by = row?.by_competitor || {};
      const out = [];
      for (const [domain, info] of Object.entries(by)) {
        if (info && info.price != null) {
          out.push({ domain, price: info.price, url: info.url, in_stock: info.in_stock, low_confidence: !!info.low_confidence });
        }
      }
      const dir = this.priceMatrixSortDir === 'desc' ? -1 : 1;
      out.sort((a, b) => (a.price - b.price) * dir);
      return out;
    },

    compShortName(domain) {
      return (domain || '').split('.')[0];
    },

    // -----------------------------------------------------------------------
    // Scheduler (F43-F47)
    // -----------------------------------------------------------------------
    async loadJobs() {
      try {
        const r = await this.api('/api/scheduler/jobs');
        this.jobs = r?.jobs || [];
      } catch {}
    },

    async createJob() {
      try {
        const r = await this.api('/api/scheduler/jobs', {
          method: 'POST', body: JSON.stringify(this.newJob),
        });
        this.toast(`Job "${this.newJob.name}" scheduled (next: ${r.next_run || 'N/A'})`, 'success');
        this.newJob = { name: '', job_type: 'source_scan', target: '', schedule_type: 'daily', schedule_value: '09:00', config_json: '' };
        await this.loadJobs();
      } catch (e) { this.toast('Failed to create job: ' + e.message, 'error'); }
    },

    async deleteJob(id) {
      if (!confirm('Delete this scheduled job?')) return;
      try {
        await this.api(`/api/scheduler/jobs/${id}`, { method: 'DELETE' });
        this.toast('Job deleted', 'success');
        await this.loadJobs();
      } catch (e) { this.toast('Failed to delete job: ' + e.message, 'error'); }
    },

    async runJobNow(id) {
      try {
        await this.api(`/api/scheduler/jobs/${id}/run-now`, { method: 'POST' });
        this.toast('Job queued to run now', 'info');
      } catch (e) { this.toast('Failed to run job: ' + e.message, 'error'); }
    },

    async toggleJob(id, active) {
      try {
        await this.api(`/api/scheduler/jobs/${id}/toggle?active=${active}`, { method: 'PUT' });
        await this.loadJobs();
      } catch (e) { this.toast('Failed to toggle job: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Reports (F61-F63)
    // -----------------------------------------------------------------------
    async loadReport() {
      this.reportFrame = '';
      try {
        let url = '';
        if (this.reportType === 'summary') url = `/api/reports/summary?days=${this.reportParams.days}`;
        else if (this.reportType === 'price_disparity') url = `/api/reports/price-disparity?threshold=${this.reportParams.threshold}`;
        else if (this.reportType === 'competitor' && this.reportParams.competitor_id)
          url = `/api/reports/competitor/${this.reportParams.competitor_id}`;
        else if (this.reportType === 'price_comparison' && this.reportParams.product_id)
          url = `/api/reports/price-comparison/${this.reportParams.product_id}`;
        if (!url) { this.toast('Please fill in required parameters', 'warning'); return; }
        this.reportFrame = await this.api(url);
      } catch (e) { this.toast('Report failed: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Export (F39-F42)
    // -----------------------------------------------------------------------
    async doExport() {
      const fmt = this.exportForm.fmt;
      const params = new URLSearchParams({ fmt });
      if (fmt === 'xlsx') {
        params.set('include_competitors', this.exportForm.include_competitors);
        params.set('include_price_history', this.exportForm.include_price_history);
      }
      try {
        const r = await fetch(`/api/export/products?${params}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const blob = await r.blob();
        const disp = r.headers.get('content-disposition') || '';
        const filename = disp.match(/filename=(.+)/)?.[1] || `export.${fmt}`;
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = filename;
        a.click();
        URL.revokeObjectURL(a.href);
        this.toast(`Exported as ${filename}`, 'success');
        await this.loadExportHistory();
      } catch (e) { this.toast('Export failed: ' + e.message, 'error'); }
    },

    async loadExportHistory() {
      try { this.exportHistory = await this.api('/api/export/history') || { records: [] }; } catch {}
    },

    // -----------------------------------------------------------------------
    // Settings (F56)
    // -----------------------------------------------------------------------
    async loadSettings() {
      try {
        this.settingsData = await this.api('/api/settings') || {};
        this.loadSourceSites();
        // Load webhook settings
        const wh = await this.api('/api/settings/webhook');
        if (wh) {
          this.webhookForm.url = wh.url || '';
          this.webhookForm.events = wh.events || [];
        }
      } catch {}
    },

    async loadManagedLists() {
      try {
        this.managedLists = await this.api('/api/competitors/managed-lists') || { manufacturers: [], excluded: [], competitors: [] };
      } catch {}
    },

    async addManagedUrl(type, raw) {
      const url = (raw || '').trim();
      if (!url) return;
      try {
        await this.api('/api/competitors/bulk-import', {
          method: 'POST',
          body: JSON.stringify({ domains: [url], domain_type: type }),
        });
        this.newManagedUrl[type] = '';
        await this.loadManagedLists();
        this.toast(`Added to ${type} list`, 'success', 2000);
      } catch (e) { this.toast('Failed to add URL: ' + e.message, 'error'); }
    },

    async removeManagedDomain(domain) {
      try {
        await this.api('/api/competitors/by-domain', {
          method: 'DELETE',
          body: JSON.stringify({ domain }),
        });
        await this.loadManagedLists();
        this.toast(`Removed ${domain}`, 'success', 2000);
      } catch (e) { this.toast('Failed to remove: ' + e.message, 'error'); }
    },

    async saveSetting(keys, value) {
      try {
        await this.api('/api/settings', { method: 'PUT', body: JSON.stringify({ keys, value }) });
        this.toast('Setting saved', 'success', 2000);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to save setting: ' + e.message, 'error'); }
    },

    async saveWebhook() {
      try {
        await this.api('/api/settings/webhook', { method: 'PUT', body: JSON.stringify(this.webhookForm) });
        this.toast('Webhook configured', 'success');
      } catch (e) { this.toast('Webhook save failed: ' + e.message, 'error'); }
    },


    // -----------------------------------------------------------------------
    // WebSocket
    // -----------------------------------------------------------------------
    connectWebSocket() {
      if (this.ws && this.ws.readyState === WebSocket.OPEN) return;
      const proto = location.protocol === 'https:' ? 'wss' : 'ws';
      try {
        this.ws = new WebSocket(`${proto}://${location.host}/ws/scan-progress`);
        this.ws.onopen = () => { this.wsConnected = true; clearTimeout(this._wsReconnectTimer); };
        this.ws.onmessage = (evt) => {
          try { this.handleWsMessage(JSON.parse(evt.data)); } catch {}
        };
        this.ws.onclose = () => {
          this.wsConnected = false;
          this._wsReconnectTimer = setTimeout(() => this.connectWebSocket(), 5000);
        };
        this.ws.onerror = () => { this.wsConnected = false; };
      } catch {}
    },

    handleWsMessage(msg) {
      switch (msg.event) {
        case 'log_tail':
          this.logTail = msg.lines || [];
          break;
        case 'site_start':
          this.scanStatus.message = `Scanning ${msg.site}...`; break;
        case 'urls_found':
          this.scanStatus.message = `${msg.site}: found ${msg.count} products`;
          this.scanStatus.total = msg.count; this.scanStatus.current = 0; break;
        case 'product_progress':
          this.scanStatus.current = msg.current; this.scanStatus.total = msg.total;
          this.scanStatus.message = `${msg.site}: scraping ${msg.current}/${msg.total}`; break;
        case 'site_complete':
          this.scanStatus.message = `${msg.site} done — ${msg.new} new, ${msg.updated} updated`; break;
        case 'scan_complete':
          this.scanRunning = false; this.scanStatus = {};
          this.toast('Source scan completed!', 'success');
          this.loadStats(); this.loadProducts(); this.loadScanSessions(); break;
        case 'scan_error':
          this.scanRunning = false; this.scanStatus = {};
          this.toast('Scan error: ' + (msg.error || 'Unknown'), 'error');
          this.loadScanSessions(); break;
        case 'competitor_found':
          this.toast(`Found competitor: ${msg.domain} (${msg.total} total)`, 'info', 2000); break;
        case 'discovery_complete':
          this.discoverRunning = false;
          this.toast(`Discovery done — ${msg.added} new competitors added`, 'success');
          this.loadCompetitors(); this.loadStats(); break;
        case 'competitor_scan_start':
          this.toast(`Scanning ${msg.competitor}...`, 'info', 2000); break;
        case 'competitor_scan_complete':
          this.toast(`${msg.competitor}: ${msg.matches_found} matches found`, 'success');
          this.competitorScanRunning = false;
          this.loadCompetitors(); this.loadStats();
          if (this.currentView === 'pricing') this.loadPriceMatrix(this.priceMatrixPage);
          break;
        case 'competitor_scan_error':
          this.competitorScanRunning = false;
          this.toast(`Competitor scan error: ${msg.error}`, 'error'); break;
        case 'web_search_product_done':
          if (msg.matches_found > 0)
            this.toast(`${msg.product_title?.slice(0,40)}: ${msg.matches_found} match(es) found`, 'success', 2500);
          break;
        case 'web_search_url_attempted':
          this.webSearchUrlLog.push({
            url: msg.url,
            domain: msg.domain,
            status: msg.status,
            product_title: msg.product_title,
            ts: new Date().toLocaleTimeString(),
          });
          this.$nextTick(() => {
            const el = document.getElementById('webSearchUrlLog');
            if (el) el.scrollTop = el.scrollHeight;
          });
          break;
        case 'web_search_scan_checkpoint':
          this.webSearchCheckpoint = {
            total_urls_visited: msg.total_urls_visited,
            total_matches: msg.total_matches,
            session_name: msg.session_name,
          };
          break;
        case 'web_search_scan_complete':
          this.webSearchRunning = false;
          this.webSearchCheckpoint = null;
          this.toast(`Web search scan complete — ${msg.total_matches_in_db} total matches in DB`, 'success');
          this.loadCompetitors(); this.loadStats();
          if (this.currentView === 'pricing') this.loadPriceMatrix(this.priceMatrixPage);
          break;
        case 'web_search_scan_error':
          this.webSearchRunning = false;
          this.webSearchCheckpoint = null;
          this.toast(`Web search scan error: ${msg.error}`, 'error'); break;
        case 'product_comp_search_progress':
          this.productCompProgress = msg;
          if (msg.product_id && this.productCompCounts[msg.product_id]) {
            const entry = this.productCompCounts[msg.product_id];
            if (msg.phase === 'found') {
              entry.found = msg.found;
              entry.current_domain = msg.domain || null;
            } else if (msg.phase === 'visiting') {
              entry.current_domain = msg.current_domain || null;
              entry.searching = true;
            } else if (msg.phase === 'searching') {
              entry.current_domain = null;
              entry.searching = true;
            }
            this.productCompCounts = { ...this.productCompCounts };
          }
          break;
        case 'product_comp_search_product_done':
          if (msg.product_id && this.productCompCounts[msg.product_id]) {
            const entry = this.productCompCounts[msg.product_id];
            entry.found = msg.found;
            entry.done = true;
            entry.searching = false;
            entry.current_domain = null;
            this.productCompCounts = { ...this.productCompCounts };
          }
          break;
        case 'product_comp_search_pause':
          this.productCompPauseState = msg;
          break;
        case 'product_competitor_search_complete':
        case 'product_competitor_search_error':
        case 'parallel_search_complete':
        case 'parallel_search_cancelled':
        case 'parallel_search_error':
          this.productCompRunning = false;
          this.productCompIsParallel = false;
          this.productCompProgress = null;
          this.productCompPauseState = null;
          // Surface a network banner when the search finished with nothing found
          // because the internet was unreachable (vs. genuinely no competitors).
          this.productCompNetworkError = msg.network_ok === false;
          this.loadCompetitors(1);
          this.loadPriceMatrix(1);
          if (msg.event === 'product_competitor_search_error' || msg.event === 'parallel_search_error') {
            this.toast('Competitor search error: ' + (msg.error || 'unknown'), 'error');
            this.productCompMode = false;
          } else if (msg.event === 'parallel_search_cancelled') {
            this.toast('Competitor search cancelled', 'info');
          } else {
            const found = msg.total_found || 0;
            this.toast(`Competitor search complete — ${found} match${found !== 1 ? 'es' : ''} found`, 'success');
          }
          break;
        case 'ai_categorize_complete':
          this.toast(`AI categorized ${msg.categorized}/${msg.total} products`, 'success');
          this.loadProducts(); break;
        case 'crawl_progress':
          if (msg.pages_visited % 10 === 0)
            this.scanStatus.message = `Crawling... ${msg.pages_visited} pages, ${msg.products_found} found`;
          break;
        case 'task_update':
          this.loadTaskList();
          if (msg.task?.name === 'Deduplication' && msg.task?.status === 'complete')
            this.loadCycleStatus();
          if (msg.task?.name?.startsWith('Scan ') && msg.task?.status === 'complete')
            this.loadCycleStatus();
          break;
        case 'cycle_status':
          this.cycleStatus = { ...this.cycleStatus, ...msg };
          if (msg.status === 'complete' || msg.status === 'idle') this.parallelScanRunning = false;
          break;
        case 'parallel_scan_complete':
          this.parallelScanRunning = false;
          this.loadCycleStatus();
          break;
      }
    },

    // -----------------------------------------------------------------------
    // Utilities
    // -----------------------------------------------------------------------
    fmtPrice(v) { return v != null ? `$${Number(v).toFixed(2)}` : '—'; },
    fmtDate(iso) { return iso ? new Date(iso).toLocaleString() : '—'; },
    fmtDateShort(iso) { return iso ? new Date(iso).toLocaleDateString() : '—'; },
    statusColor(s) {
      const m = { completed: 'text-green-500', running: 'text-blue-500', failed: 'text-red-500',
                  pending: 'text-yellow-500', cancelled: 'text-gray-400' };
      return m[s] || 'text-gray-400';
    },
  };
}
