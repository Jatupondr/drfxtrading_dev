/**
 * charts.js — DRFX Trading Dashboard Chart Manager
 * Handles equity curve (Chart.js), heatmap rendering,
 * and TradingView widget initialisation.
 */

// ── Equity Curve Chart ──────────────────────────────────────────────
let equityChart = null;

function initEquityChart(canvasId) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;

    equityChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [
                {
                    label: 'Equity',
                    data: [],
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.08)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: '#22c55e',
                },
                {
                    label: 'Balance',
                    data: [],
                    borderColor: '#38bdf8',
                    backgroundColor: 'rgba(56, 189, 248, 0.05)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: '#38bdf8',
                    borderDash: [5, 3],
                },
                {
                    label: 'Floating P/L',
                    data: [],
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.05)',
                    borderWidth: 1.5,
                    fill: false,
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 3,
                    pointHoverBackgroundColor: '#f59e0b',
                    borderDash: [2, 2],
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 500 },
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    align: 'end',
                    labels: {
                        color: '#94a3b8',
                        font: { family: "'JetBrains Mono', monospace", size: 11 },
                        boxWidth: 14,
                        boxHeight: 2,
                        padding: 16,
                        usePointStyle: false,
                    },
                },
                tooltip: {
                    backgroundColor: 'rgba(15, 20, 32, 0.95)',
                    titleColor: '#e2e8f0',
                    bodyColor: '#94a3b8',
                    borderColor: '#1e293b',
                    borderWidth: 1,
                    padding: 12,
                    titleFont: { family: "'JetBrains Mono', monospace", size: 11, weight: '600' },
                    bodyFont: { family: "'JetBrains Mono', monospace", size: 11 },
                    displayColors: true,
                    callbacks: {
                        label: (ctx) => `${ctx.dataset.label}: $${ctx.parsed.y.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
                    },
                },
            },
            scales: {
                x: {
                    display: true,
                    grid: { color: 'rgba(30, 41, 59, 0.4)', drawBorder: false },
                    ticks: {
                        color: '#64748b',
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        maxTicksLimit: 8,
                        maxRotation: 0,
                    },
                },
                y: {
                    display: true,
                    position: 'right',
                    grid: { color: 'rgba(30, 41, 59, 0.4)', drawBorder: false },
                    ticks: {
                        color: '#64748b',
                        font: { family: "'JetBrains Mono', monospace", size: 10 },
                        callback: (v) => '$' + v.toLocaleString(),
                    },
                },
            },
        },
    });
}

function updateEquityChart(curves) {
    if (!equityChart) return;

    // Merge all account curves into combined timeline
    const combined = {};
    for (const [login, points] of Object.entries(curves)) {
        for (const p of points) {
            const key = p.time.substring(0, 16); // group by minute
            if (!combined[key]) combined[key] = { balance: 0, equity: 0 };
            combined[key].balance += p.balance;
            combined[key].equity += p.equity;
        }
    }

    const sorted = Object.entries(combined).sort((a, b) => a[0].localeCompare(b[0]));
    const labels = sorted.map(([t]) => {
        const d = new Date(t);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });
    const equities = sorted.map(([, v]) => v.equity);
    const balances = sorted.map(([, v]) => v.balance);
    const floating = sorted.map(([, v]) => Math.round((v.equity - v.balance) * 100) / 100);

    equityChart.data.labels = labels;
    equityChart.data.datasets[0].data = equities;
    equityChart.data.datasets[1].data = balances;
    equityChart.data.datasets[2].data = floating;
    equityChart.update('none'); // skip animation for WS updates
}


// ── Heatmap Rendering ───────────────────────────────────────────────
const CURRENCIES = ['USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'NZD'];

function renderHeatmap(containerId, heatmapData) {
    const el = document.getElementById(containerId);
    if (!el || !heatmapData) return;

    const { strength, matrix } = heatmapData;

    // Render strength bars
    const barsHtml = renderStrengthBars(strength);

    // Render matrix grid
    let gridHtml = '<div class="heatmap-grid">';
    // Header row
    gridHtml += '<div class="heatmap-header"></div>';
    CURRENCIES.forEach(c => {
        gridHtml += `<div class="heatmap-header">${c}</div>`;
    });

    // Data rows
    if (matrix && matrix.length > 0) {
        matrix.forEach(row => {
            gridHtml += `<div class="heatmap-row-label">${row.currency}</div>`;
            CURRENCIES.forEach(col => {
                const val = row[col] || 0;
                const bg = heatmapCellColor(val);
                const textColor = Math.abs(val) > 40 ? '#fff' : '#94a3b8';
                gridHtml += `<div class="heatmap-cell" style="background:${bg};color:${textColor}" title="${row.currency}/${col}: ${val}">${val !== 0 ? val : '—'}</div>`;
            });
        });
    }
    gridHtml += '</div>';

    el.innerHTML = barsHtml + gridHtml;
}

function renderStrengthBars(strength) {
    if (!strength) return '';
    let html = '<div class="strength-bars">';
    CURRENCIES.forEach(c => {
        const val = strength[c] || 0;
        const isPositive = val >= 0;
        const color = isPositive ? '#22c55e' : '#ef4444';
        const height = Math.min(Math.abs(val) * 0.4, 40);
        const direction = isPositive ? 'bottom: 50%' : 'top: 50%';
        html += `
        <div class="strength-item">
            <span class="strength-label">${c}</span>
            <div class="strength-bar-track">
                <div class="strength-bar-fill" style="${direction};height:${height}px;background:${color};opacity:0.7"></div>
            </div>
            <span class="strength-value" style="color:${color}">${val > 0 ? '+' : ''}${val}</span>
        </div>`;
    });
    html += '</div>';
    return html;
}

function heatmapCellColor(val) {
    // Map value (-100..100) to green/red with opacity
    const abs = Math.min(Math.abs(val), 100);
    const alpha = abs / 100 * 0.6 + 0.05;
    if (val > 0) return `rgba(34, 197, 94, ${alpha})`;
    if (val < 0) return `rgba(239, 68, 68, ${alpha})`;
    return 'rgba(30, 41, 59, 0.3)';
}


// ── Market Overview Cards ───────────────────────────────────────────
function renderMarketOverview(containerId, marketData) {
    const el = document.getElementById(containerId);
    if (!el || !marketData) return;

    el.innerHTML = marketData.map(m => {
        const isUp = m.change >= 0;
        const arrow = isUp ? '▲' : '▼';
        const cls = isUp ? 'up' : 'down';
        const decimals = m.symbol.includes('JPY') ? 3 : m.symbol.includes('BTC') ? 1 : m.symbol.includes('XAU') ? 2 : 5;
        return `
        <div class="market-card">
            <div class="symbol">${m.symbol}</div>
            <div class="price">${m.bid.toFixed(decimals)}</div>
            <div class="change ${cls}">${arrow} ${Math.abs(m.change).toFixed(3)}%</div>
            <div class="spread">Spread: ${m.spread.toFixed(decimals)}</div>
        </div>`;
    }).join('');
}


// ── Ticker Bar ──────────────────────────────────────────────────────
function updateTickerBar(containerId, marketData) {
    const el = document.getElementById(containerId);
    if (!el || !marketData) return;

    const items = marketData.map(m => {
        const isUp = m.change >= 0;
        const cls = isUp ? 'up' : 'down';
        const arrow = isUp ? '▲' : '▼';
        const decimals = m.symbol.includes('JPY') ? 3 : m.symbol.includes('BTC') ? 1 : m.symbol.includes('XAU') ? 2 : 5;
        return `<span class="ticker-item">
            <span class="ticker-symbol">${m.symbol}</span>
            <span class="ticker-price">${m.bid.toFixed(decimals)}</span>
            <span class="ticker-change ${cls}">${arrow}${Math.abs(m.change).toFixed(2)}%</span>
        </span>`;
    }).join('');

    // Duplicate for seamless scroll
    el.innerHTML = items + items;
}


// ── News Table ──────────────────────────────────────────────────────
const FLAG_MAP = {
    'US': '🇺🇸', 'EU': '🇪🇺', 'GB': '🇬🇧', 'JP': '🇯🇵',
    'AU': '🇦🇺', 'CA': '🇨🇦', 'CH': '🇨🇭', 'NZ': '🇳🇿',
    'CN': '🇨🇳', 'DE': '🇩🇪', 'FR': '🇫🇷',
};

function renderNewsTable(containerId, news) {
    const el = document.getElementById(containerId);
    if (!el || !news) return;

    let html = `<table class="news-table">
    <thead><tr>
        <th>Time</th><th>Event</th><th>Impact</th><th>Forecast</th><th>Previous</th>
    </tr></thead><tbody>`;

    news.forEach(ev => {
        const impactCls = ev.impact.toLowerCase();
        const flag = FLAG_MAP[ev.country] || '🌐';
        const timeStr = ev.time.length > 10 ? ev.time.substring(5) : ev.time;
        html += `<tr>
            <td class="time-col">${timeStr}</td>
            <td class="event-col"><span class="flag-emoji">${flag}</span>${ev.event}</td>
            <td><span class="impact-badge ${impactCls}">${ev.impact}</span></td>
            <td class="text-mono">${ev.forecast}</td>
            <td class="text-mono">${ev.previous}</td>
        </tr>`;
    });

    html += '</tbody></table>';
    el.innerHTML = html;
}


// ── TradingView Widget ──────────────────────────────────────────────
function initTradingViewWidget(containerId, symbol = 'OANDA:XAUUSD') {
    const el = document.getElementById(containerId);
    if (!el) return;

    el.innerHTML = '';
    const script = document.createElement('script');
    script.src = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';
    script.async = true;
    script.innerHTML = JSON.stringify({
        autosize: true,
        symbol: symbol,
        interval: '5',
        timezone: 'Etc/UTC',
        theme: 'dark',
        style: '1',
        locale: 'en',
        backgroundColor: '#111827',
        gridColor: 'rgba(30, 41, 59, 0.4)',
        hide_top_toolbar: false,
        hide_legend: false,
        allow_symbol_change: true,
        save_image: false,
        calendar: false,
        support_host: 'https://www.tradingview.com',
    });
    el.appendChild(script);
}

// ── Exports ─────────────────────────────────────────────────────────
window.Charts = {
    initEquityChart,
    updateEquityChart,
    renderHeatmap,
    renderMarketOverview,
    updateTickerBar,
    renderNewsTable,
    initTradingViewWidget,
};
