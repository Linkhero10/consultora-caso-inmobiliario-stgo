#!/usr/bin/env python3
"""Genera el dashboard público único (una sola página, cuatro pestañas).

Consume el dataset de presentación de `dashboard_data.py` y las etiquetas
humanas de `config/dashboard_labels.json`. No decide qué contar ni cómo
agrupar -- eso vive en `dashboard_data.py`; este script solo arma el HTML.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_data import build_dashboard_dataset  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = PROJECT_ROOT / "config" / "dashboard_labels.json"
OUTPUT_PATH = PROJECT_ROOT / "docs" / "index.html"

BASEMAP = {
    "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
    "attribution": "&copy; <a href=\"https://www.openstreetmap.org/copyright\">OpenStreetMap</a> contributors",
}

METHODOLOGY_HTML = """
<h2>Metodología</h2>
<p>El corpus se construye en tres etapas verificables: descubrimiento de artículos de prensa
(discovery), clasificación con un gate determinista que exige evidencia literal citada
(classify), y enriquecimiento de actores/instituciones/hitos con citas verificadas
(enrich). Las afirmaciones documentales extraídas mediante LLM (actores, hitos, citas) se
respaldan con evidencia verificada contra el documento fuente. Las métricas territoriales
(población, hacinamiento) y las identidades de actor resueltas provienen de las capas
estructuradas y fuentes externas documentadas del warehouse (Censo 2024 INE, registro de
identidad de instituciones), no de una cita literal individual.</p>
<p>Los conflictos se agrupan a partir de casos individuales cuando la evidencia documental
permite establecer que corresponden al mismo fenómeno (mismo proyecto, mismos actores,
mismo objeto de disputa). La confianza de cada agrupación queda registrada explícitamente
(derivada mecánicamente vs. revisión manual).</p>
<p>El detalle de cada conflicto (documentos, actores, línea de tiempo, evidencia) muestra por
defecto solo las menciones con rol focal o co-principal sobre un caso único -- el mismo
criterio "seguro" documentado en <code>docs/methodology.md</code>. Otras menciones del mismo
conflicto (contextuales, panorámicas o sin revisar) se listan aparte y no aportan actores,
eventos ni evidencia al detalle principal.</p>
<p>Las comunas mostradas en el mapa corresponden a la Provincia de Santiago (32 comunas), con
datos poblacionales y de hacinamiento del Censo 2024 (INE). Un conflicto solo se asocia a una
comuna cuando al menos uno de sus documentos focales tiene una única comuna resuelta entre sus
menciones de caso; si un documento mezcla más de una comuna, no se le atribuye ninguna --se
prefiere "sin comuna resuelta" antes que asignar por aproximación.</p>
"""

ARCHITECTURE_HTML = """
<h2>Arquitectura del pipeline</h2>
<p>Descubrimiento (búsqueda de artículos) &rarr; clasificación (gate determinista +
evidencia verificada) &rarr; enriquecimiento (actores, instituciones, hitos) &rarr;
resolución de proyectos y agrupación de conflictos &rarr; este dashboard.</p>
<p>Cada etapa escribe a una base SQLite versionada (<code>data/warehouse.sqlite</code> en
esta release), que es la única fuente de datos para este dashboard -- no hay una copia
paralela ni un snapshot congelado.</p>
"""

INICIO_HTML = """
<h2>Conflictividad inmobiliaria en Santiago</h2>
<p>Portafolio técnico: pipeline de scraping, clasificación LLM con evidencia verificada, y
análisis territorial de conflictos inmobiliarios y urbanos en la Provincia de Santiago,
Chile.</p>
<p>Usa las pestañas de arriba para explorar el contexto (mapa y conflictos), la metodología,
y la arquitectura del pipeline.</p>
"""


def _load_labels() -> dict:
    return json.loads(LABELS_PATH.read_text(encoding="utf-8"))


def build_html(dataset: dict, labels: dict) -> str:
    payload = json.dumps({"dataset": dataset, "labels": labels, "basemap": BASEMAP}, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Conflictividad inmobiliaria en Santiago</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
<style>
:root{{--ink:#17212b;--muted:#667085;--line:#d9dee7;--bg:#f6f7f9;--card:#fff;--accent:#0b7285}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);font:14px system-ui,-apple-system,Segoe UI,sans-serif;color:var(--ink)}}
header{{background:#13202b;color:white;padding:20px 28px}}h1{{margin:0 0 4px;font-size:22px}}header p{{margin:0;color:#cbd5df;font-size:13px}}
.wrap{{max-width:1400px;margin:0 auto;padding:18px 24px}}
.tabs{{display:flex;gap:8px;margin:0;background:#0e1922;padding:0 24px;overflow-x:auto}}
.tabs button{{border:none;background:transparent;color:#9fb0bd;padding:12px 16px;cursor:pointer;font-size:14px;border-bottom:3px solid transparent;white-space:nowrap;flex-shrink:0}}
.tabs button.active{{color:white;border-color:var(--accent)}}
.panel{{display:none}}.panel.active{{display:block}}
.grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:16px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px}}
.metric{{font-size:26px;font-weight:700}}.label{{color:var(--muted);font-size:12px}}
#map{{width:100%;height:520px;border:1px solid var(--line);border-radius:8px}}
.controls{{display:flex;gap:10px;align-items:center;margin:10px 0;flex-wrap:wrap}}
select{{padding:6px 8px;border:1px solid var(--line);border-radius:5px}}
.conflict-list{{max-height:420px;overflow:auto;border:1px solid var(--line);border-radius:8px}}
.conflict-row{{padding:10px 12px;border-bottom:1px solid var(--line);cursor:pointer}}
.conflict-row:hover{{background:#f0f4f5}}
.conflict-row .meta{{color:var(--muted);font-size:12px}}
.detail{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px;margin-top:12px}}
.pill{{display:inline-block;background:#eef3f5;border-radius:12px;padding:2px 9px;font-size:12px;margin:2px 4px 2px 0}}
.quote{{border-left:3px solid var(--accent);padding:6px 10px;margin:6px 0;color:#33424b;font-style:italic;font-size:13px}}
.page-text{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:18px;line-height:1.6}}
.note{{font-size:12px;color:var(--muted)}}
@media(max-width:900px){{.grid{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body>
<header><h1>Conflictividad inmobiliaria en Santiago</h1>
<p>Pipeline de scraping, clasificación con evidencia verificada, y análisis territorial de conflictos inmobiliarios</p></header>
<nav class="tabs">
<button data-tab="inicio" class="active">Inicio</button>
<button data-tab="contexto">Contexto</button>
<button data-tab="metodologia">Metodología</button>
<button data-tab="arquitectura">Arquitectura</button>
</nav>
<main class="wrap">
<section id="tab-inicio" class="panel active page-text">{INICIO_HTML}</section>
<section id="tab-metodologia" class="panel page-text">{METHODOLOGY_HTML}</section>
<section id="tab-arquitectura" class="panel page-text">{ARCHITECTURE_HTML}</section>
<section id="tab-contexto" class="panel">
  <section class="grid" id="metrics"></section>
  <p class="note" id="universeNote"></p>
  <div class="controls">
    <label>Colorear comunas por: <select id="metricSelect">
      <option value="n_conflicts_backed" selected>Conflictos con respaldo de evidencia detectado</option>
      <option value="n_conflicts_backed_per_100k">Conflictos con respaldo por 100.000 hab.</option>
      <option value="n_conflicts_total">Conflictos registrados (universo completo)</option>
      <option value="n_projects">Proyectos</option>
      <option value="n_documents">Documentos</option>
      <option value="n_actors">Actores</option>
    </select></label>
  </div>
  <div id="map"></div>
  <h3 style="margin-top:20px">Conflictos con respaldo de evidencia detectado</h3>
  <div class="conflict-list" id="conflictList"></div>
  <div class="detail" id="conflictDetail" style="display:none"></div>
  <p class="note">Cada cita mostrada proviene de evidencia verificada contra el documento fuente.</p>
  <details style="margin-top:16px">
    <summary id="noBackingSummary">Conflictos sin respaldo exacto de evidencia detectado</summary>
    <p class="note">El detector de respaldo (<code>exact_substring_v1</code>) busca una cita literal de
    "objeto" que vincule explícitamente el nombre del proyecto con un caso incluido del mismo
    documento. No encontrar ese respaldo exacto no demuestra que el conflicto sea falso -- en la
    muestra de calibración (N=150 casos revisados manualmente), este detector tuvo 64.5% de
    precisión y 77.8% de recall contra errores graves. Estos conflictos siguen en el universo
    completo y no se han descartado ni marcado como inválidos; solo quedan fuera del universo
    analítico conservador hasta tener respaldo documental exacto.</p>
    <div class="conflict-list" id="noBackingList"></div>
  </details>
</section>
</main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
const DATA = {payload};
const D = DATA.dataset, L_ = DATA.labels, BASEMAP = DATA.basemap;

function label(category, value) {{
  const map = L_[category];
  if (!map) return value;
  return map[value] !== undefined ? map[value] : value;
}}

document.querySelectorAll('.tabs button').forEach(btn => {{
  btn.addEventListener('click', () => {{
    document.querySelectorAll('.tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + btn.dataset.tab).classList.add('active');
    if (btn.dataset.tab === 'contexto' && window._map) {{ window._map.invalidateSize(); }}
  }});
}});

function renderMetrics() {{
  const s = D.summary;
  const items = [
    ['Documentos', s.n_documents],
    ['Conflictos registrados (universo completo)', s.n_conflicts_total],
    ['Con respaldo de evidencia detectado', s.n_conflicts_evidence_backed],
    ['Proyectos', s.n_projects],
    ['Actores', s.n_actors],
    ['Citas verificadas', s.n_evidence_verified],
    ['Comunas con conflictos', s.n_comunas_con_conflictos],
  ];
  document.getElementById('metrics').innerHTML = items.map(([lbl, val]) =>
    `<div class="card"><div class="metric">${{val.toLocaleString('es-CL')}}</div><div class="label">${{lbl}}</div></div>`
  ).join('');
  document.getElementById('universeNote').textContent =
    `${{s.n_conflicts_total.toLocaleString('es-CL')}} conflictos registrados / ` +
    `${{s.n_conflicts_evidence_backed.toLocaleString('es-CL')}} con respaldo exacto de evidencia detectado ` +
    `(${{s.n_conflicts_without_exact_backing.toLocaleString('es-CL')}} sin respaldo exacto, ver sección abajo).`;
}}

let geoLayer = null;
function colorFor(value, max) {{
  if (!value) return '#e7eef1';
  const t = Math.min(1, value / (max || 1));
  const g = Math.round(180 - t * 120);
  return `rgb(${{Math.round(11 + t*60)}}, ${{g}}, ${{Math.round(133 - t*40)}})`;
}}

function renderMap() {{
  const map = L.map('map').setView([-33.45, -70.65], 10);
  window._map = map;
  L.tileLayer(BASEMAP.url, {{ attribution: BASEMAP.attribution, maxZoom: 18 }}).addTo(map);

  function draw(metric) {{
    if (geoLayer) map.removeLayer(geoLayer);
    const max = Math.max(...D.territories.map(t => t[metric] || 0));
    geoLayer = L.geoJSON(D.territories.map(t => ({{
      type: 'Feature',
      properties: t,
      geometry: t.geometry,
    }})), {{
      style: f => ({{ fillColor: colorFor(f.properties[metric], max), weight: 1, color: '#56777c', fillOpacity: 0.75 }}),
      onEachFeature: (f, layer) => {{
        const t = f.properties;
        layer.bindPopup(
          `<b>${{t.comuna}}</b><br>Conflictos registrados: ${{t.n_conflicts_total}}<br>` +
          `Con respaldo de evidencia detectado: ${{t.n_conflicts_backed}}<br>Proyectos: ${{t.n_projects}}<br>` +
          `Población: ${{t.poblacion.toLocaleString('es-CL')}}<br>Viviendas hacinadas: ${{t.viviendas_hacinadas.toLocaleString('es-CL')}}`
        );
      }},
    }}).addTo(map);
  }}
  draw('n_conflicts_backed');
  document.getElementById('metricSelect').addEventListener('change', e => draw(e.target.value));
}}

function renderConflictList() {{
  const backed = D.conflicts.filter(c => c.respaldo_evidencia === 'respaldo_exact_quote_detectado')
    .sort((a, b) => b.n_case_ids - a.n_case_ids);
  const noBacking = D.conflicts.filter(c => c.respaldo_evidencia !== 'respaldo_exact_quote_detectado')
    .sort((a, b) => b.n_case_ids - a.n_case_ids);

  function rowsHtml(items) {{
    return items.map((c, i) => {{
      const comunas = c.comunas.map(x => x.comuna).join(', ') || 'sin comuna';
      return `<div class="conflict-row" data-idx="${{i}}"><b>${{c.label}}</b>
        <div class="meta">${{comunas}} &middot; ${{c.projects.length}} proyecto(s) &middot; ${{label('conflict_confidence', c.confidence)}}</div></div>`;
    }}).join('');
  }}

  function bind(listEl, items) {{
    listEl.querySelectorAll('.conflict-row').forEach(row => {{
      row.addEventListener('click', () => showConflictDetail(items[parseInt(row.dataset.idx)]));
    }});
  }}

  const list = document.getElementById('conflictList');
  list.innerHTML = rowsHtml(backed);
  bind(list, backed);

  document.getElementById('noBackingSummary').textContent =
    `Conflictos sin respaldo exacto de evidencia detectado (${{noBacking.length.toLocaleString('es-CL')}})`;
  const noBackingList = document.getElementById('noBackingList');
  noBackingList.innerHTML = rowsHtml(noBacking);
  bind(noBackingList, noBacking);
}}

function showConflictDetail(c) {{
  const el = document.getElementById('conflictDetail');
  el.style.display = 'block';
  const projects = c.projects.map(p => `<span class="pill">${{p.nombre}}</span>`).join('') || '<span class="note">Sin proyectos resueltos</span>';
  const actors = c.actors.map(a => `<span class="pill">${{a.nombre}} (${{label(a.tipo_categoria, a.tipo)}}${{a.stance ? ', ' + label('stance', a.stance) : ''}})</span>`).join('') || '<span class="note">Sin actores verificados con rol focal/co-principal</span>';
  const events = c.events.map(e => `<li>${{e.fecha || 's/f'}} — ${{label('tipo_hito', e.tipo_hito)}}: ${{e.descripcion}}</li>`).join('');
  const quotes = c.evidence_quotes_sample.map(q => `<div class="quote">"${{q}}"</div>`).join('');
  const docs = c.documents.map(d => `<li><a href="${{d.url}}" target="_blank" rel="noopener">${{d.title || d.url}}</a></li>`).join('') || '<li class="note">Sin documentos focales/co-principales para este conflicto</li>';
  const others = c.other_mentions.map(d => `<li><a href="${{d.url}}" target="_blank" rel="noopener">${{d.title || d.url}}</a> <span class="note">(${{label('document_conflict_role', d.role)}} · no utilizado como evidencia focal)</span></li>`).join('');
  el.innerHTML = `<h3>${{c.label}}</h3>
    <p class="note">Origen: ${{label('conflict_origen', c.origen)}} &middot; Confianza: ${{label('conflict_confidence', c.confidence)}} &middot; ${{c.n_case_ids}} caso(s) &middot; ${{label('respaldo_evidencia', c.respaldo_evidencia)}}</p>
    <p><b>Proyectos:</b> ${{projects}}</p>
    <p><b>Actores</b> <span class="note">(rol focal/co-principal, identidad resuelta cuando aplica)</span>: ${{actors}}</p>
    ${{events ? `<p><b>Línea de tiempo</b> (${{c.n_events_total}} hito(s)):</p><ul>${{events}}</ul>` : ''}}
    ${{quotes ? `<p><b>Evidencia citada:</b></p>${{quotes}}` : ''}}
    <p><b>Documentos fuente (focal/co-principal):</b></p><ul>${{docs}}</ul>
    ${{others ? `<p><b>Otras menciones</b> <span class="note">(contextuales o sin revisar -- no aportan actores/eventos a este detalle)</span>:</p><ul>${{others}}</ul>` : ''}}`;
}}

renderMetrics();
renderMap();
renderConflictList();
</script>
</body></html>
"""


def main() -> int:
    dataset = build_dashboard_dataset()
    labels = _load_labels()
    html = build_html(dataset, labels)
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Dashboard escrito en {OUTPUT_PATH} ({len(html):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
