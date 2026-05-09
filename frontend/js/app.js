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

    // Competitors
    competitors: { competitors: [], total: 0 },
    competitorPage: 1,
    competitorSearch: '',
    discoverForm: { max_results: 20, keywords: '', session_name: '' },
    bulkImportText: '',
    bulkImportSessionName: '',
    competitorScanForm: { ids: [], session_name: '', find_similar: false, max_pages: 100, criteria: {} },
    competitorScanCriteria: {
      use_model_number: true, use_manufacturer: true, use_title_fuzzy: true,
      use_title_exact: true, use_price: false, fuzzy_threshold: 70,
    },
    competitorDetail: null,
    discoverRunning: false,

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
      ]);
      this.loadDuplicates();
      this.loadSourceSites();
      this.connectWebSocket();
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
        await this.api('/api/dedup/run', { method: 'POST', body: JSON.stringify({}) });
        this.toast('Deduplication started in background...', 'info');
      } catch (e) { this.toast('Failed to start dedup: ' + e.message, 'error'); }
    },

    async loadDuplicates() {
      try {
        const params = new URLSearchParams({ status: this.dupFilter, per_page: 50 });
        this.duplicates = await this.api(`/api/dedup/candidates?${params}`) || { candidates: [] };
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
          custom_keywords: this.discoverForm.keywords ? this.discoverForm.keywords.split('\n').map(k => k.trim()).filter(Boolean) : undefined,
        };
        await this.api('/api/competitors/discover', { method: 'POST', body: JSON.stringify(body) });
        this.toast('Competitor discovery started...', 'info');
      } catch (e) {
        this.discoverRunning = false;
        this.toast('Discovery failed: ' + e.message, 'error');
      }
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
        this.toast(`Scanning ${ids.length} competitor(s)...`, 'info');
      } catch (e) { this.toast('Competitor scan failed: ' + e.message, 'error'); }
    },

    async openCompetitor(comp) {
      try { this.competitorDetail = await this.api(`/api/competitors/${comp.id}`); }
      catch (e) { this.toast('Failed to load competitor: ' + e.message, 'error'); }
    },

    async deleteCompetitor(id) {
      if (!confirm('Deactivate this competitor?')) return;
      try {
        await this.api(`/api/competitors/${id}`, { method: 'DELETE' });
        this.toast('Competitor deactivated', 'success');
        await this.loadCompetitors();
        this.competitorDetail = null;
      } catch (e) { this.toast('Failed to delete: ' + e.message, 'error'); }
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
          this.loadCompetitors(); this.loadStats(); break;
        case 'competitor_scan_error':
          this.toast(`Competitor scan error: ${msg.error}`, 'error'); break;
        case 'ai_categorize_complete':
          this.toast(`AI categorized ${msg.categorized}/${msg.total} products`, 'success');
          this.loadProducts(); break;
        case 'crawl_progress':
          if (msg.pages_visited % 10 === 0)
            this.scanStatus.message = `Crawling... ${msg.pages_visited} pages, ${msg.products_found} found`;
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
