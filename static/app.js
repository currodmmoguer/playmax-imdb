const results = document.getElementById('results');
const moreBtn = document.getElementById('more-btn');
const statusBar = document.getElementById('status-bar');

let exploreStart = 0;
let mode = 'explore'; // 'explore' | 'search'

async function api(path, opts) {
  const r = await fetch(path, opts);
  const data = await r.json();
  if (!r.ok) throw new Error(data.error || `Error HTTP ${r.status}`);
  return data;
}

// ---------------------------------------------------------------- estado

async function checkStatus() {
  try {
    const s = await api('/api/status');
    const parts = [];
    if (s.playmax.ok) {
      parts.push('<span class="ok">● Playmax conectado</span>');
    } else if (s.playmax.needsAuth) {
      parts.push('<span class="warn">● Playmax: necesita tu autorización <button onclick="authorizeApp()">Autorizar app</button></span>');
    } else {
      parts.push(`<span class="bad">● Playmax: ${s.playmax.message}</span>`);
    }
    if (s.imdb.status === 'ready') {
      parts.push(`<span class="ok">● IMDb: ${Number(s.imdb.rows).toLocaleString('es')} títulos (act. ${s.imdb.updated || '—'})</span>`);
    } else if (s.imdb.status === 'loading') {
      parts.push('<span class="warn">● IMDb: descargando dataset…</span>');
      setTimeout(checkStatus, 5000);
    } else if (s.imdb.status === 'error') {
      parts.push(`<span class="bad">● IMDb: ${s.imdb.error} <button onclick="retryImdb()">Reintentar</button></span>`);
    } else {
      parts.push('<span class="warn">● IMDb: dataset no cargado</span>');
    }
    statusBar.innerHTML = parts.join(' ');
  } catch (e) {
    statusBar.innerHTML = `<span class="bad">● Servidor no disponible: ${e.message}</span>`;
  }
}

async function retryImdb() {
  await api('/api/imdb/update', { method: 'POST' });
  checkStatus();
}

async function authorizeApp() {
  try {
    const data = await api('/api/auth/start', { method: 'POST' });
    window.open(data.authUrl, '_blank');
    statusBar.innerHTML = '<span class="warn">● Autoriza la app en la pestaña abierta y pulsa <button onclick="checkStatus().then(()=>explore())">Ya he autorizado</button></span>';
  } catch (e) {
    statusBar.innerHTML = `<span class="bad">● Error solicitando autorización: ${e.message}</span>`;
  }
}

// ---------------------------------------------------------------- listados

function fichaCard(f) {
  const rating = f.rating ? Number(f.rating).toFixed(1) : '—';
  return `<article class="card" onclick="openDetail(${f.id})">
    <img loading="lazy" src="${f.poster || ''}" alt="" onerror="this.style.visibility='hidden'">
    <div class="card-info">
      <h3>${f.title}</h3>
      <p>${f.type || ''} ${f.year ? '· ' + f.year : ''}</p>
      <p class="pm-rating">★ ${rating} <small>(${f.votes ?? 0} votos en Playmax)</small></p>
    </div>
  </article>`;
}

function render(fichas, append) {
  const html = fichas.map(fichaCard).join('');
  if (append) results.insertAdjacentHTML('beforeend', html);
  else results.innerHTML = html || '<p class="empty">Sin resultados</p>';
}

async function explore(append = false) {
  mode = 'explore';
  if (!append) exploreStart = 0;
  const type = document.getElementById('filter-type').value;
  const order = document.getElementById('filter-order').value;

  try {
    let data;
    if (order === 'imdb') {
      // IMDb: mostrar mejor valoradas de IMDb (con datos de Playmax)
      const q = new URLSearchParams({ start: exploreStart, limit: 24 });
      if (type) q.set('type', type);
      data = await api(`/api/explore_imdb?${q}`);
      // Ya vienen con datos de Playmax, solo usar directamente
    } else {
      // Playmax: explore normal
      const q = new URLSearchParams({ order, start: exploreStart, limit: 24 });
      if (type) q.set('type', type);
      data = await api(`/api/explore?${q}`);
    }
    render(data.fichas, append);
    exploreStart = data.pagination?.next ?? exploreStart + 24;
    moreBtn.hidden = !data.fichas.length;
  } catch (e) {
    if (!append) results.innerHTML = `<p class="empty">⚠ ${e.message}</p>`;
  }
}

async function search(q) {
  mode = 'search';
  moreBtn.hidden = true;
  try {
    const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
    render(data.fichas, false);
  } catch (e) {
    results.innerHTML = `<p class="empty">⚠ ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------- detalle

function ratingBlock(label, rating, votes, link) {
  const value = rating != null ? Number(rating).toFixed(1) : '—';
  const v = votes != null ? `${Number(votes).toLocaleString('es')} votos` : 'sin datos';
  const inner = `<div class="score">${value}</div><div class="site">${label}</div><div class="votes">${v}</div>`;
  return link
    ? `<a class="rating-box" href="${link}" target="_blank" rel="noopener">${inner}</a>`
    : `<div class="rating-box">${inner}</div>`;
}

async function openDetail(id) {
  const dlg = document.getElementById('detail');
  const body = document.getElementById('detail-body');
  body.innerHTML = '<p class="empty">Cargando…</p>';
  dlg.showModal();
  try {
    const f = await api(`/api/ficha/${id}`);
    let comparison = '';
    if (f.difference != null) {
      const d = f.difference;
      const cls = d > 0 ? 'pm-wins' : d < 0 ? 'imdb-wins' : 'tie';
      const text = d > 0
        ? `Playmax la valora ${d.toFixed(1)} puntos más alto`
        : d < 0
          ? `IMDb la valora ${Math.abs(d).toFixed(1)} puntos más alto`
          : 'Misma valoración en ambos sitios';
      comparison = `<p class="diff ${cls}">${text}</p>`;
    } else if (!f.imdbId) {
      comparison = '<p class="diff none">Esta ficha no tiene enlace a IMDb en Playmax</p>';
    } else if (f.imdbDbStatus !== 'ready') {
      comparison = '<p class="diff none">El dataset de IMDb aún se está cargando…</p>';
    } else {
      comparison = '<p class="diff none">Sin valoración en el dataset de IMDb</p>';
    }

    body.innerHTML = `
      <div class="detail-head">
        <img src="${f.poster || ''}" alt="" onerror="this.style.display='none'">
        <div>
          <h2>${f.title} ${f.year ? `<small>(${f.year})</small>` : ''}</h2>
          <p class="orig">${f.originalTitle || ''}</p>
          <p>${f.type || ''}${f.imdbId ? ` · <a href="${f.imdbUrl}" target="_blank" rel="noopener">${f.imdbId}</a>` : ''}</p>
        </div>
      </div>
      <div class="ratings">
        ${ratingBlock('Playmax', f.playmax.rating, f.playmax.votes)}
        ${ratingBlock('IMDb', f.imdb?.rating, f.imdb?.votes, f.imdbUrl)}
      </div>
      ${comparison}
      ${f.sinopsis ? `<p class="sinopsis">${f.sinopsis}</p>` : ''}`;
  } catch (e) {
    body.innerHTML = `<p class="empty">⚠ ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------- mis fichas

const MARK_LABELS = {
  following: 'Siguiendo', pending: 'Pendiente', favorite: 'Favorita',
  viewed: 'Vista', abandoned: 'Abandonada',
};

let myRows = [];
let mySort = { key: 'pm', dir: -1 };
let resolving = false;

function showView(view) {
  const mine = view === 'mine';
  document.getElementById('myfichas').hidden = !mine;
  results.hidden = mine;
  moreBtn.hidden = mine || mode !== 'explore';
}

function sortValue(r, key) {
  switch (key) {
    case 'pm': return r.playmax?.rating ?? null;
    case 'imdb': return r.imdb?.rating ?? null;
    case 'diff':
      return (r.playmax?.rating != null && r.imdb?.rating != null)
        ? r.playmax.rating - r.imdb.rating : null;
    case 'marked': return MARK_LABELS[r.marked] || r.marked || null;
    default: return r[key] ?? null;
  }
}

function renderMy() {
  const group = document.getElementById('my-group').value;
  const state = document.getElementById('my-state').value;
  const seriesStatus = document.getElementById('my-series-status').value;
  let rows = myRows.filter(r => {
    if (group && r.group !== group) return false;
    if (state && r.marked !== state) return false;
    if (seriesStatus) {
      // Filtrar por status de serie (aplica a series y documentales que son series)
      const hasSeriesStatus = (r.group === 'series' || r.group === 'documentary') && r.status === seriesStatus;
      return hasSeriesStatus;
    }
    return true;
  });

  // Mostrar/ocultar select de status de series
  const statusSelect = document.getElementById('my-series-status');
  statusSelect.style.display = (group === 'series' || group === 'documentary' || !group) ? 'block' : 'none';

  const { key, dir } = mySort;
  rows.sort((a, b) => {
    const va = sortValue(a, key), vb = sortValue(b, key);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;            // los nulos siempre al final
    if (vb == null) return -1;
    if (typeof va === 'string') return dir * va.localeCompare(vb, 'es');
    return dir * (va - vb);
  });

  document.querySelectorAll('#my-table th').forEach(th => {
    th.classList.toggle('sorted', th.dataset.key === key);
    th.dataset.dir = th.dataset.key === key ? (dir > 0 ? '↑' : '↓') : '';
  });

  const fmt = (v, dec = 1) => v != null ? Number(v).toFixed(dec) : '—';
  document.querySelector('#my-table tbody').innerHTML = rows.map(r => {
    const diff = sortValue(r, 'diff');
    const diffCls = diff == null ? '' : diff > 0 ? 'pos' : diff < 0 ? 'neg' : '';
    const imdbCell = r.imdb
      ? fmt(r.imdb.rating)
      : r.resolved ? '<span class="muted">—</span>' : '<span class="muted">…</span>';
    const statusLabel = r.status
      ? r.status === 'finished' ? '✓ Finalizada'
      : r.status === 'waiting for new season' ? '⏳ Esperando'
      : r.status === 'in production' ? '🎬 En prod.'
      : r.status === 'cancelled' ? '✕ Cancelada'
      : r.status
      : '—';
    return `<tr onclick="openDetail(${r.id})">
      <td class="t-title"><img loading="lazy" src="${r.poster || ''}" alt=""> ${r.title}
        <small>${r.type || ''}</small></td>
      <td>${r.year ?? '—'}</td>
      <td>${MARK_LABELS[r.marked] || r.marked || '—'}</td>
      <td>${statusLabel}</td>
      <td>${r.myRating ? fmt(r.myRating, 0) : '—'}</td>
      <td class="num">${fmt(r.playmax?.rating)}</td>
      <td class="num">${imdbCell}</td>
      <td class="num ${diffCls}">${diff != null ? (diff > 0 ? '+' : '') + diff.toFixed(1) : '—'}</td>
    </tr>`;
  }).join('') || '<tr><td colspan="8" class="empty">Sin fichas con estos filtros</td></tr>';
}

async function resolveImdb() {
  if (resolving) return;
  resolving = true;
  const progress = document.getElementById('my-progress');
  try {
    const pending = myRows.filter(r => !r.resolved).map(r => r.id);
    const total = myRows.length;
    for (let i = 0; i < pending.length; i += 15) {
      progress.textContent = `Resolviendo IMDb… ${total - pending.length + i}/${total}`;
      const res = await api('/api/imdb/resolve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: pending.slice(i, i + 15) }),
      });
      for (const [id, v] of Object.entries(res)) {
        const row = myRows.find(r => r.id === Number(id));
        if (row && !v.error) {
          row.resolved = true;
          row.imdbId = v.imdbId;
          row.imdb = v.imdb;
        }
      }
      renderMy();
    }
    progress.textContent = '';
  } catch (e) {
    progress.textContent = `⚠ ${e.message}`;
  } finally {
    resolving = false;
  }
}

async function loadMyFichas() {
  showView('mine');
  const tbody = document.querySelector('#my-table tbody');
  tbody.innerHTML = '<tr><td colspan="8" class="empty">Cargando tus fichas…</td></tr>';
  try {
    const data = await api('/api/my_fichas');
    myRows = data.fichas;
    renderMy();
    resolveImdb();

    // Cargar status de series en background (sin bloquear)
    const seriesIds = myRows.filter(r => r.group === 'series' && !r.status).map(r => r.id);
    if (seriesIds.length > 0) {
      const loadingEl = document.getElementById('series-status-loading');
      loadingEl.style.display = 'inline';

      // Cargar en lotes de 5 para no abrumar la API
      (async () => {
        try {
          for (let i = 0; i < seriesIds.length; i += 5) {
            const batch = seriesIds.slice(i, i + 5);
            const statusData = await api('/api/series-status', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ ids: batch }),
            });
            for (const [id, status] of Object.entries(statusData)) {
              const row = myRows.find(r => r.id === Number(id));
              if (row) row.status = status;
            }
            renderMy();
          }
        } catch (e) {
          console.error('Error cargando status de series:', e);
        } finally {
          loadingEl.style.display = 'none';
        }
      })();
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="8" class="empty">⚠ ${e.message}</td></tr>`;
  }
}

async function exportFichas() {
  const group = document.getElementById('my-group').value;
  const state = document.getElementById('my-state').value;
  const rows = myRows.filter(r =>
    (!group || r.group === group) && (!state || r.marked === state));
  if (!rows.length) {
    alert('No hay fichas para exportar con estos filtros');
    return;
  }
  try {
    const res = await fetch('/api/export/fichas', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fichas: rows }),
    });
    if (!res.ok) throw new Error(await res.text());
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `fichas_${new Date().toISOString().split('T')[0]}.xlsx`;
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    alert(`Error al exportar: ${e.message}`);
  }
}

document.getElementById('mine-btn').addEventListener('click', loadMyFichas);
document.getElementById('export-btn').addEventListener('click', exportFichas);
document.getElementById('my-group').addEventListener('change', () => {
  const group = document.getElementById('my-group').value;
  // Limpiar filtro de estado de serie si no es Series ni Documentales
  if (group && group !== 'series' && group !== 'documentary') {
    document.getElementById('my-series-status').value = '';
  }
  renderMy();
});
document.getElementById('my-state').addEventListener('change', renderMy);
document.getElementById('my-series-status').addEventListener('change', renderMy);
document.querySelectorAll('#my-table th').forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.key;
    if (mySort.key === key) mySort.dir *= -1;
    else mySort = { key, dir: key === 'title' ? 1 : -1 };
    renderMy();
  });
});

// ---------------------------------------------------------------- eventos

document.getElementById('search-form').addEventListener('submit', (e) => {
  e.preventDefault();
  const q = document.getElementById('search-input').value.trim();
  if (q.length >= 2) { showView('catalog'); search(q); }
});
document.getElementById('explore-btn').addEventListener('click', () => { showView('catalog'); explore(false); });
moreBtn.addEventListener('click', () => { if (mode === 'explore') explore(true); });

checkStatus();
explore();
