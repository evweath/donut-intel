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

    // Search-engine selection (per page). Populated from GET /api/search/engines.
    // searchEngines: [{key,label,group}] registry. pageEngines: {page:[key,...]}.
    // engineSel: {page: {key: bool}} — which engines are checked on each page.
    searchEngines: [],
    pageEngines: {},
    engineSel: { find_product: {}, beat_price: {}, competitors: {}, products: {} },

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
    productCompMax: 10,
    productCompRunning: false,
    productCompIsParallel: false,           // true when using parallel endpoint (2+ products)
    productCompProgress: null,    // { product_title, found, max, phase, current_domain }
    productCompMode: false,                 // true while search-mode view is active
    productCompSearchProducts: [],          // [{id, title, price, primary_image}] — products being searched
    productCompCounts: {},                  // {product_id: {found, target, done, searching, current_domain}}
    productCompPauseState: null,            // {product_id, product_title, found, visited, max} when paused

    // Shared search-pause prompt (used by every search page). When set, the
    // global pause modal shows. kind routes Continue/Stop to the right handler.
    pausePrompt: null,                      // { kind:'comp'|'beat'|'find', found, max, product_title }
    pauseTimer: null,                       // setInterval handle for the countdown
    pauseRemaining: 0,                      // seconds left before auto-stop
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
    findProductMaxResults: 10,
    findProductUsaOnly: true,        // limit to USA websites (default on)
    findProductTiedToProduct: true,  // search is tied to a catalog product (so "our price" applies)
    findProductResults: [],
    findProductCompResults: [],
    findProductOurPrice: null,       // our catalog price for the searched product (live results)
    findProductLoading: false,
    findProductSearched: false,
    findProductHistory: [],
    findProductHistoryOpen: false,
    fpHistorySort: { col: '', dir: 'asc' },   // sort for the flat find-product history table
    bpHistorySort: { col: '', dir: 'asc' },   // sort for the flat beat-price history table
    fpHistoryLimit: 50,                        // grows by 50 via "Show next 50"
    bpHistoryLimit: 50,
    fpHistorySelected: {},                     // result id -> true (rows ticked for deletion)
    bpHistorySelected: {},
    bpGroupOpen: {},                           // beat-price search id -> expanded? (grouped-by-search overview)
    fpGroupOpen: {},                           // find-product search id -> expanded?
    // Batch-boundary pause state (find 10, ask to continue). Pause only kicks in
    // when the user kept the default target (<=10); a larger target runs straight.
    findProductTarget: 10,
    findProductPauseEnabled: false,
    findProductLastPayload: null,
    findProductSearchId: null,
    findProductAbort: null,
    findProductActiveParams: null,   // {term, engines[], confidence} shown while searching

    // "Confirmed" checkboxes on search-result rows — user ticks one after visiting
    // the link and verifying the product/price matches. Keyed by result URL so the
    // state survives re-renders, sorting, and page switches; persisted to
    // localStorage so it also survives reloads.
    confirmedRows: {},

    // Beat This Price
    beatPriceForm: { description: '', price_min: '', price_max: '', confidence: '', max_results: 10 },
    beatPriceChars: { size: '', color: '', manufacturer: '', country_of_origin: '', features: '' },
    beatPriceResults: [],            // Flat list when free-text only (successful matches)
    beatPricePotential: [],          // Free-text potential matches (match but price off)
    beatPriceGroupedResults: [],     // Per-product groups when products selected
    beatPriceSort: { col: 'price', dir: 'asc' },  // shared sort for results; cheapest-first default
    beatPriceUsaOnly: true,          // limit to USA websites (default on)
    beatPriceTiedToProduct: true,    // search is tied to a catalog product (so "our price" applies)
    beatPriceLoading: false,
    beatPriceProductIds: [],         // IDs of selected master products
    beatPriceCatalogSearch: '',
    beatPriceCatalogResults: [],
    beatPriceProgress: '',           // Status text while running multi-product
    beatPriceHistory: [],
    beatPriceHistoryOpen: false,
    // Batch-boundary pause state (see find-product equivalents above).
    beatPriceTarget: 10,
    beatPricePauseEnabled: false,
    beatPriceLastPayload: null,
    beatPriceSearchId: null,
    beatPriceAbort: null,

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
    competitorPicks: {},   // domain -> true: domains ticked in search results to add as competitors
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
    matchSort: { col: '', dir: 'asc' },
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
    priceMatrixExpanded: {},      // product_id -> bool; absent/true = expanded, false = collapsed
    priceMatrixGroupSort: 'az',   // 'az' | 'za' — alphabetical sort of the product groups
    priceMatrixHasSearched: false,
    loadingMatrix: false,

    // Scheduler
    jobs: [],
    newJob: {
      name: '', job_type: 'source_scan', target: '',
      schedule_type: 'daily', schedule_value: '09:00', config_json: '',
      // Search params (used when job_type is beat_price / find_product)
      search: {
        description: '', query: '', model_number: '', category: '',
        price_min: '', price_max: '', confidence: '', min_fuzzy_score: '',
        max_results: 10, search_competitor_sites: true, product_ids: '', usa_only: true,
      },
      // Email-alert rule fired when results come back matching it
      notify: { enabled: false, max_price: '', min_match: '', min_results: 1, recipients: '' },
    },
    // SMTP / email settings (Scheduler page)
    emailSettings: { enabled: false, smtp_host: '', smtp_port: 587, smtp_use_tls: true,
      smtp_user: '', smtp_password: '', from_address: '', to_addresses: '', smtp_password_set: false },
    emailTestTo: '',

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
    shopifyCredentials: {},    // domain -> { shopify_store_url, shopify_client_id, shopify_client_secret, shopify_access_token, sync_draft, sync_archived }
    shopifyTestStatus: {},     // domain -> 'idle'|'testing'|'ok'|'warn'|'error'
    shopifyTestMessage: {},    // domain -> string
    shopifyConnLog: [],        // recent Shopify connection-attempt log lines
    shopifyConnLogTimer: null, // setInterval handle for polling the connection log
    newSiteForm: { show: false, name: '', shopify_store_url: '', is_destination: false },
    removeSiteConfirm: null,   // domain pending removal confirmation

    // Live Search Log — external product/competitor search activity panel,
    // shown at the top of every page that runs external searches.
    searchLog: [],
    searchLogTimer: null,
    searchLogCollapsed: false,
    // Views that perform external product/competitor searches.
    searchLogViews: ['products', 'competitors', 'pricing', 'find-product', 'beat-price'],

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
        this.loadSearchEngines(),
        this.loadStats(),
        this.loadFilterOptions(),
        this.loadScanSessions(),
        this.loadSettings(),
        this.loadManagedLists(),
        this.loadCompetitors(),
        this.loadJobs(),
        this.loadExportHistory(),
        this.loadConfirmedRows(),
      ]);
      this.loadSourceSites();
      this.startShopifyConnLog();
      this.startSearchLog();
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
    // Product search term — editable, auto-saved on change. All internet
    // searches query this field, so we persist edits immediately (no Save
    // button) and flush any in-flight save before a search runs.
    // -----------------------------------------------------------------------
    _searchTermSaves: [],

    async saveProductSearchTerm(p) {
      if (!p || !p.id) return;
      const value = (p.product_search_term || '').trim();
      const promise = this.api(`/api/products/${p.id}/canonical`, {
        method: 'PUT',
        body: JSON.stringify({ product_search_term: value }),
      })
        .then(() => { this.toast('Search term saved', 'success', 1500); })
        .catch(e => { this.toast('Failed to save search term: ' + e.message, 'error'); });
      this._searchTermSaves.push(promise);
      try { await promise; } finally {
        this._searchTermSaves = this._searchTermSaves.filter(x => x !== promise);
      }
    },

    // Await any pending search-term saves so a search uses the latest text.
    async flushSearchTermSaves() {
      if (this._searchTermSaves.length) {
        await Promise.allSettled(this._searchTermSaves);
      }
    },

    // -----------------------------------------------------------------------
    // Search-engine selection — checkboxes that narrow which engines/shopping
    // sites a page's search algorithm queries. The list is server-driven
    // (/api/search/engines) so it never drifts from what the backend runs.
    // -----------------------------------------------------------------------
    async loadSearchEngines() {
      try {
        const cfg = await this.api('/api/search/engines');
        if (!cfg) return;
        this.searchEngines = cfg.engines || [];
        this.pageEngines = cfg.pages || {};
        // Default: every engine a page uses starts checked (preserves prior behavior).
        for (const page of Object.keys(this.engineSel)) {
          const sel = {};
          for (const key of (this.pageEngines[page] || [])) sel[key] = true;
          this.engineSel[page] = sel;
        }
      } catch (e) {
        // Non-fatal: pages fall back to "all engines" (engines: [] -> backend treats as all).
        console.warn('Failed to load search engines:', e.message);
      }
    },

    // Registry entries (with label/group) for the engines a given page uses.
    enginesForPage(page) {
      const keys = this.pageEngines[page] || [];
      return keys
        .map(k => this.searchEngines.find(e => e.key === k))
        .filter(Boolean);
    },

    toggleEngine(page, key) {
      if (!this.engineSel[page]) this.engineSel[page] = {};
      this.engineSel[page][key] = !this.engineSel[page][key];
    },

    toggleAllEngines(page, value) {
      const sel = {};
      for (const key of (this.pageEngines[page] || [])) sel[key] = value;
      this.engineSel[page] = sel;
    },

    // Keys currently checked on a page — the array sent as `engines` in requests.
    selectedEngines(page) {
      const sel = this.engineSel[page] || {};
      return Object.keys(sel).filter(k => sel[k]);
    },

    anyEngineChecked(page) {
      return this.selectedEngines(page).length > 0;
    },

    // Human-readable labels for the engines currently checked on a page.
    selectedEngineLabels(page) {
      const all = this.enginesForPage(page) || [];
      const labelOf = (k) => (all.find(e => e.key === k) || {}).label || k;
      return this.selectedEngines(page).map(labelOf);
    },

    allEnginesChecked(page) {
      const keys = this.pageEngines[page] || [];
      return keys.length > 0 && keys.every(k => this.engineSel[page]?.[k]);
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

      // Persist any in-flight search-term edits so the scan uses the latest text.
      await this.flushSearchTermSaves();

      const target = Math.max(1, parseInt(this.productCompMax) || 5);

      // Switch to search-mode view showing only the selected products
      this.productCompSearchProducts = (this.productData.products || [])
        .filter(p => ids.includes(p.id))
        .map(p => ({ id: p.id, title: p.title || p.canonical_title, product_search_term: p.product_search_term, price: p.price, primary_image: p.primary_image }));
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
              engines: this.selectedEngines('products'),
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
              engines: this.selectedEngines('products'),
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

    // ---- Shared search-pause prompt (Continue / Stop + 2-min auto-stop) ----
    // PAUSE_SECONDS mirrors the backend PAUSE_TIMEOUT_SECONDS safety timeout.
    showPausePrompt(kind, data) {
      this.pausePrompt = { kind, ...(data || {}) };
      this.pauseRemaining = 120;
      this._clearPauseTimer();
      this.pauseTimer = setInterval(() => {
        this.pauseRemaining -= 1;
        if (this.pauseRemaining <= 0) this.pauseStop();   // no response -> stop & store
      }, 1000);
    },

    _clearPauseTimer() {
      if (this.pauseTimer) { clearInterval(this.pauseTimer); this.pauseTimer = null; }
    },

    pauseCountdownText() {
      const s = Math.max(0, this.pauseRemaining | 0);
      const m = Math.floor(s / 60);
      return m + ':' + String(s % 60).padStart(2, '0');
    },

    pauseContinue() {
      const kind = this.pausePrompt?.kind;
      this._clearPauseTimer();
      this.pausePrompt = null;
      if (kind === 'comp') this.resumeCompSearch();
      else if (kind === 'beat') this.continueBeatPrice();
      else if (kind === 'find') this.continueFindProduct();
    },

    pauseStop() {
      const kind = this.pausePrompt?.kind;
      this._clearPauseTimer();
      this.pausePrompt = null;
      if (kind === 'comp') this.stopCompSearch();
      else if (kind === 'beat') this.stopBeatPrice();
      else if (kind === 'find') this.stopFindProduct();
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
      if (this.findProductTiedToProduct && !this.findProductIds.length) {
        this.toast('Select one or more products from the catalog, or uncheck "This search is tied to a product in our store".', 'info');
        return;
      }
      if (!this.findProductQuery && !this.findProductIds.length) {
        this.toast('Enter a query or select products from the catalog', 'info');
        return;
      }
      // Persist any in-flight search-term edits so the search uses the latest text.
      await this.flushSearchTermSaves();
      this.findProductLoading = true;
      this.findProductSearched = false;
      this.findProductResults = [];
      this.findProductCompResults = [];
      const target = this.findProductMaxResults;
      const payload = {
        product_ids: this.findProductIds.length ? this.findProductIds : null,
        query: this.findProductQuery || null,
        model_number: this.findProductModelNumber || null,
        category: this.findProductCategory || null,
        max_results: target,
        min_fuzzy_score: this.findProductMinFuzzyScore || 0,
        search_competitor_sites: true,
        engines: this.selectedEngines('find_product'),
        usa_only: this.findProductUsaOnly,
      };
      this.findProductLastPayload = payload;
      // Snapshot the search parameters shown in the "Searching..." window.
      this.findProductActiveParams = {
        term: this.findProductQuery
          ? this.findProductQuery
          : (this.findProductIds.length + ' selected product' + (this.findProductIds.length !== 1 ? 's' : '')),
        engines: this.selectedEngineLabels('find_product'),
        confidence: this.findProductMinFuzzyScore || 0,
      };
      this.findProductTarget = target;
      this.findProductPauseEnabled = target <= 10;
      this.findProductSearchId = null;
      this.findProductAbort = new AbortController();
      try {
        const res = await this.api('/api/search/find-product', {
          method: 'POST', body: JSON.stringify(payload), signal: this.findProductAbort.signal,
        });
        this.findProductSearchId = res?.search_id || null;
        this.findProductOurPrice = res?.our_price ?? null;
        this.findProductResults = res?.results || [];
        this.findProductCompResults = res?.competitor_results || [];
        await this.loadFindProductHistory();
        this._maybePauseFindProduct();
      } catch (e) {
        if (e.name !== 'AbortError') this.toast('Search failed: ' + e.message, 'error');
      }
      finally { this.findProductLoading = false; this.findProductSearched = true; this.findProductAbort = null; }
    },

    // Distinct web competitor domains found so far.
    findProductDomains() {
      const set = new Set();
      (this.findProductResults || []).forEach(r => r.domain && set.add(r.domain));
      return set;
    },

    _maybePauseFindProduct() {
      const found = this.findProductDomains().size;
      if (this.findProductPauseEnabled && this.findProductSearchId && found >= this.findProductTarget) {
        this.showPausePrompt('find', { found });
      }
    },

    async continueFindProduct() {
      if (!this.findProductSearchId || !this.findProductLastPayload) return;
      this.findProductTarget += 10;
      this.findProductLoading = true;
      this.findProductAbort = new AbortController();
      const exclude = [...this.findProductDomains()];
      try {
        const res = await this.api('/api/search/find-product/continue', {
          method: 'POST', signal: this.findProductAbort.signal,
          body: JSON.stringify({ ...this.findProductLastPayload, search_id: this.findProductSearchId, exclude_domains: exclude }),
        });
        this.findProductResults = [...this.findProductResults, ...(res?.results || [])];
        await this.loadFindProductHistory();
        this._maybePauseFindProduct();
      } catch (e) {
        if (e.name !== 'AbortError') this.toast('Continue failed: ' + e.message, 'error');
      } finally { this.findProductLoading = false; this.findProductAbort = null; }
    },

    stopFindProduct() {
      if (this.findProductAbort) { try { this.findProductAbort.abort(); } catch {} }
      this.findProductLoading = false;
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
      this.beatPricePotential = [];
      this.beatPriceGroupedResults = [];
      this.beatPriceForm = { description: '', price_min: '', price_max: '', confidence: '', max_results: 10 };
      this.beatPriceChars = {};
      this.beatPriceCatalogSearch = '';
      this.beatPriceCatalogResults = [];
    },

    async runBeatPrice() {
      const hasProducts = this.beatPriceProductIds.length > 0;
      const hasDescription = !!(this.beatPriceForm.description || '').trim();
      if (this.beatPriceTiedToProduct && !hasProducts) {
        this.toast('Select one or more products from "Browse Our Products", or uncheck "This search is tied to a product in our store".', 'info');
        return;
      }
      if (!hasProducts && !hasDescription) {
        this.toast('Select at least one product or enter a description', 'info');
        return;
      }
      // Persist any in-flight search-term edits so the search uses the latest text.
      await this.flushSearchTermSaves();

      this.beatPriceLoading = true;
      this.beatPriceResults = [];
      this.beatPricePotential = [];
      this.beatPriceGroupedResults = [];
      this.beatPriceProgress = hasProducts ? `Searching ${this.beatPriceProductIds.length} product(s)...` : '';

      const chars = Object.fromEntries(Object.entries(this.beatPriceChars).filter(([, v]) => v));
      const target = this.beatPriceForm.max_results || 10;
      const payload = {
        description: this.beatPriceForm.description || null,
        product_ids: hasProducts ? this.beatPriceProductIds : null,
        price_min: this.beatPriceForm.price_min ? parseFloat(this.beatPriceForm.price_min) : null,
        price_max: this.beatPriceForm.price_max ? parseFloat(this.beatPriceForm.price_max) : null,
        min_confidence: this.beatPriceForm.confidence !== '' && this.beatPriceForm.confidence != null
          ? parseFloat(this.beatPriceForm.confidence) : null,
        characteristics: Object.keys(chars).length ? chars : null,
        max_results: target,
        engines: this.selectedEngines('beat_price'),
        usa_only: this.beatPriceUsaOnly,
      };
      this.beatPriceLastPayload = payload;
      this.beatPriceTarget = target;
      this.beatPricePauseEnabled = target <= 10;  // default-target safety net only
      this.beatPriceSearchId = null;
      this.beatPriceAbort = new AbortController();

      try {
        const res = await this.api('/api/search/beat-price', {
          method: 'POST', body: JSON.stringify(payload), signal: this.beatPriceAbort.signal,
        });
        this.beatPriceSearchId = res?.search_id || null;
        const stamp = this._beatRunStamp(payload);
        this.beatPriceResults = this._tagBeatResults(res?.results || [], stamp);
        this.beatPricePotential = this._tagBeatResults(res?.potential || [], stamp);
        this.beatPriceGroupedResults = (res?.groups || []).map(g =>
          ({ ...g, results: this._tagBeatResults(g.results || [], stamp),
             potential: this._tagBeatResults(g.potential || [], stamp) }));
        const total = this.beatPriceTotalResults();
        const pot = this.beatPricePotentialTotal();
        if (!total && !pot) this.toast('No matches found — try broadening the description or price', 'info');
        else this.toast(`${total} successful match${total !== 1 ? 'es' : ''}` +
          (pot ? `, ${pot} potential` : ''), 'success');
        this._maybePauseBeatPrice();
      } catch (e) {
        if (e.name !== 'AbortError') this.toast('Search failed: ' + e.message, 'error');
      } finally {
        this.beatPriceLoading = false;
        this.beatPriceProgress = '';
        this.beatPriceAbort = null;
        await this.loadBeatPriceHistory();
      }
    },

    // Distinct competitor domains found so far across flat + grouped results.
    beatPriceDomains() {
      const set = new Set();
      (this.beatPriceResults || []).forEach(r => r.domain && set.add(r.domain));
      (this.beatPriceGroupedResults || []).forEach(g =>
        (g.results || []).forEach(r => r.domain && set.add(r.domain)));
      return set;
    },

    // Successful matches (match% >= floor AND price within limit) across both views.
    beatPriceTotalResults() {
      return (this.beatPriceResults || []).length +
        (this.beatPriceGroupedResults || []).reduce((n, g) => n + (g.results?.length || 0), 0);
    },

    // Potential matches (match the product but price is outside the limit / unknown).
    beatPricePotentialTotal() {
      return (this.beatPricePotential || []).length +
        (this.beatPriceGroupedResults || []).reduce((n, g) => n + (g.potential?.length || 0), 0);
    },

    // If we hit the target number of SUCCESSFUL matches and pausing is on, ask
    // whether to keep going — and show both successful + potential counts.
    _maybePauseBeatPrice() {
      const successful = this.beatPriceTotalResults();
      if (this.beatPricePauseEnabled && this.beatPriceSearchId && successful >= this.beatPriceTarget) {
        this.showPausePrompt('beat', { found: successful, successful, potential: this.beatPricePotentialTotal() });
      }
    },

    // "Continue" — fetch ~10 more competitors, excluding those already shown,
    // and append them to the same saved search.
    async continueBeatPrice() {
      if (!this.beatPriceSearchId || !this.beatPriceLastPayload) return;
      this.beatPriceTarget += 10;
      this.beatPriceLoading = true;
      this.beatPriceProgress = 'Searching for more competitors...';
      this.beatPriceAbort = new AbortController();
      const exclude = [...this.beatPriceDomains()];
      try {
        const res = await this.api('/api/search/beat-price/continue', {
          method: 'POST', signal: this.beatPriceAbort.signal,
          body: JSON.stringify({ ...this.beatPriceLastPayload, search_id: this.beatPriceSearchId, exclude_domains: exclude }),
        });
        const stamp = this._beatRunStamp(this.beatPriceLastPayload);
        this.beatPriceResults = [...this.beatPriceResults, ...this._tagBeatResults(res?.results || [], stamp)];
        this.beatPricePotential = [...this.beatPricePotential, ...this._tagBeatResults(res?.potential || [], stamp)];
        this._mergeBeatGroups((res?.groups || []).map(g =>
          ({ ...g, results: this._tagBeatResults(g.results || [], stamp),
             potential: this._tagBeatResults(g.potential || [], stamp) })));
        this._maybePauseBeatPrice();   // ask again at the next 10
      } catch (e) {
        if (e.name !== 'AbortError') this.toast('Continue failed: ' + e.message, 'error');
      } finally {
        this.beatPriceLoading = false;
        this.beatPriceProgress = '';
        this.beatPriceAbort = null;
        await this.loadBeatPriceHistory();
      }
    },

    _mergeBeatGroups(newGroups) {
      for (const ng of newGroups) {
        const g = this.beatPriceGroupedResults.find(x => x.product_id === ng.product_id);
        if (g) {
          g.results = [...(g.results || []), ...(ng.results || [])];
          g.potential = [...(g.potential || []), ...(ng.potential || [])];
        } else this.beatPriceGroupedResults.push(ng);
      }
      this.beatPriceGroupedResults = [...this.beatPriceGroupedResults];
    },

    // "Stop" — keep whatever has been found (already saved server-side).
    stopBeatPrice() {
      if (this.beatPriceAbort) { try { this.beatPriceAbort.abort(); } catch {} }
      this.beatPriceLoading = false;
      this.beatPriceProgress = '';
    },

    async loadBeatPriceHistory() {
      try {
        const res = await this.api('/api/search/beat-price/history?limit=20');
        this.beatPriceHistory = res?.searches || [];
      } catch {}
    },

    // Build a {ts, params} stamp describing the search that produced a result
    // batch, so each result line can show when it was run and with what params.
    _beatRunStamp(payload) {
      const p = payload || {};
      const parts = [];
      if (p.description) parts.push(`"${p.description}"`);
      if (p.price_min != null) parts.push(`min $${p.price_min}`);
      if (p.price_max != null) parts.push(`max $${p.price_max}`);
      if (p.min_confidence != null) parts.push(`conf ≥ ${p.min_confidence}%`);
      return { ts: new Date().toLocaleString(), params: parts.join(' · ') || '—' };
    },
    // Attach the run stamp to each result row (kept on the row so it survives
    // sorting and "continue" appends).
    _tagBeatResults(rows, stamp) {
      return (rows || []).map(r => ({ ...r, _ts: stamp.ts, _params: stamp.params }));
    },
    // Sort a result list using the shared sort helper. Default cheapest-first.
    // Sortable columns: price, confidence (fuzzy_score), vendor (domain).
    sortedBeatResults(rows) {
      return this._sortRows(rows || [], this.beatPriceSort.col, this.beatPriceSort.dir, (r, col) => {
        if (col === 'price') return r.price != null ? Number(r.price) : null;
        if (col === 'confidence') return r.fuzzy_score != null ? Number(r.fuzzy_score) : null;
        if (col === 'vendor') return r.domain || '';
        return '';
      });
    },
    setBeatSort(col) { this.setSort(this.beatPriceSort, col); },

    // History list excluding searches that returned 0 results.
    beatPriceHistoryVisible() {
      return (this.beatPriceHistory || []).filter(s => (s.results?.length || 0) > 0);
    },

    // Find-Product history, excluding searches that returned 0 results.
    findProductHistoryVisible() {
      return (this.findProductHistory || []).filter(s => (s.results?.length || 0) > 0);
    },

    // Max result lines shown across the whole (flattened) search history.
    HISTORY_ROW_LIMIT: 50,

    // Shared accessor for sorting history result lines by the columns shown:
    // searched date, vendor (domain), match % (fuzzy_score), our price, competitor price.
    _historyResultVal(r, col) {
      if (col === 'date') return r._searched_at ? (Date.parse(r._searched_at) || null) : null;
      if (col === 'vendor') return r.domain || r.title || '';
      if (col === 'match') return r.fuzzy_score != null ? Number(r.fuzzy_score) : null;
      if (col === 'our') return r.our_price != null ? Number(r.our_price) : null;
      if (col === 'price') return r.price != null ? Number(r.price) : null;
      return '';
    },
    // Flatten every result line across all (non-empty) searches into one list,
    // tagged with its search's query + timestamp. Keep only the most-recent
    // `limit` lines, then apply the user's chosen column sort.
    // Default (no column chosen) = newest-first.
    historyFlatRows(searches, sortState, limit) {
      const rows = [];
      for (const s of (searches || [])) {
        const query = s.query ?? s.description ?? '';
        for (const r of (s.results || [])) {
          rows.push({ ...r, _query: query, _searched_at: s.searched_at });
        }
      }
      // Newest first (by search time, then result id), then cap to the limit.
      rows.sort((a, b) =>
        ((Date.parse(b._searched_at) || 0) - (Date.parse(a._searched_at) || 0)) ||
        ((b.id || 0) - (a.id || 0)));
      const pool = rows.slice(0, limit || this.HISTORY_ROW_LIMIT);
      if (!sortState.col) return pool;
      return this._sortRows(pool, sortState.col, sortState.dir,
        (r, col) => this._historyResultVal(r, col));
    },
    // Total result lines available across the visible history (for "showing X of Y").
    historyTotalRows(searches) {
      return (searches || []).reduce((n, s) => n + (s.results?.length || 0), 0);
    },

    // --- "Grouped by search" overview (collapsible per search) ----------------
    // Shared by the Find-Product and Beat-Price history sections.
    // Human label for a search group: the free-text query the user typed
    // (Find-Product uses `query`, Beat-Price uses `description`), else the
    // selected catalog products' search terms (what a catalog search actually
    // queried), else a summary of any other search params.
    historyGroupLabel(s) {
      const text = ((s?.query ?? s?.description) || '').trim();
      if (text) return text;
      const terms = (s?.product_search_terms || []).filter(Boolean);
      if (terms.length) return terms.join(' · ');
      const parts = [];
      if (s?.model_number) parts.push(s.model_number);
      if (s?.category) parts.push(s.category);
      if (parts.length) return parts.join(' · ');
      return 'Catalog products (no search text)';
    },
    // Toggle a group's expanded state. `openMap` is the page's reactive map
    // (bpGroupOpen / fpGroupOpen); mutating it in place keeps Alpine reactive.
    toggleHistoryGroup(openMap, id) { openMap[id] = !openMap[id]; },

    async deleteFindProductResult(resultId) {
      try {
        await this.api(`/api/search/find-product/result/${resultId}`, { method: 'DELETE' });
        await this.loadFindProductHistory();
      } catch (e) { this.toast('Delete failed: ' + e.message, 'error'); }
    },
    async deleteBeatPriceResult(resultId) {
      try {
        await this.api(`/api/search/beat-price/result/${resultId}`, { method: 'DELETE' });
        await this.loadBeatPriceHistory();
      } catch (e) { this.toast('Delete failed: ' + e.message, 'error'); }
    },

    // --- Bulk selection + deletion for the search-history tables --------------
    historyAllSelected(rows, selMap) {
      return rows.length > 0 && rows.every(r => selMap[r.id]);
    },
    historyToggleAll(rows, selMap, value) {
      rows.forEach(r => { if (value) selMap[r.id] = true; else delete selMap[r.id]; });
    },
    historySelectedCount(selMap) {
      return Object.keys(selMap).filter(k => selMap[k]).length;
    },
    // kind: 'fp' (find-product) or 'bp' (beat-price)
    async deleteSelectedHistory(kind) {
      const selMap = kind === 'fp' ? this.fpHistorySelected : this.bpHistorySelected;
      const ids = Object.keys(selMap).filter(k => selMap[k]).map(Number);
      if (!ids.length) return;
      if (!confirm(`Delete ${ids.length} selected result line${ids.length !== 1 ? 's' : ''}?`)) return;
      const base = kind === 'fp'
        ? '/api/search/find-product/result/'
        : '/api/search/beat-price/result/';
      try {
        await Promise.all(ids.map(id => this.api(base + id, { method: 'DELETE' })));
      } catch (e) {
        this.toast('Delete failed: ' + e.message, 'error');
      }
      if (kind === 'fp') { this.fpHistorySelected = {}; await this.loadFindProductHistory(); }
      else { this.bpHistorySelected = {}; await this.loadBeatPriceHistory(); }
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
        const s = this.competitorSort;
        const sortQ = s.col ? `&sort=${encodeURIComponent(s.col)}&dir=${s.dir}` : '';
        this.competitors = await this.api(`/api/competitors?page=${page}&per_page=50${sortQ}`) || { competitors: [], total: 0 };
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

    // --- Add competitor domains straight from search-result rows --------------
    // Every screen that lists competitor-product domains renders a checkbox
    // bound to competitorPicks[domain]; the floating bar adds the ticked ones.
    togglePick(domain, checked) {
      if (!domain) return;
      if (checked) this.competitorPicks[domain] = true;
      else delete this.competitorPicks[domain];
    },
    competitorPickCount() {
      return Object.keys(this.competitorPicks).filter(k => this.competitorPicks[k]).length;
    },
    clearCompetitorPicks() { this.competitorPicks = {}; },
    async addPickedCompetitors() {
      const domains = Object.keys(this.competitorPicks).filter(k => this.competitorPicks[k]);
      if (!domains.length) return;
      try {
        const r = await this.api('/api/competitors/bulk-import', {
          method: 'POST',
          body: JSON.stringify({ domains, domain_type: 'competitor' }),
        });
        const parts = [];
        if (r.added) parts.push(`${r.added} added`);
        if (r.updated) parts.push(`${r.updated} updated`);
        if (r.skipped_as_source && r.skipped_as_source.length)
          parts.push(`${r.skipped_as_source.length} skipped (your own site)`);
        this.toast(`Competitors: ${parts.join(', ') || 'no changes (already tracked)'}`, 'success');
        this.competitorPicks = {};
        await this.loadCompetitors();
      } catch (e) { this.toast('Add competitors failed: ' + e.message, 'error'); }
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
          body: JSON.stringify({ max_results: n, product_limit: limit || null, engines: this.selectedEngines('competitors') }),
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
      if (state === this.competitorSort) this.loadCompetitors(1);
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
      // Sort is server-side (applied across all pages); return current page data as-is.
      return this.competitors?.competitors || [];
    },
    sortedMatches() {
      const rows = (this.competitorDetail && this.competitorDetail.matches) || [];
      return this._sortRows(rows, this.matchSort.col, this.matchSort.dir, (m, col) => {
        if (col === 'title') return m.master_title || m.title || '';
        if (col === 'manufacturer') return m.master_manufacturer || '';
        if (col === 'price') return m.price != null ? Number(m.price) : null;
        if (col === 'confidence') return m.confidence != null ? Number(m.confidence) : null;
        if (col === 'variance') {
          if (m.price == null || m.our_price == null || !m.our_price) return null;
          return (Number(m.price) - Number(m.our_price)) / Number(m.our_price);
        }
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

    // Single-competitor delete — no confirmation popup (per product spec).
    deleteCompetitor(id) {
      this._runDeleteCompetitors([id], false);
    },

    toggleCompetitorSelect(id) {
      const idx = this.competitorSelected.indexOf(id);
      if (idx >= 0) this.competitorSelected.splice(idx, 1);
      else this.competitorSelected.push(id);
    },

    isCompetitorSelected(id) {
      return this.competitorSelected.includes(id);
    },

    // Selection persists across pages (competitorSelected is never reset on page
    // load), so these helpers reason about the CURRENT page only.
    allCurrentPageSelected() {
      const all = (this.competitors?.competitors || []).map(c => c.id);
      return all.length > 0 && all.every(id => this.competitorSelected.includes(id));
    },

    someCurrentPageSelected() {
      const all = (this.competitors?.competitors || []).map(c => c.id);
      return all.some(id => this.competitorSelected.includes(id)) && !this.allCurrentPageSelected();
    },

    selectAllCompetitors() {
      const all = (this.competitors?.competitors || []).map(c => c.id);
      if (this.allCurrentPageSelected()) {
        // Deselect just this page; keep selections made on other pages.
        this.competitorSelected = this.competitorSelected.filter(id => !all.includes(id));
      } else {
        const set = new Set(this.competitorSelected);
        all.forEach(id => set.add(id));
        this.competitorSelected = [...set];
      }
    },

    // Toolbar "Delete Selected": confirm only when 2+ are selected.
    requestBulkDelete() {
      const n = this.competitorSelected.length;
      if (!n) return;
      if (n === 1) {
        this._runDeleteCompetitors([...this.competitorSelected], this.competitorDeleteExclude);
        return;
      }
      this.competitorDeleteExclude = false;
      this.competitorDeleteModal = true;
    },

    // "No" in the bulk-delete popup — close it but keep the current selection
    // (and current page) intact so the user can adjust their choice.
    cancelBulkDelete() {
      this.competitorDeleteModal = false;
    },

    // "Yes" in the bulk-delete popup.
    async confirmDeleteCompetitors() {
      this.competitorDeleteModal = false;
      await this._runDeleteCompetitors([...this.competitorSelected], this.competitorDeleteExclude);
    },

    async _runDeleteCompetitors(ids, exclude) {
      if (!ids.length) return;
      try {
        const r = await this.api('/api/competitors/bulk-delete', {
          method: 'POST',
          body: JSON.stringify({ ids, exclude: !!exclude }),
        });
        const rm = r?.removed || {};
        const n = ids.length;
        const detail = `matches=${rm.matches || 0}, prices=${rm.price_history || 0}, scans=${rm.scans || 0}`;
        this.toast(`${n} competitor${n !== 1 ? 's' : ''} deleted (${detail})`, 'success');
        // Drop only the deleted IDs from the selection; keep any others checked.
        this.competitorSelected = this.competitorSelected.filter(id => !ids.includes(id));
        this.competitorEditId = null;
        this.competitorDetail = null;
        // Stay on the current page rather than reverting to page 1.
        await this.loadCompetitors(this.competitorPage);
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

    // ---- Price-matrix accordion: collapse/expand + alphabetical group sort ----
    // A group is expanded unless explicitly set to false, so groups start open.
    isGroupExpanded(pid) {
      return this.priceMatrixExpanded[pid] !== false;
    },

    togglePriceMatrixGroup(pid) {
      const cur = this.priceMatrixExpanded[pid] !== false;
      this.priceMatrixExpanded = { ...this.priceMatrixExpanded, [pid]: !cur };
    },

    expandAllGroups() {
      const e = { ...this.priceMatrixExpanded };
      (this.priceMatrix.rows || []).forEach(r => { e[r.product_id] = true; });
      this.priceMatrixExpanded = e;
    },

    collapseAllGroups() {
      const e = { ...this.priceMatrixExpanded };
      (this.priceMatrix.rows || []).forEach(r => { e[r.product_id] = false; });
      this.priceMatrixExpanded = e;
    },

    // Product groups ordered alphabetically by name (A→Z or Z→A).
    sortedMatrixRows() {
      const rows = [...(this.priceMatrix.rows || [])];
      const dir = this.priceMatrixGroupSort === 'za' ? -1 : 1;
      rows.sort((a, b) =>
        (a.title || '').localeCompare(b.title || '', undefined, { sensitivity: 'base' }) * dir);
      return rows;
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

    // Default newJob shape — reused on reset.
    _blankJob() {
      return {
        name: '', job_type: 'source_scan', target: '', schedule_type: 'daily',
        schedule_value: '09:00', config_json: '',
        search: { description: '', query: '', model_number: '', category: '',
          price_min: '', price_max: '', confidence: '', min_fuzzy_score: '',
          max_results: 10, search_competitor_sites: true, product_ids: '', usa_only: true },
        notify: { enabled: false, max_price: '', min_match: '', min_results: 1, recipients: '' },
      };
    },

    // True for the two search job types that carry search params + notify rules.
    isSearchJob() {
      return this.newJob.job_type === 'beat_price' || this.newJob.job_type === 'find_product';
    },

    // Build the request payload, packing search + notify into config_json for
    // beat_price / find_product jobs.
    _buildJobPayload() {
      const j = this.newJob;
      const num = v => (v === '' || v == null) ? null : Number(v);
      const ids = (j.search.product_ids || '').split(',').map(s => s.trim()).filter(Boolean).map(Number);
      const recipients = (j.notify.recipients || '').split(/[,\n;]/).map(s => s.trim()).filter(Boolean);
      const base = { name: j.name, job_type: j.job_type, target: j.target || null,
        schedule_type: j.schedule_type, schedule_value: j.schedule_value };
      if (!this.isSearchJob()) return { ...base, config_json: j.config_json || null };

      let search;
      if (j.job_type === 'beat_price') {
        search = { description: j.search.description || null, product_ids: ids.length ? ids : null,
          price_min: num(j.search.price_min), price_max: num(j.search.price_max),
          min_confidence: num(j.search.confidence), max_results: Number(j.search.max_results) || 10,
          usa_only: !!j.search.usa_only };
      } else {
        search = { query: j.search.query || null, product_ids: ids.length ? ids : null,
          model_number: j.search.model_number || null, category: j.search.category || null,
          min_fuzzy_score: Number(j.search.min_fuzzy_score) || 0,
          search_competitor_sites: !!j.search.search_competitor_sites,
          max_results: Number(j.search.max_results) || 10, usa_only: !!j.search.usa_only };
      }
      const notify = { enabled: !!j.notify.enabled, max_price: num(j.notify.max_price),
        min_match: num(j.notify.min_match), min_results: Number(j.notify.min_results) || 1,
        recipients };
      return { ...base, config_json: JSON.stringify({ search, notify }) };
    },

    async createJob() {
      try {
        const payload = this._buildJobPayload();
        const r = await this.api('/api/scheduler/jobs', {
          method: 'POST', body: JSON.stringify(payload),
        });
        this.toast(`Job "${this.newJob.name}" scheduled (next: ${r.next_run || 'N/A'})`, 'success');
        this.newJob = this._blankJob();
        await this.loadJobs();
      } catch (e) { this.toast('Failed to create job: ' + e.message, 'error'); }
    },

    // ---- Email / SMTP settings (Scheduler page) ----
    async loadEmailSettings() {
      try {
        const s = await this.api('/api/settings/email');
        this.emailSettings = { ...this.emailSettings, ...s,
          to_addresses: Array.isArray(s.to_addresses) ? s.to_addresses.join(', ') : (s.to_addresses || ''),
          smtp_password: '' };
      } catch {}
    },
    async saveEmailSettings() {
      try {
        const e = this.emailSettings;
        const body = {
          enabled: !!e.enabled, smtp_host: e.smtp_host || '', smtp_port: Number(e.smtp_port) || 587,
          smtp_use_tls: !!e.smtp_use_tls, smtp_user: e.smtp_user || '', from_address: e.from_address || '',
          to_addresses: (e.to_addresses || '').split(/[,\n;]/).map(s => s.trim()).filter(Boolean),
          smtp_password: e.smtp_password || null,
        };
        await this.api('/api/settings/email', { method: 'PUT', body: JSON.stringify(body) });
        this.toast('Email settings saved', 'success');
        await this.loadEmailSettings();
      } catch (err) { this.toast('Failed to save email settings: ' + err.message, 'error'); }
    },
    async sendTestEmail() {
      try {
        const recipients = (this.emailTestTo || '').split(/[,\n;]/).map(s => s.trim()).filter(Boolean);
        const r = await this.api('/api/notify/test', { method: 'POST',
          body: JSON.stringify({ recipients: recipients.length ? recipients : null }) });
        this.toast(r.ok ? 'Test email sent ✓' : ('Test failed: ' + r.detail), r.ok ? 'success' : 'error');
      } catch (e) { this.toast('Test failed: ' + e.message, 'error'); }
    },

    // ---- "Schedule this search" from the Beat Price / Find Product pages ----
    scheduleBeatPriceSearch() {
      if (this.beatPriceTiedToProduct && !this.beatPriceProductIds.length) {
        this.toast('Select one or more products from "Browse Our Products", or uncheck "This search is tied to a product in our store".', 'info');
        return;
      }
      const j = this._blankJob();
      j.job_type = 'beat_price';
      j.name = 'Beat price: ' + ((this.beatPriceForm.description || '').slice(0, 40) || 'catalog');
      j.search.description = this.beatPriceForm.description || '';
      j.search.price_min = this.beatPriceForm.price_min || '';
      j.search.price_max = this.beatPriceForm.price_max || '';
      j.search.confidence = this.beatPriceForm.confidence || '';
      j.search.max_results = this.beatPriceForm.max_results || 10;
      j.search.product_ids = (this.beatPriceProductIds || []).join(', ');
      j.search.usa_only = this.beatPriceUsaOnly;
      this.newJob = j;
      this.currentView = 'scheduler';
      this.loadJobs(); this.loadEmailSettings();
      this.toast('Search loaded into the scheduler — set a schedule and (optionally) an alert.', 'info');
    },
    scheduleFindProductSearch() {
      if (this.findProductTiedToProduct && !this.findProductIds.length) {
        this.toast('Select one or more products from the catalog, or uncheck "This search is tied to a product in our store".', 'info');
        return;
      }
      const j = this._blankJob();
      j.job_type = 'find_product';
      j.name = 'Find product: ' + ((this.findProductQuery || '').slice(0, 40) || 'catalog');
      j.search.query = this.findProductQuery || '';
      j.search.model_number = this.findProductModelNumber || '';
      j.search.category = this.findProductCategory || '';
      j.search.min_fuzzy_score = this.findProductMinFuzzyScore || '';
      j.search.max_results = this.findProductMaxResults || 10;
      j.search.product_ids = (this.findProductIds || []).join(', ');
      j.search.usa_only = this.findProductUsaOnly;
      this.newJob = j;
      this.currentView = 'scheduler';
      this.loadJobs(); this.loadEmailSettings();
      this.toast('Search loaded into the scheduler — set a schedule and (optionally) an alert.', 'info');
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
        // Populate Shopify credential forms from saved settings
        const creds = {};
        for (const site of (this.settingsData.source_sites || [])) {
          creds[site.domain] = {
            shopify_store_url: site.shopify_store_url || '',
            shopify_client_id: site.shopify_client_id || site.shopify_api_key || '',
            shopify_client_secret: site.shopify_client_secret || '',
            shopify_access_token: site.shopify_access_token || '',
            sync_draft: site.sync_draft || false,
            sync_archived: site.sync_archived || false,
          };
        }
        this.shopifyCredentials = creds;
        // Load webhook settings
        const wh = await this.api('/api/settings/webhook');
        if (wh) {
          this.webhookForm.url = wh.url || '';
          this.webhookForm.events = wh.events || [];
        }
      } catch {}
    },

    // -----------------------------------------------------------------------
    // Shopify connection log + source-site credentials
    // -----------------------------------------------------------------------
    async loadShopifyConnLog() {
      try {
        const r = await this.api('/api/shopify/connection-log?n=150');
        const box = document.getElementById('shopifyConnLogBox');
        const atBottom = box ? (box.scrollHeight - box.scrollTop - box.clientHeight < 24) : true;
        this.shopifyConnLog = (r && r.lines) || [];
        // Keep the view pinned to the newest line unless the user scrolled up.
        if (atBottom) this.$nextTick(() => { const b = document.getElementById('shopifyConnLogBox'); if (b) b.scrollTop = b.scrollHeight; });
      } catch (e) { /* panel is best-effort; ignore transient errors */ }
    },

    startShopifyConnLog() {
      this.loadShopifyConnLog();
      if (this.shopifyConnLogTimer) return;
      this.shopifyConnLogTimer = setInterval(() => {
        if (this.currentView === 'settings') this.loadShopifyConnLog();
      }, 3000);
    },

    async clearShopifyConnLog() {
      try { await this.api('/api/shopify/connection-log/clear', { method: 'POST' }); } catch (e) {}
      this.shopifyConnLog = [];
    },

    // -----------------------------------------------------------------------
    // Live Search Log (external product/competitor search activity)
    // -----------------------------------------------------------------------
    onSearchLogPage() {
      return this.searchLogViews.includes(this.currentView);
    },

    async loadSearchLog() {
      try {
        const r = await this.api('/api/search-log?n=200');
        const box = document.getElementById('searchLogBox');
        const atBottom = box ? (box.scrollHeight - box.scrollTop - box.clientHeight < 28) : true;
        this.searchLog = (r && r.entries) || [];
        // Keep pinned to newest unless the user scrolled up.
        if (atBottom) this.$nextTick(() => { const b = document.getElementById('searchLogBox'); if (b) b.scrollTop = b.scrollHeight; });
      } catch (e) { /* best-effort panel */ }
    },

    startSearchLog() {
      this.loadSearchLog();
      if (this.searchLogTimer) return;
      this.searchLogTimer = setInterval(() => {
        if (this.onSearchLogPage() && !this.searchLogCollapsed) this.loadSearchLog();
      }, 2000);
    },

    async clearSearchLog() {
      try { await this.api('/api/search-log/clear', { method: 'POST' }); } catch (e) {}
      this.searchLog = [];
    },

    // Color a log entry block by its content.
    searchLogClass(entry) {
      const t = entry || '';
      if (t.includes('✓ match')) return 'text-green-300';
      if (t.includes('🔎')) return 'text-cyan-300';
      if (t.includes('…')) return 'text-yellow-300';
      return 'text-gray-300';
    },

    async saveShopifyCredentials(domain) {
      const creds = this.shopifyCredentials[domain] || {};
      try {
        await this.api(`/api/source-sites/${encodeURIComponent(domain)}/credentials`, {
          method: 'PUT',
          body: JSON.stringify({
            shopify_store_url: creds.shopify_store_url || '',
            shopify_client_id: creds.shopify_client_id || '',
            shopify_client_secret: creds.shopify_client_secret || '',
            shopify_access_token: creds.shopify_access_token || '',
            sync_draft: creds.sync_draft || false,
            sync_archived: creds.sync_archived || false,
          }),
        });
        this.toast(`Credentials saved for ${domain}`, 'success', 2500);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to save credentials: ' + e.message, 'error'); }
    },

    async addSourceSite() {
      const url = (this.newSiteForm.shopify_store_url || '').trim().replace(/^https?:\/\//, '').replace(/\/$/, '');
      if (!this.newSiteForm.name.trim() || !url) {
        this.toast('Name and Store URL are required', 'error'); return;
      }
      // Derive domain from the myshopify URL (strip scheme, keep host)
      const domain = url.split('/')[0].toLowerCase();
      try {
        await this.api('/api/source-sites', {
          method: 'POST',
          body: JSON.stringify({
            name: this.newSiteForm.name.trim(),
            domain,
            shopify_store_url: 'https://' + url,
            is_destination: this.newSiteForm.is_destination,
          }),
        });
        this.newSiteForm = { show: false, name: '', shopify_store_url: '', is_destination: false };
        this.toast(`Store "${domain}" added`, 'success', 3000);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to add store: ' + e.message, 'error'); }
    },

    async removeSourceSite(domain) {
      if (this.removeSiteConfirm !== domain) {
        this.removeSiteConfirm = domain;
        setTimeout(() => { if (this.removeSiteConfirm === domain) this.removeSiteConfirm = null; }, 4000);
        return;
      }
      this.removeSiteConfirm = null;
      try {
        await this.api(`/api/source-sites/${encodeURIComponent(domain)}`, { method: 'DELETE' });
        this.toast(`Removed ${domain}`, 'success', 2500);
        await this.loadSettings();
      } catch (e) { this.toast('Failed to remove: ' + e.message, 'error'); }
    },

    async testShopifyConnection(domain) {
      this.shopifyTestStatus = { ...this.shopifyTestStatus, [domain]: 'testing' };
      try {
        const result = await this.api(`/api/source-sites/${encodeURIComponent(domain)}/test-connection`, { method: 'POST' });
        // Auth + shop read can succeed while product read is blocked by a missing
        // scope (products_ok === false) — surface that as a warning, not a green ✓.
        const status = !result.ok ? 'error' : (result.products_ok === false ? 'warn' : 'ok');
        this.shopifyTestStatus = { ...this.shopifyTestStatus, [domain]: status };
        this.shopifyTestMessage = {
          ...this.shopifyTestMessage,
          [domain]: !result.ok ? result.error
            : (result.products_ok === false ? result.warning : `Connected — ${result.shop_name} (${result.plan})`),
        };
      } catch (e) {
        this.shopifyTestStatus = { ...this.shopifyTestStatus, [domain]: 'error' };
        this.shopifyTestMessage = { ...this.shopifyTestMessage, [domain]: e.message };
      }
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
          this.showPausePrompt('comp', msg);
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
          this._clearPauseTimer();
          this.pausePrompt = null;
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

    // "Tied to a product in our store" checkbox — warn when unticked, since an
    // untied (free-text) search has no catalog product and so gets no "our price".
    notifyTiedToProduct(checked) {
      if (!checked) {
        this.toast('No price will be associated to the search results unless the search is tied to a product in our store.', 'info');
      }
    },

    // Our projected cost = our retail price × 0.7 (the price we show on our sites).
    fmtProjected(ourPrice) {
      return ourPrice != null ? `$${(Number(ourPrice) * 0.7).toFixed(2)}` : '—';
    },

    // --- SAME / SIMILR per-result checkboxes (keyed by URL, saved server-side) ---
    // confirmedRows maps url -> { type: 'same'|'similar', verified_at }. A key
    // exists only while a result is classified; SAME and SIMILR are mutually
    // exclusive (one stored value) and both may be left unchecked (no key).
    matchType(url) { return this.confirmedRows[url]?.type || null; },
    isSame(url) { return this.matchType(url) === 'same'; },
    isSimilar(url) { return this.matchType(url) === 'similar'; },
    // Back-compat: the live-results "Confirmed" checkboxes treat confirmed == SAME.
    isConfirmed(url) { return this.isSame(url); },
    confirmedAtLabel(url) {
      const ts = this.confirmedRows[url]?.verified_at;
      return ts ? new Date(ts).toLocaleDateString() : '';
    },
    // Set (or clear) a URL's match type. Checking one box replaces whatever was
    // there; unchecking the active box clears it. Mutual exclusivity is automatic
    // because a single value is stored per URL.
    async setMatch(url, type, checked) {
      if (!url) return;
      const desired = checked ? type : null;
      // Optimistic update, then reconcile with the server's authoritative timestamp.
      const prev = this.confirmedRows[url];
      if (desired) this.confirmedRows[url] = { type: desired, verified_at: new Date().toISOString() };
      else delete this.confirmedRows[url];
      try {
        const res = await this.api('/api/confirmations', {
          method: 'POST', body: JSON.stringify({ url, match_type: desired }),
        });
        if (desired && res?.verified_at) this.confirmedRows[url] = { type: desired, verified_at: res.verified_at };
      } catch (e) {
        if (prev !== undefined) this.confirmedRows[url] = prev; else delete this.confirmedRows[url];
        this.toast('Could not save selection: ' + e.message, 'error');
      }
    },
    // Back-compat shim for the untouched live-results "Confirmed" checkboxes.
    toggleConfirmed(url, checked) { return this.setMatch(url, 'same', checked); },
    async loadConfirmedRows() {
      try {
        const res = await this.api('/api/confirmations');
        this.confirmedRows = res?.confirmations || {};
      } catch { this.confirmedRows = {}; }
    },

    fmtDate(iso) { return iso ? new Date(iso).toLocaleString() : '—'; },
    fmtDateShort(iso) { return iso ? new Date(iso).toLocaleDateString() : '—'; },
    statusColor(s) {
      const m = { completed: 'text-green-500', running: 'text-blue-500', failed: 'text-red-500',
                  pending: 'text-yellow-500', cancelled: 'text-gray-400' };
      return m[s] || 'text-gray-400';
    },
  };
}
