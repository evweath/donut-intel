/**
 * Donut Intel Platform — Frontend Alpine.js application v2.0
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
      { id: 'duplicates',   icon: '🔁', label: 'Duplicates',        badge: 0 },
      { id: 'source-products', icon: '📂', label: 'Source Products',   badge: 0 },
      { id: 'find-product',    icon: '🔎', label: 'Find Product',       badge: 0 },
      { id: 'beat-price',      icon: '💡', label: 'Beat This Price',    badge: 0 },
      { id: 'find-customers',  icon: '👥', label: 'Find Customers',     badge: 0 },
      { id: 'sync',         icon: '🔄', label: 'Source Sync',        badge: 0 },
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
    priceComparison: null,
    priceHistory: null,
    loadingPriceComp: false,

    // Scans
    scanSessions: { sessions: [] },
    sourceSites: [],
    scanRunning: false,
    activeScanId: null,
    scanStatus: { message: '', current: 0, total: 0 },

    // Duplicates
    duplicates: { candidates: [] },
    dupFilter: 'pending',
    dupSelected: {},
    dupDomainFilters: {},

    // Source Domain Product Browser
    sourceProducts: { products: [], total: 0, page: 1, pages: 1 },
    sourceProductDomain: '',
    sourceProductSearch: '',
    sourceProductSelected: {},

    // Dashboard live log tail
    logTail: [],
    _logPollTimer: null,

    // Find This Product
    findProductQuery: '',
    findProductIds: [],
    findProductCatalogSearch: '',
    findProductCatalogResults: [],
    findProductMaxResults: 5,
    findProductResults: [],
    findProductLoading: false,

    // Beat This Price
    beatPriceForm: { description: '', price_min: '', price_max: '', max_results: 10 },
    beatPriceChars: { size: '', color: '', manufacturer: '', country_of_origin: '', features: '' },
    beatPriceResults: [],
    beatPriceLoading: false,

    // Find Me Customers
    findCustForm: { business_type: '', location: '', radius_miles: '', max_results: 20 },
    findCustKeywords: [],
    findCustKeywordInput: '',
    findCustResults: [],
    findCustLoading: false,

    // Source Sync / Domain Comparison
    domainComparison: { products: [], total: 0, all_domains: [], page: 1, pages: 1 },
    domainCompPage: 1,
    domainCompShowAll: false,
    syncSelected: {},   // { product_id: true/false }
    cycleStatus: { status: 'idle', domains_complete: [], domains_started: [], dedup_done: false, last_complete_at: null },
    taskList: [],
    parallelScanRunning: false,

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
    competitorProfile: null,
    competitorProfileSaving: false,
    competitorScanCriteria: {
      use_model_number: true, use_manufacturer: true, use_title_fuzzy: true,
      use_title_exact: true, use_price: false, fuzzy_threshold: 70,
    },
    competitorDetail: null,
    discoverRunning: false,
    competitorEditId: null,
    competitorEditForm: { name: '', base_url: '' },

    // Pricing matrix
    priceMatrix: { rows: [], competitors: [], total: 0, page: 1, pages: 1 },
    priceMatrixPage: 1,
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
        this.loadCompetitors(),
        this.loadJobs(),
        this.loadExportHistory(),
        this.loadCycleStatus(),
      ]);
      this.loadDuplicates();
      this.loadSourceSites();
      this.connectWebSocket();
      this._logPollTimer = setInterval(() => { this.loadLogTail(); }, 3000);
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
        const dupBadge = this.stats.pending_duplicates || 0;
        const nav = this.navItems.find(n => n.id === 'duplicates');
        if (nav) nav.badge = dupBadge;
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
        if (this.productFilters.search)      params.set('search', this.productFilters.search);
        if (this.productFilters.manufacturer) params.set('manufacturer', this.productFilters.manufacturer);
        if (this.productFilters.category)     params.set('category', this.productFilters.category);
        if (this.productFilters.source_site)  params.set('source_site', this.productFilters.source_site);
        if (this.productFilters.min_price)    params.set('min_price', this.productFilters.min_price);
        if (this.productFilters.max_price)    params.set('max_price', this.productFilters.max_price);
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
        if (!Object.keys(this.dupDomainFilters).length) {
          const filters = {};
          this.sourceSites.forEach(s => { filters[s.domain] = true; });
          this.dupDomainFilters = filters;
        }
        if (!this.sourceProductDomain && this.sourceSites.length) {
          this.sourceProductDomain = this.sourceSites[0].domain;
        }
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
    // Deduplication
    // -----------------------------------------------------------------------
    async runDedup() {
      try {
        const selected = Object.entries(this.dupDomainFilters).filter(([, v]) => v).map(([k]) => k);
        const body = selected.length && selected.length < this.sourceSites.length
          ? { domain_filters: selected }
          : {};
        await this.api('/api/dedup/run', { method: 'POST', body: JSON.stringify(body) });
        this.toast('Deduplication started in background...', 'info');
      } catch (e) { this.toast('Failed to start dedup: ' + e.message, 'error'); }
    },

    async loadDuplicates() {
      try {
        const params = new URLSearchParams({ status: this.dupFilter, per_page: 50 });
        this.duplicates = await this.api(`/api/dedup/candidates?${params}`) || { candidates: [] };
        this.dupSelected = {};
      } catch {}
    },

    async resolvedup(candidateId, action) {
      try {
        await this.api(`/api/dedup/candidates/${candidateId}/resolve`, {
          method: 'POST', body: JSON.stringify({ action }),
        });
        this.toast(action === 'merge' ? 'Products merged' : 'Duplicate rejected', 'success');
        await this.loadDuplicates();
        await this.loadStats();
      } catch (e) { this.toast('Failed to resolve: ' + e.message, 'error'); }
    },

    dupSelectedCount() {
      return Object.values(this.dupSelected).filter(Boolean).length;
    },

    dupAllSelected() {
      const candidates = this.duplicates.candidates || [];
      return candidates.length > 0 && candidates.every(d => this.dupSelected[d.id]);
    },

    dupToggleSelectAll() {
      const candidates = this.duplicates.candidates || [];
      const selectAll = !this.dupAllSelected();
      const updated = {};
      candidates.forEach(d => { updated[d.id] = selectAll; });
      this.dupSelected = updated;
    },

    async deleteSelectedDups() {
      const ids = Object.entries(this.dupSelected).filter(([, v]) => v).map(([k]) => parseInt(k));
      if (!ids.length) return;
      try {
        const res = await this.api('/api/dedup/candidates/bulk-delete', {
          method: 'POST', body: JSON.stringify({ candidate_ids: ids }),
        });
        this.toast(`Deleted ${res.deleted} duplicate${res.deleted !== 1 ? 's' : ''}`, 'success');
        await this.loadDuplicates();
        await this.loadStats();
      } catch (e) { this.toast('Failed to delete: ' + e.message, 'error'); }
    },

    async dupSelectAllPages() {
      try {
        const res = await this.api(`/api/dedup/candidates/ids?status=${this.dupFilter}`);
        const all = {};
        (res.ids || []).forEach(id => { all[id] = true; });
        this.dupSelected = all;
        this.toast(`Selected ${res.ids.length} duplicate${res.ids.length !== 1 ? 's' : ''} across all pages`, 'info');
      } catch (e) { this.toast('Failed to select all: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Source Domain Product Browser
    // -----------------------------------------------------------------------
    async loadSourceProducts(domain, page = 1) {
      if (domain) this.sourceProductDomain = domain;
      if (!this.sourceProductDomain && this.sourceSites.length) {
        this.sourceProductDomain = this.sourceSites[0].domain;
      }
      try {
        const params = new URLSearchParams({ source_site: this.sourceProductDomain, page, per_page: 50 });
        if (this.sourceProductSearch) params.set('search', this.sourceProductSearch);
        this.sourceProducts = await this.api(`/api/products?${params}`) || { products: [], total: 0, page: 1, pages: 1 };
        this.sourceProductSelected = {};
      } catch (e) { this.toast('Failed to load products: ' + e.message, 'error'); }
    },

    sourceProductSelectedCount() {
      return Object.values(this.sourceProductSelected).filter(Boolean).length;
    },

    sourceProductAllSelected() {
      const prods = this.sourceProducts.products || [];
      return prods.length > 0 && prods.every(p => this.sourceProductSelected[p.id]);
    },

    sourceProductToggleSelectAll() {
      const prods = this.sourceProducts.products || [];
      const selectAll = !this.sourceProductAllSelected();
      const updated = {};
      prods.forEach(p => { updated[p.id] = selectAll; });
      this.sourceProductSelected = updated;
    },

    async sourceProductSelectAllPages() {
      try {
        const params = new URLSearchParams({ source_site: this.sourceProductDomain });
        if (this.sourceProductSearch) params.set('search', this.sourceProductSearch);
        const res = await this.api(`/api/products/ids?${params}`);
        const all = {};
        (res.ids || []).forEach(id => { all[id] = true; });
        this.sourceProductSelected = all;
        this.toast(`Selected ${res.ids.length} product${res.ids.length !== 1 ? 's' : ''} across all pages`, 'info');
      } catch (e) { this.toast('Failed to select all: ' + e.message, 'error'); }
    },

    async deactivateSelectedProducts() {
      const ids = Object.entries(this.sourceProductSelected).filter(([, v]) => v).map(([k]) => parseInt(k));
      if (!ids.length) return;
      try {
        const res = await this.api('/api/products/bulk-deactivate', {
          method: 'POST', body: JSON.stringify({ product_ids: ids }),
        });
        this.toast(`Deactivated ${res.deactivated} product${res.deactivated !== 1 ? 's' : ''}`, 'success');
        await this.loadSourceProducts(null, this.sourceProducts.page);
        await this.loadStats();
      } catch (e) { this.toast('Failed to deactivate: ' + e.message, 'error'); }
    },

    // -----------------------------------------------------------------------
    // Dashboard — live log tail + cycle status helpers
    // -----------------------------------------------------------------------
    async loadLogTail() {
      try {
        const r = await this.api('/api/logs/tail?lines=7');
        if (r === null) {
          // 401 — session expired, stop polling
          if (this._logPollTimer) { clearInterval(this._logPollTimer); this._logPollTimer = null; }
          return;
        }
        this.logTail = r.lines || [];
      } catch {}
    },

    cycleStatusLabel() {
      const s = this.cycleStatus?.status || 'idle';
      if (s === 'scanning' && this.scanStatus?.message) return this.scanStatus.message;
      const started = this.cycleStatus?.domains_started?.length || 0;
      const done = this.cycleStatus?.domains_complete?.length || 0;
      return {
        idle: 'No scan running',
        scanning: `Scanning source domains (${done}/${started} complete)`,
        dedup_running: 'Running deduplication across all domains...',
        review_pending: 'Awaiting duplicate review',
        complete: 'Scan cycle complete',
      }[s] || s;
    },

    cycleNextStep() {
      const s = this.cycleStatus?.status || 'idle';
      const done = this.cycleStatus?.domains_complete?.length || 0;
      const total = this.cycleStatus?.domains_started?.length || 0;
      const pending = this.stats?.pending_duplicates || 0;
      const ts = this.cycleStatus?.last_complete_at
        ? new Date(this.cycleStatus.last_complete_at).toLocaleString() : '';
      return {
        idle: 'Click "Scan All Sources" to begin a full data collection cycle.',
        scanning: done < total
          ? `${total - done} domain${total - done !== 1 ? 's' : ''} still scanning — deduplication will start automatically when all finish.`
          : 'All domains scanned — deduplication starting...',
        dedup_running: 'Identifying duplicate products across all source domains. This may take a few minutes.',
        review_pending: pending
          ? `${pending} duplicate${pending !== 1 ? 's' : ''} need review. Go to Duplicates, resolve them, then approve the cycle.`
          : 'Deduplication complete. Approve the cycle to finalize.',
        complete: `Last cycle finished${ts ? ' at ' + ts : ''}. Start a new scan when ready.`,
      }[s] || '';
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

    async runFindProduct() {
      if (!this.findProductQuery && !this.findProductIds.length) {
        this.toast('Enter a query or select products from the catalog', 'info');
        return;
      }
      this.findProductLoading = true;
      this.findProductResults = [];
      try {
        const res = await this.api('/api/search/find-product', {
          method: 'POST',
          body: JSON.stringify({
            product_ids: this.findProductIds.length ? this.findProductIds : null,
            query: this.findProductQuery || null,
            max_results: this.findProductMaxResults,
          }),
        });
        this.findProductResults = res?.results || [];
        if (!this.findProductResults.length) this.toast('No results found — try a different query', 'info');
      } catch (e) { this.toast('Search failed: ' + e.message, 'error'); }
      finally { this.findProductLoading = false; }
    },

    // -----------------------------------------------------------------------
    // Beat This Price
    // -----------------------------------------------------------------------
    async runBeatPrice() {
      if (!this.beatPriceForm.description) {
        this.toast('Enter a product description', 'info');
        return;
      }
      this.beatPriceLoading = true;
      this.beatPriceResults = [];
      try {
        const chars = Object.fromEntries(
          Object.entries(this.beatPriceChars).filter(([, v]) => v)
        );
        const res = await this.api('/api/search/beat-price', {
          method: 'POST',
          body: JSON.stringify({
            description: this.beatPriceForm.description,
            price_min: this.beatPriceForm.price_min ? parseFloat(this.beatPriceForm.price_min) : null,
            price_max: this.beatPriceForm.price_max ? parseFloat(this.beatPriceForm.price_max) : null,
            characteristics: Object.keys(chars).length ? chars : null,
            max_results: this.beatPriceForm.max_results,
          }),
        });
        this.beatPriceResults = res?.results || [];
        if (!this.beatPriceResults.length) this.toast('No suppliers found — try broadening the description', 'info');
      } catch (e) { this.toast('Search failed: ' + e.message, 'error'); }
      finally { this.beatPriceLoading = false; }
    },

    // -----------------------------------------------------------------------
    // Find Me New Customers
    // -----------------------------------------------------------------------
    addFindCustKeyword() {
      const kw = this.findCustKeywordInput.trim();
      if (kw && !this.findCustKeywords.includes(kw)) {
        this.findCustKeywords = [...this.findCustKeywords, kw];
        this.findCustKeywordInput = '';
      }
    },

    removeFindCustKeyword(kw) {
      this.findCustKeywords = this.findCustKeywords.filter(k => k !== kw);
    },

    async runFindCustomers() {
      if (!this.findCustForm.business_type && !this.findCustForm.location && !this.findCustKeywords.length) {
        this.toast('Enter at least a business type, location, or keyword', 'info');
        return;
      }
      this.findCustLoading = true;
      this.findCustResults = [];
      try {
        const res = await this.api('/api/search/find-customers', {
          method: 'POST',
          body: JSON.stringify({
            business_type: this.findCustForm.business_type || null,
            location: this.findCustForm.location || null,
            radius_miles: this.findCustForm.radius_miles ? parseInt(this.findCustForm.radius_miles) : null,
            keywords: this.findCustKeywords.length ? this.findCustKeywords : null,
            max_results: this.findCustForm.max_results,
          }),
        });
        this.findCustResults = res?.results || [];
        if (!this.findCustResults.length) this.toast('No customers found — try different criteria', 'info');
      } catch (e) { this.toast('Search failed: ' + e.message, 'error'); }
      finally { this.findCustLoading = false; }
    },

    // Returns an array of comparison rows for the duplicate card.
    // Each row: { label, primary, secondary, score, mono }
    dupFields(dup) {
      const r = dup.match_reasons || {};
      const p = dup.primary;
      const s = dup.secondary;
      const fp = v => v != null ? '$' + Number(v).toFixed(2) : '—';
      return [
        { label: 'Title',        primary: p.title        || '—', secondary: s.title        || '—', score: r.title_fuzzy,   mono: false },
        { label: 'Price',        primary: fp(p.price),           secondary: fp(s.price),           score: r.price,         mono: false },
        { label: 'Manufacturer', primary: p.manufacturer  || '—', secondary: s.manufacturer  || '—', score: r.manufacturer, mono: false },
        { label: 'Model #',      primary: p.model_number  || '—', secondary: s.model_number  || '—', score: r.model_number, mono: true  },
        { label: 'SKU',          primary: p.sku            || '—', secondary: s.sku            || '—', score: r.sku,          mono: true  },
        { label: 'Sources',      primary: (p.sources||[]).join(', ')||'—', secondary: (s.sources||[]).join(', ')||'—', score: null, mono: false },
      ];
    },

    // Row background class based on match score.
    dupRowClass(score, hasBoth) {
      if (score === null || score === undefined) return 'bg-blue-50 dark:bg-blue-900/20';
      if (!hasBoth) return 'bg-gray-50 dark:bg-gray-700/30';
      if (score >= 80) return 'bg-green-50 dark:bg-green-900/20';
      if (score >= 40) return 'bg-yellow-50 dark:bg-yellow-900/20';
      return 'bg-red-50 dark:bg-red-900/20';
    },

    // One-line explanation of why the confidence score is what it is.
    dupSummary(dup) {
      const r = dup.match_reasons || {};
      if (r.disqualifier === 'model_number_mismatch')
        return 'Model numbers present but conflict — score capped at 5%.';
      if (r.disqualifier === 'sku_mismatch')
        return 'SKUs present but conflict — score capped at 5%.';
      const factors = [
        { name: 'model number', score: r.model_number  || 0 },
        { name: 'price',        score: r.price         || 0 },
        { name: 'manufacturer', score: r.manufacturer  || 0 },
        { name: 'title',        score: r.title_fuzzy   || 0 },
        { name: 'description',  score: r.description   || 0 },
      ].filter(f => f.score > 0).sort((a, b) => b.score - a.score);
      if (!factors.length) return 'No matching signals found.';
      const top = factors.slice(0, 2).map(f => `${f.name} (${Math.round(f.score)}%)`);
      const missing = [
        r.model_number === 0 && dup.primary.model_number && dup.secondary.model_number ? 'model mismatch' : null,
        r.price        === 0 && dup.primary.price        && dup.secondary.price        ? 'price gap'      : null,
      ].filter(Boolean);
      let note = 'Driven by ' + top.join(' and ') + '.';
      if (missing.length) note += ' Limited by ' + missing.join(', ') + '.';
      return note;
    },

    // -----------------------------------------------------------------------
    // Source Sync / Domain Comparison
    // -----------------------------------------------------------------------
    async loadDomainComparison(page = 1) {
      this.domainCompPage = page;
      try {
        const params = new URLSearchParams({ page, per_page: 50, show_all: this.domainCompShowAll });
        this.domainComparison = await this.api(`/api/domain-comparison?${params}`) || { products: [], total: 0, all_domains: [] };
      } catch (e) { this.toast('Failed to load domain comparison: ' + e.message, 'error'); }
    },

    toggleSyncSelect(productId) {
      this.syncSelected[productId] = !this.syncSelected[productId];
    },

    selectAllSync() {
      this.domainComparison.products.forEach(p => { this.syncSelected[p.product_id] = true; });
    },

    clearSyncSelect() {
      this.syncSelected = {};
    },

    syncSelectedCount() {
      return Object.values(this.syncSelected).filter(Boolean).length;
    },

    // -----------------------------------------------------------------------
    // Scan Cycle & Parallel Tasks
    // -----------------------------------------------------------------------
    async loadCycleStatus() {
      try {
        this.cycleStatus = await this.api('/api/scan/cycle-status') || { status: 'idle' };
      } catch {}
    },

    async loadTaskList() {
      try {
        this.taskList = (await this.api('/api/tasks')).tasks || [];
      } catch {}
    },

    async startParallelScan() {
      if (this.parallelScanRunning) return;
      if (!confirm('Start a full parallel scan of all source domains? This will scrape all domains simultaneously, then auto-run deduplication.')) return;
      this.parallelScanRunning = true;
      try {
        await this.api('/api/scan/all-sources', { method: 'POST', body: JSON.stringify({}) });
        this.toast('Parallel scan started — all domains scanning simultaneously', 'info');
        await this.loadCycleStatus();
        await this.loadTaskList();
      } catch (e) {
        this.toast('Failed to start scan: ' + e.message, 'error');
        this.parallelScanRunning = false;
      }
    },

    async approveCycle() {
      if (!confirm('Mark this scan cycle as complete and approved? This will allow a new full scan to begin.')) return;
      try {
        await this.api('/api/scan/cycle/approve', { method: 'POST', body: JSON.stringify({}) });
        this.toast('Scan cycle approved — ready for next scan', 'success');
        await this.loadCycleStatus();
        this.parallelScanRunning = false;
      } catch (e) { this.toast('Failed: ' + e.message, 'error'); }
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

    async deleteCompetitor(id) {
      try {
        await this.api(`/api/competitors/${id}`, { method: 'DELETE' });
        this.toast('Competitor deactivated', 'success');
        this.competitorEditId = null;
        await this.loadCompetitors();
        this.competitorDetail = null;
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
      try {
        this.priceMatrix = await this.api(`/api/price-comparison?page=${page}&per_page=25`) || { rows: [], competitors: [] };
      } catch (e) { this.toast('Failed to load price matrix: ' + e.message, 'error'); }
      finally { this.loadingMatrix = false; }
    },

    priceDiff(ourPrice, theirPrice) {
      if (!ourPrice || !theirPrice) return null;
      return ((theirPrice - ourPrice) / ourPrice * 100).toFixed(1);
    },

    priceDiffClass(diff) {
      if (diff === null) return '';
      return parseFloat(diff) < 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold';
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
        case 'dedup_complete':
          this.toast(`Dedup done — ${msg.stats?.auto_merged || 0} merged, ${msg.stats?.flagged_for_review || 0} need review`, 'success');
          this.loadDuplicates(); this.loadStats(); break;
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
