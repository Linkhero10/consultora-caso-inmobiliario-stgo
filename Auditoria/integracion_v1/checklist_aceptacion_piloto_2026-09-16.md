# Checklist de aceptación — piloto de integración P0 (Estación Central, guetos verticales)

Recorre `Auditoria/agent_reviews/inventario_integracion_arcos_20260913.md`
sección 7, honestamente: cumplido con evidencia, parcial, o no cumplido.

**[CORRECCIÓN 2026-09-16, hallazgo real de Sol]** El resumen anterior de
este archivo decía "7/10 cumplidos, 0 no cumplidos" — error de conteo
propio: el archivo tiene **11 líneas evaluativas, no 10** (`grep -c '^\- \['`
lo confirma), y **2 siguen marcadas `[ ]` (no cumplido)**, no 0: licencia/
condiciones de uso, y PII. El recuento real correcto es **6 cumplidos
(`[x]`), 3 parciales (`[~]`), 2 no cumplidos (`[ ]`)** — ver abajo.

## Contrato común de evidencia

- [x] **Cada documento tiene `document_id`, hash, URL, fecha de captura y
  `lineage`.** `document_id = content_sha256`, `url`, `fetched_at`,
  `lineage_json` en la tabla `document` (verificado: 11/11 documentos del
  piloto con estos campos poblados).
- [ ] **Condiciones de uso/licencia por fuente.** No implementado. Ningún
  campo de licencia en `document`. Gap real, no resuelto en este piloto.
- [x] **Cada afirmación apunta a un `evidence_id` y localizador reproducible;
  citas comprobadas contra el documento.** Tabla `claim.claim_evidence_ids_json`
  enlaza a `evidence`, cada fila de `evidence.verified` viene del flag de
  literalidad ya calculado por el gate (`evidence_*_quotes_verified`,
  alineado por índice, con test dedicado). En el piloto: 18 claims, todas
  sus citas mostradas en la vista HTML son `verified=1`.
- [x] **Cada evento admite varias fechas o un intervalo (`linea_tiempo`).**
  **[ACTUALIZADO 2026-09-16, noche] CUMPLIDO.** Fase F ejecutada
  (`enrich_case_v2.py`, `enrichment_schema_v2.json`): 11/11 documentos, 38
  hitos de `linea_tiempo` (36/38 con el año confirmado literalmente en el
  texto fuente). Materializados en la tabla `event` del warehouse
  (`build_event_table_v1.py`, 38/38 con FK real a `document`, 0 con
  fallback de hash de URL). Integrado además a la vista HTML del piloto
  (línea de tiempo consolidada, orden cronológico 1960→2025).
- [x] **Cada caso conserva documentos y eventos de origen; nada reemplaza la
  procedencia.** La vista HTML enlaza cada claim a su documento fuente
  (`<a href>` a la URL real); el crosswalk declara explícitamente qué
  documentos NO tienen un `project_id` específico resuelto en vez de
  fingir resolución.
- [~] **Los joins declaran método, fecha de capa, CRS y tasa de no unión.**
  Parcial: el join de `territory` usa `codigo_comuna_ine` (ID oficial, no
  por nombre) — método declarado en el código, pero no se escribió un
  reporte aparte con tasa de no-unión ni CRS explícito de la capa censal
  (el GeoJSON trae su propio campo `crs`, no propagado al artefacto).
- [ ] **PII minimizada, marcada y separada.** No implementado. La tabla
  `entity` guarda nombres de personas tal como aparecen en prensa (ej.
  "Rosa González", vecina citada) sin ningún campo de clasificación PII.
  Son nombres ya públicos en la fuente, pero el criterio pide marcado
  explícito, que no existe. Gap real.
- [~] **Se reportan cobertura, sesgo, faltantes, incertidumbre, duplicados y
  límites.** Parcial: la reconciliación de dedupe documenta duplicados
  reales (Fase A0); el crosswalk documenta explícitamente qué documentos
  no resuelven a un proyecto específico. Pero no existe un reporte único
  y consolidado de sesgo/cobertura para el piloto (ej. cuántas comunas de
  las 32 tienen 0 casos, ventana temporal real vs. ventana de búsqueda).

## Criterios de Felipe (corpus, clasificación, mapa, dashboard)

- [x] **Clasificación reproducible por versión.** `contract_version` fijo
  (`v5.2.3`) en cada documento; manifest con hashes de prompt/schema/script.
- [~] **Mapa no confunde proxy con valor de mercado.** No aplica todavía en
  sentido estricto (no hay capa de valor de mercado en este piloto), pero
  el mapa comunal SÍ deja explícito en texto que es nivel comuna, no punto
  exacto — no hay afirmación engañosa de precisión.
- [x] **Dashboard concuerda con la tabla fuente y permite abrir la
  evidencia.** Cada claim en `Productos/piloto_integracion_v1/index.html`
  enlaza al documento fuente real; verificado visualmente en el Browser
  pane (11 documentos, 18 claims, 59 entidades, sin errores de consola).

## Resumen

**[CORREGIDO 2026-09-16, noche, hallazgo real de Sol: el resumen anterior
tenía un error de aritmética] Recuento real: 11 líneas evaluativas — 6
cumplidas con evidencia (`[x]`), 3 parciales (`[~]`), 2 no cumplidas
(`[ ]`).** Los 2 puntos genuinamente no cumplidos: condiciones de uso/
licencia por documento, y PII minimizada/marcada/separada — ninguno de los
dos se tocó en esta ronda, siguen abiertos. Línea de tiempo/eventos SÍ se
cerró con datos reales esta ronda (Fase F + tabla `event`), eso es correcto
y se mantiene. Además, Sol encontró que el crosswalk de proyectos
específicos tenía un error real (fusión indebida de un nombre de empresa
con un nombre de calle) y que `nombre_proyecto` se atribuía mal a hitos de
`linea_tiempo` en documentos multi-proyecto — ambos corregidos (ver
`crosswalk_project_id_piloto.json` v2 y la vista HTML regenerada). Ninguno
de los gaps restantes bloquea el valor del piloto como demostración
end-to-end (documento→evidencia→claim→entidad→territorio→evento), pero
tampoco se
declaran resueltos para no inflar el estado real.
