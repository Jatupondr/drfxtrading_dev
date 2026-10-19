/**
 * dashboard.js — DRFX Trading Dashboard Controller v4
 * Features: Cent/Dollar toggle, THB, drag & drop, rename, MaxDD
 */
(function () {
    'use strict';

    let ws = null, wsRetries = 0, isConnected = false;
    const MAX_RETRIES = 20;
    let sortColumn = null, sortDir = 'desc', lastData = null;

    // ── Currency Display Mode ────────────────────────────────────────
    let displayMode = 'cent';
    let exchangeRate = 34.50;
    let rateSource = '', rateUpdated = '';
    const MODE_KEY = 'drfx_display_mode';

    function loadMode() { try { const s=localStorage.getItem(MODE_KEY); if(s==='dollar') displayMode='dollar'; } catch(e){} updateModeUI(); }
    function updateModeUI() {
        const btnC=document.getElementById('btnCent'), btnD=document.getElementById('btnDollar'), lbl=document.getElementById('rateLabel');
        if(btnC&&btnD){
            if(displayMode==='cent'){ btnC.style.background='var(--blue-dim)';btnC.style.color='var(--text-accent)';btnC.style.fontWeight='600'; btnD.style.background='transparent';btnD.style.color='var(--text-muted)';btnD.style.fontWeight='500'; }
            else { btnD.style.background='var(--blue-dim)';btnD.style.color='var(--text-accent)';btnD.style.fontWeight='600'; btnC.style.background='transparent';btnC.style.color='var(--text-muted)';btnC.style.fontWeight='500'; }
        }
        if(lbl) lbl.textContent = displayMode==='cent' ? '1\u00A2 = \u0E3F' : '1$ = \u0E3F';
    }
    function toDisplay(v) { return displayMode==='dollar' ? (v||0)/100 : (v||0); }
    function toTHB(v) { return (v||0) * exchangeRate / 100; }
    function sym() { return displayMode==='dollar' ? '$' : '\u00A2'; }

    function fmtDisplay(v) { const d=toDisplay(v); return sym()+Math.abs(d).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}); }
    function fmtDisplay_PL(v) { const d=toDisplay(v); return (d>=0?'+'+sym():'-'+sym())+Math.abs(d).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}); }
    function fmtTHB(v) { const t=toTHB(v); return '\u0E3F'+Math.abs(t).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}); }
    function fmtTHB_PL(v) { const t=toTHB(v); return (t>=0?'+\u0E3F':'-\u0E3F')+Math.abs(t).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}); }
    function escapeHtml(t) { return (t||'').replace(/'/g,"\\'").replace(/"/g,'&quot;'); }

    function moneyCell(v) {
        return '<div>'+fmtDisplay(v)+'</div><div style="font-size:0.68rem;color:var(--amber)">'+fmtTHB(v)+'</div>';
    }

    // plCell — แสดง P/L + THB + % + DD (ถ้ามี)
    function plCell(v, bal, ddVal) {
        const cls = (v||0)>=0?'positive':'negative';
        const tc = toTHB(v)>=0?'var(--green)':'var(--red)';
        const pct = (bal&&bal>0) ? ((v||0)/bal*100).toFixed(2) : '0.00';
        const pctClr = (v||0)>=0?'var(--green)':'var(--red)';
        let html = '<div class="'+cls+'">'+fmtDisplay_PL(v)+'</div>'
            +'<div style="font-size:0.68rem;color:'+tc+'">'+fmtTHB_PL(v)
            +' <span style="color:'+pctClr+';opacity:0.8">('+(v>=0?'+':'')+pct+'%)</span></div>';
        // DD line (แสดงเฉพาะเมื่อ ddVal < 0)
        if(ddVal !== undefined && ddVal < 0) {
            const ddDisp = toDisplay(ddVal);
            const ddPct = (bal&&bal>0) ? (ddVal/bal*100).toFixed(2) : '0.00';
            html += '<div style="font-size:0.62rem;color:#f87171;opacity:0.85;margin-top:1px">'
                +'DD: -'+sym()+Math.abs(ddDisp).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})
                +' ('+ddPct+'%)</div>';
        }
        return html;
    }

    function updateRateDisplay() {
        const rateEl=document.getElementById('rateValue'), srcEl=document.getElementById('rateSource');
        if(rateEl) rateEl.textContent = exchangeRate.toFixed(4);
        if(srcEl&&rateSource){ const ago=rateUpdated?timeSince(rateUpdated):''; srcEl.textContent='Live'+(ago?' \u00B7 '+ago:''); srcEl.style.color='var(--green)'; }
    }
    function timeSince(iso) { try{const s=Math.floor((Date.now()-new Date(iso).getTime())/1000);if(s<60)return s+'s ago';if(s<3600)return Math.floor(s/60)+'m ago';return Math.floor(s/3600)+'h ago';}catch(e){return '';} }

    // ── Account Order ────────────────────────────────────────────────
    let accountOrder = [], dragSrcLogin = null;
    async function loadAccountOrder() { try{const r=await fetch('/api/order');const d=await r.json();accountOrder=d.order||[];}catch(e){} }
    async function saveAccountOrder() { try{await fetch('/api/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order:accountOrder})});}catch(e){} }
    function sortByCustomOrder(accounts) {
        if(!accountOrder.length) return accounts;
        const m={};accountOrder.forEach((l,i)=>{m[l]=i;});
        return [...accounts].sort((a,b)=>((a.login in m)?m[a.login]:9999)-((b.login in m)?m[b.login]:9999));
    }

    // ── Init ─────────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', async () => {
        loadMode(); await loadAccountOrder();
        Charts.initEquityChart('equityChart');
        Charts.initTradingViewWidget('tvWidget','OANDA:XAUUSD');
        setupNavigation(); setupTableSorting(); connectWebSocket();
        setTimeout(()=>{if(!isConnected)fetchSnapshot();},3000);
    });

    // ── WebSocket ────────────────────────────────────────────────────
    function connectWebSocket() {
        const proto=location.protocol==='https:'?'wss':'ws';
        ws=new WebSocket(proto+'://'+location.host+'/ws');
        ws.onopen=()=>{isConnected=true;wsRetries=0;setConnectionStatus(true);};
        ws.onmessage=(e)=>{try{const d=JSON.parse(e.data);lastData=d;render(d);}catch(x){}};
        ws.onclose=()=>{isConnected=false;setConnectionStatus(false);if(wsRetries<MAX_RETRIES){wsRetries++;setTimeout(connectWebSocket,Math.min(1000*Math.pow(1.5,wsRetries),30000));}};
        ws.onerror=()=>{ws.close();};
    }
    async function fetchSnapshot(){try{const r=await fetch('/api/snapshot');const d=await r.json();lastData=d;render(d);}catch(e){}}

    // ── Render ────────────────────────────────────────────────────────
    function render(data) {
        if(!data) return;
        if(data.usdthb&&data.usdthb.rate>0){exchangeRate=data.usdthb.rate;rateSource=data.usdthb.source||'';rateUpdated=data.usdthb.updated||'';updateRateDisplay();}
        updateStatCards(data.portfolio);
        updateAccountsTable(data.portfolio?.accounts||[]);
        Charts.updateEquityChart(data.equity_curves||{});
        Charts.updateTickerBar('tickerContent',data.market||[]);
        Charts.renderMarketOverview('marketOverview',data.market||[]);
        Charts.renderHeatmap('heatmapContainer',data.heatmap);
        Charts.renderNewsTable('newsContainer',data.news||[]);
        updateTimestamp(data.timestamp);
        updateDemoBadge(data.demo_mode);
    }

    // ── Stat cards ───────────────────────────────────────────────────
    function updateStatCards(p) {
        if(!p) return;
        const bal=p.total_balance||0;
        setCardValue('totalBalance',p.total_balance,false,0);
        setCardValue('totalEquity',p.total_equity,false,0);
        setCardValue('totalProfit',p.total_profit,true,bal);
        setCardValue('todayProfit',p.today_profit,true,bal);
        setCardValue('yesterdayProfit',p.yesterday_profit,true,bal);
        setCardValue('weeklyProfit',p.weekly_profit,true,bal);
        setCardValue('monthlyProfit',p.monthly_profit,true,bal);
        const yDate=(p.accounts||[]).find(a=>a.yesterday_date)?.yesterday_date||'';
        const yEl=document.getElementById('yesterdayDate');
        if(yEl&&yDate) yEl.textContent=yDate;
    }

    function setCardValue(id,value,colored,bal) {
        const el=document.getElementById(id); if(!el) return;
        const v=value||0, d=toDisplay(v), s=sym();
        const main=(d>=0?(colored?'+'+s:s):'-'+s)+Math.abs(d).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
        const thb=colored?fmtTHB_PL(v):fmtTHB(v);
        const thbClr=colored?(toTHB(v)>=0?'var(--green)':'var(--red)'):'var(--amber)';
        let pctStr='';
        if(colored&&bal>0){const pct=(v/bal*100).toFixed(2);pctStr=' <span style="opacity:0.8">('+(v>=0?'+':'')+pct+'%)</span>';}
        el.innerHTML=main+'<div style="font-size:0.72rem;color:'+thbClr+';font-weight:500;margin-top:2px">'+thb+pctStr+'</div>';
        if(colored){el.classList.remove('positive','negative');el.classList.add(v>=0?'positive':'negative');}
    }

    // ── Accounts table with DD ───────────────────────────────────────
    function updateAccountsTable(accounts) {
        const tbody=document.getElementById('accountsTableBody'); if(!tbody) return;
        let sorted;
        if(sortColumn) sorted=[...accounts].sort((a,b)=>{const aV=a[sortColumn]||0,bV=b[sortColumn]||0;return sortDir==='desc'?bV-aV:aV-bV;});
        else sorted=sortByCustomOrder(accounts);

        tbody.innerHTML = sorted.map(acct => {
            const sCls=acct.connected?'online':'offline', sTxt=acct.connected?'Connected':'Offline';
            const yD=acct.yesterday_date||'', yV=acct.yesterday||0, bal=acct.balance||0;
            const ddT=acct.max_dd_today||0, ddY=acct.max_dd_yesterday||0, ddW=acct.max_dd_week||0, ddM=acct.max_dd_month||0;
            return '<tr draggable="true" data-login="'+acct.login+'" style="cursor:grab">'
                +'<td>'
                    +'<div style="display:flex;align-items:center;gap:6px">'
                        +'<span style="cursor:grab;opacity:0.3;font-size:0.85rem" title="Drag to reorder">\u2630</span>'
                        +'<span style="font-weight:600;color:var(--text-primary);cursor:pointer" onclick="renameAccount('+acct.login+',\''+escapeHtml(acct.label)+'\')" title="Click to rename">'+acct.label+'</span>'
                        +'<span style="cursor:pointer;opacity:0.4;font-size:0.7rem" onclick="renameAccount('+acct.login+',\''+escapeHtml(acct.label)+'\')">\u270F\uFE0F</span>'
                    +'</div>'
                    +'<div style="font-size:0.68rem;color:var(--text-muted);margin-left:22px">'+acct.login+'</div>'
                +'</td>'
                +'<td>'+moneyCell(acct.equity)+'</td>'
                +'<td>'+moneyCell(acct.balance)+'</td>'
                +'<td>'+plCell(acct.today, bal, ddT)+'</td>'
                +'<td>'+plCell(yV, bal, ddY)+'<div style="font-size:0.6rem;color:var(--text-muted);margin-top:1px">'+yD+'</div></td>'
                +'<td>'+plCell(acct.weekly, bal, ddW)+'</td>'
                +'<td>'+plCell(acct.monthly, bal, ddM)+'</td>'
                +'<td><span class="status-badge '+sCls+'"><span class="status-dot" style="width:6px;height:6px"></span>'+sTxt+'</span></td>'
                +'<td style="white-space:nowrap">'
                    +'<button class="action-btn" onclick="viewAccount(\''+acct.login+'\')" style="margin-right:4px">View</button>'
                    +'<button class="action-btn" onclick="deleteAccount('+acct.login+',\''+escapeHtml(acct.label)+'\')" style="color:var(--red);border-color:rgba(239,68,68,0.3)" title="Remove from dashboard">\u2715</button>'
                +'</td>'
            +'</tr>';
        }).join('');
        setupDragAndDrop(tbody);
    }

    function setupDragAndDrop(tbody) {
        tbody.querySelectorAll('tr[draggable]').forEach(row => {
            row.addEventListener('dragstart',(e)=>{dragSrcLogin=parseInt(row.getAttribute('data-login'));row.style.opacity='0.4';e.dataTransfer.effectAllowed='move';});
            row.addEventListener('dragend',()=>{row.style.opacity='1';tbody.querySelectorAll('tr').forEach(r=>{r.style.borderTop='';r.style.borderBottom='';});});
            row.addEventListener('dragover',(e)=>{
                e.preventDefault();e.dataTransfer.dropEffect='move';
                const rect=row.getBoundingClientRect(),mid=rect.top+rect.height/2;
                tbody.querySelectorAll('tr').forEach(r=>{r.style.borderTop='';r.style.borderBottom='';});
                if(e.clientY<mid) row.style.borderTop='2px solid var(--blue)'; else row.style.borderBottom='2px solid var(--blue)';
            });
            row.addEventListener('dragleave',()=>{row.style.borderTop='';row.style.borderBottom='';});
            row.addEventListener('drop',(e)=>{
                e.preventDefault();row.style.borderTop='';row.style.borderBottom='';
                const tl=parseInt(row.getAttribute('data-login'));if(dragSrcLogin===tl)return;
                const cur=[];tbody.querySelectorAll('tr[data-login]').forEach(r=>{cur.push(parseInt(r.getAttribute('data-login')));});
                const si=cur.indexOf(dragSrcLogin);if(si>-1)cur.splice(si,1);
                const rect=row.getBoundingClientRect(),mid=rect.top+rect.height/2;
                let ti=cur.indexOf(tl);if(e.clientY>mid)ti+=1;
                cur.splice(ti,0,dragSrcLogin);accountOrder=cur;sortColumn=null;saveAccountOrder();
                if(lastData?.portfolio?.accounts)updateAccountsTable(lastData.portfolio.accounts);
            });
        });
    }

    // ── Table sorting / Navigation / Status ──────────────────────────
    function setupTableSorting(){document.querySelectorAll('.data-table thead th[data-sort]').forEach(th=>{th.addEventListener('click',()=>{const col=th.getAttribute('data-sort');if(sortColumn===col)sortDir=sortDir==='desc'?'asc':'desc';else{sortColumn=col;sortDir='desc';}document.querySelectorAll('.data-table thead th').forEach(h=>h.classList.remove('sorted'));th.classList.add('sorted');const icon=th.querySelector('.sort-icon');if(icon)icon.textContent=sortDir==='desc'?'\u25BC':'\u25B2';if(lastData)updateAccountsTable(lastData.portfolio?.accounts||[]);});});}
    function setupNavigation(){document.querySelectorAll('.nav-item').forEach(item=>{item.addEventListener('click',()=>{document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));item.classList.add('active');const el=document.getElementById(item.getAttribute('data-section'));if(el)el.scrollIntoView({behavior:'smooth',block:'start'});});});}
    function setConnectionStatus(c){const d=document.getElementById('wsStatusDot'),t=document.getElementById('wsStatusText');if(d)d.classList.toggle('offline',!c);if(t)t.textContent=c?'WebSocket Live':'Reconnecting...';}
    function updateTimestamp(ts){const el=document.getElementById('lastUpdate');if(el&&ts)el.textContent='Updated: '+new Date(ts).toLocaleTimeString();}
    function updateDemoBadge(isDemo){const el=document.getElementById('modeBadge');if(!el)return;if(isDemo){el.textContent='DEMO MODE';el.classList.remove('live');}else{el.textContent='LIVE';el.classList.add('live');}}

    // ── Global helpers ───────────────────────────────────────────────
    window.viewAccount=function(login){const el=document.getElementById('section-equity');if(el)el.scrollIntoView({behavior:'smooth'});};
    window.changeChartSymbol=function(s){Charts.initTradingViewWidget('tvWidget',s);};
    window.toggleCurrency=function(mode){displayMode=mode;try{localStorage.setItem(MODE_KEY,mode);}catch(e){}updateModeUI();updateRateDisplay();if(lastData)render(lastData);};

    window.renameAccount=async function(login,currentName){
        const n=prompt('\u0E15\u0E31\u0E49\u0E07\u0E0A\u0E37\u0E48\u0E2D\u0E1A\u0E31\u0E0D\u0E0A\u0E35 '+login+':',currentName);
        if(n===null)return;const t=n.trim();
        if(!t){if(confirm('\u0E25\u0E1A\u0E0A\u0E37\u0E48\u0E2D\u0E17\u0E35\u0E48\u0E15\u0E31\u0E49\u0E07\u0E40\u0E2D\u0E07?'))try{await fetch('/api/labels/'+login,{method:'DELETE'});}catch(e){}return;}
        if(t.length>50){alert('\u0E0A\u0E37\u0E48\u0E2D\u0E22\u0E32\u0E27\u0E40\u0E01\u0E34\u0E19\u0E44\u0E1B');return;}
        try{const r=await fetch('/api/labels/'+login,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:t})});const d=await r.json();if(d.status==='ok'&&lastData?.portfolio?.accounts){const a=lastData.portfolio.accounts.find(x=>x.login===login);if(a)a.label=t;updateAccountsTable(lastData.portfolio.accounts);}}catch(e){alert('\u0E44\u0E21\u0E48\u0E2A\u0E32\u0E21\u0E32\u0E23\u0E16\u0E40\u0E1B\u0E25\u0E35\u0E48\u0E22\u0E19\u0E0A\u0E37\u0E48\u0E2D\u0E44\u0E14\u0E49');}
    };

    window.deleteAccount=async function(login, label) {
        if(!confirm('\u0E25\u0E1A\u0E1A\u0E31\u0E0D\u0E0A\u0E35 "'+label+'" ('+login+') \u0E2D\u0E2D\u0E01\u0E08\u0E32\u0E01 Dashboard?\n\n\u0E16\u0E49\u0E32 EA \u0E22\u0E31\u0E07\u0E23\u0E31\u0E19\u0E2D\u0E22\u0E39\u0E48 \u0E1A\u0E31\u0E0D\u0E0A\u0E35\u0E08\u0E30\u0E01\u0E25\u0E31\u0E1A\u0E21\u0E32\u0E43\u0E19\u0E23\u0E2D\u0E1A\u0E16\u0E31\u0E14\u0E44\u0E1B')) return;
        try {
            const r = await fetch('/api/ea/account/'+login, {method:'DELETE'});
            const d = await r.json();
            if(d.status==='ok') {
                // ลบออกจาก lastData ทันที
                if(lastData?.portfolio?.accounts) {
                    lastData.portfolio.accounts = lastData.portfolio.accounts.filter(a=>a.login!==login);
                    render(lastData);
                }
            } else {
                alert(d.error || 'Error');
            }
        } catch(e) { alert('\u0E44\u0E21\u0E48\u0E2A\u0E32\u0E21\u0E32\u0E23\u0E16\u0E25\u0E1A\u0E44\u0E14\u0E49'); }
    };
})();
