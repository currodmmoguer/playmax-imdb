const campanaSel = document.getElementById('campana');
const form = document.getElementById('form');
const lista = document.getElementById('lista');
const alertas = document.getElementById('alertas');

let currentTab = 'resumen';
let editingId = null;
let meta = { categorias: [] };
let me = null;
const cache = { fincas: [], sectores: [], trabajadores: [] };

async function api(path, opts = {}) {
  // La cabecera X-Requested-With es la protección CSRF que exige el servidor.
  opts.headers = { 'X-Requested-With': 'fresas' };
  if (opts.body && typeof opts.body !== 'string') {
    opts.body = JSON.stringify(opts.body);
    opts.headers['Content-Type'] = 'application/json';
  }
  const r = await fetch(path, opts);
  const data = await r.json();
  if (r.status === 401 && data.login && path !== '/api/login') showLogin();
  if (!r.ok) {
    const err = new Error(data.error || `Error HTTP ${r.status}`);
    err.status = r.status;
    err.data = data;
    throw err;
  }
  return data;
}

const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const num = (n, d = 0) => n == null ? '—' :
  Number(n).toLocaleString('es', { minimumFractionDigits: d, maximumFractionDigits: d });
const eur = n => n == null ? '—' :
  Number(n).toLocaleString('es', { style: 'currency', currency: 'EUR' });
const fecha = f => f ? f.split('-').reverse().join('/') : '—';
const today = () => new Date().toLocaleDateString('sv'); // AAAA-MM-DD en hora local

const byId = (list, id) => list.find(x => x.id === id);
const nombreFinca = id => byId(cache.fincas, id)?.nombre ?? '—';
const nombreSector = id => {
  const s = byId(cache.sectores, id);
  return s ? `${nombreFinca(s.finca_id)} · ${s.nombre}` : '—';
};
const nombreTrabajador = id => byId(cache.trabajadores, id)?.nombre ?? '—';

// ---------------------------------------------------------------- definición de pantallas

// Variedades habituales en Huelva (se pueden escribir otras).
const VARIEDADES = ['Fortuna', 'Rociera', 'Primoris', 'Sabrina', 'Calinda',
  'Marisol', 'Victory', 'Sabina', 'Fontanilla', 'Splendor', 'Florida Brilliance'];

const SCREENS = {
  recolecciones: {
    title: 'Registrar recolección',
    keep: ['fecha', 'sector_id', 'categoria'],
    fields: [
      { name: 'fecha', label: 'Fecha', type: 'date', required: true, default: today },
      { name: 'sector_id', label: 'Sector', type: 'sector', required: true },
      { name: 'trabajador_id', label: 'Trabajador', type: 'trabajador' },
      { name: 'categoria', label: 'Categoría', type: 'categoria', required: true },
      { name: 'cajas', label: 'Cajas', type: 'number', step: 1 },
      { name: 'kg', label: 'Kg', type: 'number', step: 0.1, required: true },
    ],
    columns: [
      ['Fecha', r => fecha(r.fecha)], ['Sector', r => nombreSector(r.sector_id)],
      ['Trabajador', r => nombreTrabajador(r.trabajador_id)], ['Categoría', r => r.categoria],
      ['Cajas', r => num(r.cajas), 'n'], ['Kg', r => num(r.kg, 1), 'n'],
    ],
    total: rs => `${num(rs.reduce((a, r) => a + r.kg, 0), 1)} kg en ${rs.length} registros`,
  },
  entregas: {
    title: 'Registrar entrega (albarán)',
    keep: ['fecha', 'destino'],
    fields: [
      { name: 'fecha', label: 'Fecha', type: 'date', required: true, default: today },
      { name: 'destino', label: 'Cooperativa / almacén', type: 'text', required: true, list: 'destinos' },
      { name: 'albaran', label: 'Nº albarán', type: 'text' },
      { name: 'categoria', label: 'Categoría', type: 'categoria', required: true },
      { name: 'kg', label: 'Kg', type: 'number', step: 0.1, required: true },
      { name: 'precio_kg', label: 'Precio €/kg (liquidación)', type: 'number', step: 0.001 },
    ],
    columns: [
      ['Fecha', r => fecha(r.fecha)], ['Destino', r => esc(r.destino)],
      ['Albarán', r => esc(r.albaran)], ['Categoría', r => r.categoria],
      ['Kg', r => num(r.kg, 1), 'n'], ['€/kg', r => r.precio_kg == null ? 'pendiente' : num(r.precio_kg, 3), 'n'],
      ['Importe', r => r.precio_kg == null ? '—' : eur(r.kg * r.precio_kg), 'n'],
    ],
    total: rs => `${num(rs.reduce((a, r) => a + r.kg, 0), 1)} kg · ` +
      eur(rs.reduce((a, r) => a + r.kg * (r.precio_kg || 0), 0)),
  },
  tratamientos: {
    title: 'Anotar tratamiento fitosanitario',
    keep: ['fecha', 'aplicador'],
    fields: [
      { name: 'fecha', label: 'Fecha', type: 'date', required: true, default: today },
      { name: 'sector_id', label: 'Sector', type: 'sector', required: true },
      { name: 'plaga', label: 'Plaga / problema', type: 'text', list: 'plagas' },
      { name: 'producto', label: 'Producto comercial', type: 'text', required: true },
      { name: 'num_registro', label: 'Nº registro', type: 'text' },
      { name: 'materia_activa', label: 'Materia activa', type: 'text' },
      { name: 'dosis', label: 'Dosis', type: 'text', placeholder: 'p. ej. 0,5 l/ha' },
      { name: 'plazo_seguridad_dias', label: 'Plazo de seguridad (días)', type: 'number', step: 1, default: () => 0 },
      { name: 'aplicador', label: 'Aplicador (carné)', type: 'text' },
    ],
    columns: [
      ['Fecha', r => fecha(r.fecha)], ['Sector', r => nombreSector(r.sector_id)],
      ['Plaga', r => esc(r.plaga)], ['Producto', r => esc(r.producto)],
      ['Nº reg.', r => esc(r.num_registro)], ['Dosis', r => esc(r.dosis)],
      ['P.S.', r => `${r.plazo_seguridad_dias} d`, 'n'],
      ['Recolectable', r => {
        const d = new Date(r.fecha);
        d.setDate(d.getDate() + r.plazo_seguridad_dias);
        const iso = d.toISOString().slice(0, 10);
        return iso > today() ? `<span class="bad">${fecha(iso)}</span>` : fecha(iso);
      }],
    ],
    export: ['Descargar cuaderno de campo (Excel)', '/api/export/cuaderno'],
  },
  sectores: {
    title: 'Sector / macrotúnel',
    fields: [
      { name: 'finca_id', label: 'Finca', type: 'finca', required: true },
      { name: 'nombre', label: 'Nombre', type: 'text', required: true, placeholder: 'p. ej. Túneles 1-12' },
      { name: 'variedad', label: 'Variedad', type: 'text', list: 'variedades' },
      { name: 'superficie_ha', label: 'Superficie (ha)', type: 'number', step: 0.01 },
      { name: 'plantas', label: 'Nº plantas', type: 'number', step: 1 },
      { name: 'fecha_plantacion', label: 'Fecha plantación', type: 'date' },
    ],
    columns: [
      ['Finca', r => esc(nombreFinca(r.finca_id))], ['Sector', r => esc(r.nombre)],
      ['Variedad', r => esc(r.variedad)], ['Ha', r => num(r.superficie_ha, 2), 'n'],
      ['Plantas', r => num(r.plantas), 'n'],
      ['Plantas/ha', r => r.plantas && r.superficie_ha ? num(r.plantas / r.superficie_ha) : '—', 'n'],
      ['Plantación', r => fecha(r.fecha_plantacion)],
    ],
  },
  fincas: {
    title: 'Finca',
    fields: [
      { name: 'nombre', label: 'Nombre', type: 'text', required: true },
      { name: 'municipio', label: 'Municipio', type: 'text', list: 'municipios' },
      { name: 'notas', label: 'Notas (polígono, parcela, REGA…)', type: 'text' },
    ],
    columns: [['Finca', r => esc(r.nombre)], ['Municipio', r => esc(r.municipio)], ['Notas', r => esc(r.notas)]],
  },
  trabajadores: {
    title: 'Trabajador',
    fields: [
      { name: 'nombre', label: 'Nombre', type: 'text', required: true },
      { name: 'dni', label: 'DNI / NIE', type: 'text' },
      { name: 'telefono', label: 'Teléfono', type: 'tel' },
      { name: 'cuadrilla', label: 'Cuadrilla', type: 'text' },
      { name: 'fecha_alta', label: 'Fecha de alta', type: 'date' },
      { name: 'activo', label: 'Activo', type: 'checkbox', default: () => true },
    ],
    columns: [
      ['Nombre', r => esc(r.nombre)], ['DNI/NIE', r => esc(r.dni)], ['Teléfono', r => esc(r.telefono)],
      ['Cuadrilla', r => esc(r.cuadrilla)], ['Alta', r => fecha(r.fecha_alta)],
      ['Estado', r => r.activo ? '<span class="ok">activo</span>' : 'baja'],
    ],
  },
  usuarios: {
    title: 'Usuario de la aplicación',
    noDelete: true, // se dan de baja desmarcando «Activo»
    fields: [
      { name: 'usuario', label: 'Usuario', type: 'text', required: true },
      { name: 'nombre', label: 'Nombre', type: 'text' },
      { name: 'rol', label: 'Rol', type: 'rol', required: true },
      { name: 'password', label: 'Contraseña (mín. 8)', editLabel: 'Nueva contraseña (vacío = no cambiar)',
        type: 'password', requiredNew: true, noFill: true },
      { name: 'activo', label: 'Activo', type: 'checkbox', default: () => true },
    ],
    columns: [
      ['Usuario', r => esc(r.usuario)], ['Nombre', r => esc(r.nombre)],
      ['Rol', r => r.rol === 'admin' ? 'Administrador' : 'Usuario'],
      ['Estado', r => r.activo ? '<span class="ok">activo</span>' : 'baja'],
    ],
  },
};

const SELECT_TYPES = ['categoria', 'finca', 'sector', 'trabajador', 'rol'];

const DATALISTS = {
  variedades: VARIEDADES,
  municipios: ['Moguer', 'Palos de la Frontera', 'Lepe', 'Cartaya', 'Almonte',
    'Bonares', 'Lucena del Puerto', 'Rociana del Condado', 'Isla Cristina', 'Gibraleón'],
  plagas: ['Araña roja', 'Trips', 'Pulgón', 'Oídio', 'Botrytis', 'Antracnosis',
    'Spodoptera', 'Mosca blanca', 'Phytophthora'],
  destinos: [],
};

// ---------------------------------------------------------------- formularios

function optionsFor(f) {
  const opt = (v, t) => `<option value="${v}">${esc(t)}</option>`;
  const blank = f.required ? '<option value="">— elige —</option>' : '<option value="">—</option>';
  if (f.type === 'categoria') return meta.categorias.map(c => opt(c, c)).join('');
  if (f.type === 'rol') return opt('usuario', 'Usuario (registra datos)') + opt('admin', 'Administrador (también gestiona usuarios)');
  if (f.type === 'finca') return blank + cache.fincas.map(x => opt(x.id, x.nombre)).join('');
  if (f.type === 'sector') return blank + cache.sectores.map(x => opt(x.id, nombreSector(x.id) +
    (x.variedad ? ` (${x.variedad})` : ''))).join('');
  if (f.type === 'trabajador') return blank + cache.trabajadores
    .filter(x => x.activo || x.id === Number(form.elements[f.name]?.value))
    .map(x => opt(x.id, x.nombre + (x.cuadrilla ? ` · ${x.cuadrilla}` : ''))).join('');
  return '';
}

function renderForm(screen, values = {}) {
  const lists = new Set();
  const inputs = screen.fields.map(f => {
    const required = f.required || (f.requiredNew && !editingId);
    const req = required ? 'required' : '';
    const label = editingId && f.editLabel ? f.editLabel : f.label;
    let input;
    if (SELECT_TYPES.includes(f.type)) {
      input = `<select name="${f.name}" ${req}>${optionsFor(f)}</select>`;
    } else if (f.type === 'checkbox') {
      input = `<input type="checkbox" name="${f.name}">`;
    } else {
      if (f.list) lists.add(f.list);
      input = `<input type="${f.type}" name="${f.name}" ${req}
        ${f.step ? `step="${f.step}" min="0" inputmode="decimal"` : ''}
        ${f.list ? `list="dl-${f.list}"` : ''} placeholder="${esc(f.placeholder || '')}"
        ${f.type === 'password' ? `minlength="8" autocomplete="new-password"` : ''}>`;
    }
    return `<label class="${f.type === 'checkbox' ? 'check' : ''}">${esc(label)}${required ? ' *' : ''}${input}</label>`;
  }).join('');
  const datalists = [...lists].map(l =>
    `<datalist id="dl-${l}">${DATALISTS[l].map(v => `<option value="${esc(v)}">`).join('')}</datalist>`).join('');
  form.innerHTML = `<h3>${editingId ? 'Editar' : 'Nuevo'}: ${esc(screen.title)}</h3>
    <div class="fields">${inputs}</div>${datalists}
    <div class="form-buttons">
      <button type="submit">${editingId ? 'Guardar cambios' : 'Añadir'}</button>
      ${editingId ? '<button type="button" class="secondary" id="cancel-edit">Cancelar</button>' : ''}
    </div>
    <p class="msg" id="form-msg"></p>`;
  for (const f of screen.fields) {
    const el = form.elements[f.name];
    if (f.noFill) continue;
    const v = f.name in values ? values[f.name] : f.default?.();
    if (f.type === 'checkbox') el.checked = !!v;
    else if (v != null) el.value = v;
  }
  document.getElementById('cancel-edit')?.addEventListener('click', () => {
    editingId = null;
    renderForm(screen);
  });
  // Primera vez sin datos maestros: avisar de lo que hay que dar de alta antes.
  const needs = screen.fields.filter(f => f.required && ['finca', 'sector'].includes(f.type))
    .map(f => f.type).find(t => cache[t === 'finca' ? 'fincas' : 'sectores'].length === 0);
  if (needs) formMsg(`Primero da de alta al menos ${needs === 'finca' ? 'una finca' : 'un sector'}.`, 'warn');
}

function formMsg(text, cls = '') {
  const el = document.getElementById('form-msg');
  el.className = `msg ${cls}`;
  el.textContent = text;
}

function readForm(screen) {
  const data = {};
  for (const f of screen.fields) {
    const el = form.elements[f.name];
    data[f.name] = f.type === 'checkbox' ? el.checked : el.value;
  }
  return data;
}

form.addEventListener('submit', async e => {
  e.preventDefault();
  const screen = SCREENS[currentTab];
  const data = readForm(screen);
  try {
    await save(data);
  } catch (err) {
    if (err.status === 409 && err.data?.plazo_seguridad &&
        confirm(`${err.message}\n\n¿Registrar la recolección igualmente?`)) {
      await save({ ...data, forzar: true }).catch(e2 => formMsg(e2.message, 'bad'));
      return;
    }
    formMsg(err.message, 'bad');
  }
});

async function save(data) {
  const screen = SCREENS[currentTab];
  const wasEditing = editingId;
  if (editingId) await api(`/api/${currentTab}/${editingId}`, { method: 'PUT', body: data });
  else await api(`/api/${currentTab}`, { method: 'POST', body: data });
  editingId = null;
  // Para meter muchos registros seguidos se conservan fecha, sector, etc.
  const kept = Object.fromEntries((screen.keep || []).map(k => [k, data[k]]));
  if (cache[currentTab]) await loadCache();
  if (currentTab === 'usuarios') await loadMe();
  if (currentTab === 'usuarios' && me.rol !== 'admin') return showTab('resumen');
  await loadList();
  renderForm(screen, wasEditing ? {} : kept);
  formMsg(wasEditing ? 'Cambios guardados.' : 'Registro añadido.', 'ok');
  form.elements.kg?.focus();
}

// ---------------------------------------------------------------- listados

let rowsCache = [];

async function loadList() {
  const screen = SCREENS[currentTab];
  rowsCache = await api(`/api/${currentTab}?campana=${encodeURIComponent(campanaSel.value)}`);
  if (currentTab === 'entregas') {
    DATALISTS.destinos = [...new Set(rowsCache.map(r => r.destino))];
  }
  if (!rowsCache.length) {
    lista.innerHTML = '<p class="empty">Todavía no hay registros.</p>';
    return;
  }
  const head = screen.columns.map(([t, , c]) => `<th class="${c || ''}">${t}</th>`).join('');
  const body = rowsCache.map(r => `<tr>${screen.columns.map(([, fn, c]) =>
    `<td class="${c || ''}">${fn(r)}</td>`).join('')}
    <td class="row-actions"><button class="link" data-edit="${r.id}">Editar</button>
    ${screen.noDelete ? '' : `<button class="link bad" data-del="${r.id}">Borrar</button>`}</td></tr>`).join('');
  lista.innerHTML = (screen.total ? `<p class="total">${screen.total(rowsCache)}</p>` : '') +
    `<div class="scroll"><table><thead><tr>${head}<th></th></tr></thead><tbody>${body}</tbody></table></div>`;
}

lista.addEventListener('click', async e => {
  const screen = SCREENS[currentTab];
  if (e.target.dataset.edit) {
    editingId = Number(e.target.dataset.edit);
    renderForm(screen, byId(rowsCache, editingId));
    form.scrollIntoView({ behavior: 'smooth' });
  } else if (e.target.dataset.del) {
    if (!confirm('¿Borrar este registro?')) return;
    try {
      await api(`/api/${currentTab}/${e.target.dataset.del}`, { method: 'DELETE' });
      if (cache[currentTab]) await loadCache();
      await loadList();
    } catch (err) {
      alert(err.message);
    }
  }
});

// ---------------------------------------------------------------- resumen

function bars(items, label, value, fmt) {
  const max = Math.max(...items.map(value), 1);
  if (!items.length) return '<p class="empty">Sin datos.</p>';
  return `<div class="bars">${items.map(i => `
    <div class="bar-row"><span class="bar-label">${label(i)}</span>
      <span class="bar"><span style="width:${(value(i) / max * 100).toFixed(1)}%"></span></span>
      <span class="bar-value">${fmt(value(i))}</span></div>`).join('')}</div>`;
}

function table(cols, items) {
  if (!items.length) return '<p class="empty">Sin datos.</p>';
  return `<div class="scroll"><table><thead><tr>${cols.map(([t, , c]) => `<th class="${c || ''}">${t}</th>`).join('')}</tr></thead>
    <tbody>${items.map(i => `<tr>${cols.map(([, fn, c]) => `<td class="${c || ''}">${fn(i)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

async function loadResumen() {
  const r = await api(`/api/resumen?campana=${encodeURIComponent(campanaSel.value)}`);
  const ha = r.por_sector.reduce((a, s) => a + (s.superficie_ha || 0), 0);
  document.getElementById('kpis').innerHTML = [
    ['Kg recolectados', num(r.recolectado.kg)],
    ['Días de recogida', num(r.recolectado.dias)],
    ['Kg / ha', ha ? num(r.recolectado.kg / ha) : '—'],
    ['Kg entregados', num(r.entregado.kg)],
    ['Importe liquidado', eur(r.entregado.importe)],
    ['Precio medio', r.entregado.precio_medio ? `${num(r.entregado.precio_medio, 3)} €/kg` : '—'],
  ].map(([t, v]) => `<div class="kpi"><span>${t}</span><strong>${v}</strong></div>`).join('');

  document.getElementById('chart-semana').innerHTML = bars(r.por_semana,
    s => `sem. ${fecha(s.semana).slice(0, 5)}`, s => s.kg, v => `${num(v)} kg`);
  const orden = meta.categorias;
  document.getElementById('chart-categoria').innerHTML = bars(
    [...r.por_categoria].sort((a, b) => orden.indexOf(a.categoria) - orden.indexOf(b.categoria)),
    c => c.categoria, c => c.kg,
    v => `${num(v)} kg (${num(v / (r.recolectado.kg || 1) * 100)} %)`);

  document.getElementById('tabla-sectores').innerHTML = table([
    ['Finca', s => esc(s.finca)], ['Sector', s => esc(s.sector)], ['Variedad', s => esc(s.variedad)],
    ['Ha', s => num(s.superficie_ha, 2), 'n'], ['Kg', s => num(s.kg), 'n'],
    ['Kg/ha', s => num(s.kg_ha), 'n'], ['g/planta', s => num(s.g_planta), 'n'],
  ], r.por_sector);
  document.getElementById('tabla-trabajadores').innerHTML = table([
    ['Nombre', t => esc(t.nombre)], ['Cuadrilla', t => esc(t.cuadrilla)],
    ['Días', t => num(t.dias), 'n'], ['Cajas', t => num(t.cajas), 'n'],
    ['Kg', t => num(t.kg), 'n'], ['Kg/día', t => num(t.kg_dia, 1), 'n'],
  ], r.por_trabajador);
  document.getElementById('tabla-entregas').innerHTML = table([
    ['Categoría', c => c.categoria], ['Kg', c => num(c.kg), 'n'],
    ['Precio medio', c => c.precio_medio == null ? '—' : `${num(c.precio_medio, 3)} €/kg`, 'n'],
    ['Importe', c => eur(c.importe), 'n'],
  ], r.entregado.por_categoria);
  document.getElementById('export-campana').href =
    `/api/export/campana?campana=${encodeURIComponent(campanaSel.value)}`;
}

async function loadAlertas() {
  const plazos = await api('/api/plazos');
  alertas.innerHTML = plazos.map(p => {
    const t = p.tratamientos[0];
    return `<div class="alerta">⚠️ <strong>${esc(nombreSector(p.sector_id))}</strong>: plazo de
      seguridad por «${esc(t.producto)}» — no recolectar hasta el <strong>${fecha(p.recolectable_desde)}</strong>.</div>`;
  }).join('');
}

// ---------------------------------------------------------------- navegación

async function loadCache() {
  [cache.fincas, cache.sectores, cache.trabajadores] = await Promise.all(
    ['fincas', 'sectores', 'trabajadores'].map(t => api(`/api/${t}`)));
}

async function showTab(tab) {
  currentTab = tab;
  editingId = null;
  document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  document.getElementById('tab-resumen').hidden = tab !== 'resumen';
  document.getElementById('tab-cuenta').hidden = tab !== 'cuenta';
  document.getElementById('tab-crud').hidden = !SCREENS[tab];
  try {
    await loadAlertas();
    if (tab === 'resumen') return await loadResumen();
    if (tab === 'cuenta') return;
    const screen = SCREENS[tab];
    await loadList();
    renderForm(screen);
    document.getElementById('crud-actions').innerHTML = screen.export ?
      `<a class="btn" href="${screen.export[1]}?campana=${encodeURIComponent(campanaSel.value)}">${screen.export[0]}</a>` : '';
  } catch (err) {
    alertas.innerHTML = `<div class="alerta bad">${esc(err.message)}</div>`;
  }
}

document.getElementById('tabs').addEventListener('click', e => {
  if (e.target.dataset.tab) showTab(e.target.dataset.tab);
});
campanaSel.addEventListener('change', () => showTab(currentTab));

// ---------------------------------------------------------------- sesión

const loginView = document.getElementById('login-view');
const appView = document.getElementById('app-view');
const loginForm = document.getElementById('login-form');

function showLogin() {
  me = null;
  appView.hidden = true;
  loginView.hidden = false;
  loginForm.elements.usuario.focus();
}

async function loadMe() {
  me = await api('/api/me');
  document.getElementById('user-name').textContent = me.nombre || me.usuario;
  document.querySelectorAll('[data-admin]').forEach(el => el.hidden = me.rol !== 'admin');
}

loginForm.addEventListener('submit', async e => {
  e.preventDefault();
  const msg = document.getElementById('login-msg');
  msg.textContent = '';
  try {
    await api('/api/login', { method: 'POST', body: {
      usuario: loginForm.elements.usuario.value, password: loginForm.elements.password.value } });
    loginForm.reset();
    await start();
  } catch (err) {
    msg.textContent = err.message;
  }
});

document.getElementById('logout').addEventListener('click', async () => {
  await api('/api/logout', { method: 'POST' }).catch(() => {});
  showLogin();
});

const passwordForm = document.getElementById('password-form');
passwordForm.addEventListener('submit', async e => {
  e.preventDefault();
  const el = passwordForm.elements;
  const msg = document.getElementById('password-msg');
  if (el.nueva.value !== el.repite.value) {
    msg.className = 'msg bad';
    msg.textContent = 'Las contraseñas nuevas no coinciden.';
    return;
  }
  try {
    await api('/api/me/password', { method: 'POST', body: { actual: el.actual.value, nueva: el.nueva.value } });
    passwordForm.reset();
    msg.className = 'msg ok';
    msg.textContent = 'Contraseña cambiada. Las demás sesiones abiertas se han cerrado.';
  } catch (err) {
    msg.className = 'msg bad';
    msg.textContent = err.message;
  }
});

async function start() {
  await loadMe();
  loginView.hidden = true;
  appView.hidden = false;
  meta = await api('/api/meta');
  campanaSel.innerHTML = meta.campanas.map(c => `<option>${c}</option>`).join('');
  campanaSel.value = meta.campana_actual;
  await loadCache();
  // Sin fincas todavía: empezar por darlas de alta.
  await showTab(cache.fincas.length ? 'resumen' : 'fincas');
}

start().catch(() => {});
