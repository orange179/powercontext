const API_BASE = window.location.origin;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let currentTab = 'search';

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', () => {
    initTabs();
    initSearch();
    initPapers();
    initModal();
    checkHealth();
});

async function checkHealth() {
    try {
        const res = await fetch(`${API_BASE}/api/health`);
        const data = await res.json();
        const dot = document.getElementById('statusDot');
        const text = document.getElementById('statusText');
        if (data.seekdb_available) {
            dot.className = 'status-dot connected';
            text.textContent = `seekdb: ${data.seekdb_mode}`;
        } else {
            dot.className = 'status-dot';
            text.textContent = `mode: ${data.seekdb_mode}`;
        }
    } catch {
        document.getElementById('statusDot').className = 'status-dot error';
        document.getElementById('statusText').textContent = 'backend offline';
    }
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
function initTabs() {
    document.querySelectorAll('.tab').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
            btn.classList.add('active');
            const tab = btn.dataset.tab;
            document.getElementById(`tab-${tab}`).classList.add('active');
            currentTab = tab;
            if (tab === 'papers') loadPapers();
            if (tab === 'stats') loadStats();
        });
    });
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
function initSearch() {
    document.getElementById('searchBtn').addEventListener('click', doSearch);
    document.getElementById('searchInput').addEventListener('keydown', e => {
        if (e.key === 'Enter') doSearch();
    });
}

async function doSearch() {
    const query = document.getElementById('searchInput').value.trim();
    if (!query) return;

    const mode = document.getElementById('searchMode').value;
    const n = parseInt(document.getElementById('nResults').value);
    const tag = document.getElementById('filterTag').value.trim();
    const yearMin = document.getElementById('filterYearMin').value;
    const yearMax = document.getElementById('filterYearMax').value;

    const filters = {};
    if (tag) filters.tag = tag;
    if (yearMin) filters.year_min = parseInt(yearMin);
    if (yearMax) filters.year_max = parseInt(yearMax);

    const area = document.getElementById('searchResults');
    area.innerHTML = '<div class="empty-state"><p>...</p><p>Searching...</p></div>';

    try {
        const res = await fetch(`${API_BASE}/api/search`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query, search_mode: mode, n_results: n, filters: Object.keys(filters).length ? filters : null }),
        });
        const data = await res.json();
        renderSearchResults(data, area);
    } catch (err) {
        area.innerHTML = `<div class="empty-state"><p>Error</p><p>${err.message}</p></div>`;
    }
}

function renderSearchResults(data, area) {
    if (!data.results || data.results.length === 0) {
        area.innerHTML = '<div class="empty-state"><p>&#x1F50D;</p><p>No results found</p></div>';
        return;
    }

    const modeLabels = { hybrid: 'Hybrid', vector: 'Vector', keyword: 'Keyword' };
    let html = `<div class="search-info">
        <span>Found ${data.total} results for "${data.query}" (${modeLabels[data.search_mode] || data.search_mode} search)</span>
    </div>`;

    for (const r of data.results) {
        html += renderResultCard(r);
    }
    area.innerHTML = html;
}

function renderResultCard(r) {
    const tags = (r.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');
    const authors = (r.authors || []).join(', ');
    return `<div class="result-card">
        <div class="result-header">
            <div class="result-title">${esc(r.title)}</div>
            <div class="result-score">Score: ${r.score}</div>
        </div>
        <div class="result-meta">
            <span>&#x1F464; ${esc(authors)}</span>
            <span>&#x1F4C5; ${r.year}</span>
            ${r.source ? `<span>&#x1F517; ${esc(r.source)}</span>` : ''}
        </div>
        <div class="result-abstract">${esc(r.abstract || '')}</div>
        <div class="result-tags">${tags}</div>
    </div>`;
}

// ---------------------------------------------------------------------------
// Papers
// ---------------------------------------------------------------------------
function initPapers() {
    document.getElementById('importSampleBtn').addEventListener('click', importSample);
    document.getElementById('addPaperBtn').addEventListener('click', () => {
        document.getElementById('addPaperModal').classList.add('open');
    });
    document.getElementById('paperFilterStatus').addEventListener('change', loadPapers);
}

async function loadPapers() {
    const status = document.getElementById('paperFilterStatus').value;
    const url = `${API_BASE}/api/papers${status ? `?reading_status=${status}` : ''}`;
    try {
        const res = await fetch(url);
        const data = await res.json();
        renderPapers(data.papers, document.getElementById('papersList'));
    } catch {
        document.getElementById('papersList').innerHTML = '<div class="empty-state"><p>Error loading papers</p></div>';
    }
}

function renderPapers(papers, area) {
    if (!papers || papers.length === 0) {
        area.innerHTML = '<div class="empty-state"><p>&#x1F4C4;</p><p>No papers yet</p><p class="hint">Click "Import Sample Data" to get started</p></div>';
        return;
    }

    let html = '';
    for (const p of papers) {
        const statusClass = `status-${p.reading_status || 'unread'}`;
        const statusLabel = { unread: 'Unread', reading: 'Reading', read: 'Read' }[p.reading_status] || 'Unread';
        const authors = (p.authors || []).join(', ');
        const tags = (p.tags || []).map(t => `<span class="tag">${esc(t)}</span>`).join('');

        html += `<div class="paper-card" data-id="${p.id}">
            <div class="paper-info">
                <div class="paper-title">${esc(p.title)}</div>
                <div class="paper-meta">
                    <span>${esc(authors)}</span>
                    <span>${p.year}</span>
                </div>
                <div class="result-tags" style="margin-top:6px">${tags}</div>
            </div>
            <div class="paper-actions">
                <span class="status-badge ${statusClass}">${statusLabel}</span>
                <button class="btn-icon" onclick="cycleStatus('${p.id}', '${p.reading_status || 'unread'}')" title="Toggle status">&#x21BB;</button>
                <button class="btn-icon danger" onclick="deletePaper('${p.id}')" title="Delete">&#x1F5D1;</button>
            </div>
        </div>`;
    }
    area.innerHTML = html;
}

async function importSample() {
    const btn = document.getElementById('importSampleBtn');
    btn.disabled = true;
    btn.textContent = 'Importing...';
    try {
        const res = await fetch(`${API_BASE}/api/import-sample`, { method: 'POST' });
        const data = await res.json();
        btn.textContent = `Imported ${data.imported} papers`;
        setTimeout(() => { btn.textContent = '\u{1F4E5} Import Sample Data'; btn.disabled = false; }, 2000);
        loadPapers();
    } catch {
        btn.textContent = 'Import failed';
        btn.disabled = false;
    }
}

async function cycleStatus(id, current) {
    const next = { unread: 'reading', reading: 'read', read: 'unread' }[current] || 'unread';
    await fetch(`${API_BASE}/api/papers/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reading_status: next }),
    });
    loadPapers();
}

async function deletePaper(id) {
    if (!confirm('Delete this paper?')) return;
    await fetch(`${API_BASE}/api/papers/${id}`, { method: 'DELETE' });
    loadPapers();
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------
async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/api/stats`);
        const data = await res.json();
        document.getElementById('statTotal').textContent = data.total_papers;
        document.getElementById('statMode').textContent = data.seekdb_mode;
        document.getElementById('statRead').textContent = data.reading_status.read || 0;
        document.getElementById('statUnread').textContent = (data.reading_status.unread || 0) + (data.reading_status.reading || 0);

        renderTagChart(data.tags || {});
        renderYearChart(data.papers_by_year || {});
    } catch {
        // ignore
    }
}

function renderTagChart(tags) {
    const el = document.getElementById('tagsChart');
    const entries = Object.entries(tags).sort((a, b) => b[1] - a[1]);
    if (entries.length === 0) { el.innerHTML = '<span style="color:var(--text-secondary);font-size:13px">No data</span>'; return; }
    el.innerHTML = entries.map(([tag, count]) =>
        `<div class="chart-bar"><span class="chart-bar-label">${esc(tag)}</span><span class="chart-bar-value">${count}</span></div>`
    ).join('');
}

function renderYearChart(years) {
    const el = document.getElementById('yearChart');
    const entries = Object.entries(years).sort((a, b) => a[0] - b[0]);
    if (entries.length === 0) { el.innerHTML = '<span style="color:var(--text-secondary);font-size:13px">No data</span>'; return; }
    el.innerHTML = entries.map(([year, count]) =>
        `<div class="chart-bar"><span class="chart-bar-label">${year}</span><span class="chart-bar-value">${count}</span></div>`
    ).join('');
}

// ---------------------------------------------------------------------------
// Modal
// ---------------------------------------------------------------------------
function initModal() {
    const modal = document.getElementById('addPaperModal');
    document.getElementById('closeModal').addEventListener('click', () => modal.classList.remove('open'));
    modal.addEventListener('click', e => { if (e.target === modal) modal.classList.remove('open'); });

    document.getElementById('addPaperForm').addEventListener('submit', async e => {
        e.preventDefault();
        const paper = {
            title: document.getElementById('paperTitle').value,
            abstract: document.getElementById('paperAbstract').value,
            content: document.getElementById('paperContent').value,
            authors: document.getElementById('paperAuthors').value.split(',').map(s => s.trim()).filter(Boolean),
            year: parseInt(document.getElementById('paperYear').value) || 2026,
            tags: document.getElementById('paperTags').value.split(',').map(s => s.trim()).filter(Boolean),
            source: document.getElementById('paperSource').value,
        };
        try {
            await fetch(`${API_BASE}/api/papers`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(paper),
            });
            modal.classList.remove('open');
            e.target.reset();
            loadPapers();
        } catch {
            alert('Failed to add paper');
        }
    });
}

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
function esc(s) {
    const d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
}
