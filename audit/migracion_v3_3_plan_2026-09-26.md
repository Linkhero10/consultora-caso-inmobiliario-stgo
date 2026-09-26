# Migración completa v3.2→v3.3 + Fix 1F (geografía real) — cierre técnico final del enrichment

## 0. Contexto

Hoy (2026-09-25/26) se completó la migración de TODO el corpus productivo (934/934 documentos,
100%) al contrato de enriquecimiento v3.3, corrido en 8 tandas vía 3 proveedores (OpenRouter,
NanoGPT, Requesty), costo real total $3.84404 USD. Los 3 archivos fuente son:

```
Auditoria/enriquecimiento_v3_3_piloto/enrichment.jsonl        (8 docs)
Auditoria/enriquecimiento_v3_3_calibracion/enrichment.jsonl   (75 docs)
Auditoria/enriquecimiento_v3_3_escalamiento/enrichment.jsonl  (851 docs)
```

Verificado empíricamente en esta sesión: unión de URLs = 934, exactamente igual a
`SELECT COUNT(*) FROM enrichment_document` (el warehouse productivo v3.2 actual). 0 registros
inválidos, 248/249 tests en verde (1 fallo preexistente ajeno, `test_blind_review_html.py`, busca
un archivo fuera del repo — no relacionado).

**El problema que esta tarea cierra**: v3.3 hoy solo se usa como fuente secundaria, leída en vivo
desde los 3 JSONL directamente por `build_conflicts.py::load_v3_3_verified_links()` (Fix 1D,
2026-09-24) — nunca se materializó en el warehouse productivo. La tabla real `enrichment_document`
(y `enrichment_project_mention`, sin vínculo a `case_mention` en absoluto) se sigue construyendo
100% desde el v3.2 VIEJO (`src/build_enrichment_tables.py`, lee
`Auditoria/enriquecimiento_v3_2_934/enrichment.jsonl`). Esto obliga a `load_v3_3_verified_links()` a
hacer un puente frágil por NOMBRE NORMALIZADO entre dos corridas LLM separadas (v3.2 y v3.3), que
empíricamente no coinciden en el 15.6% de los casos (`build_conflicts.py:257-276`) — un parche
sobre un parche, exactamente el patrón que el usuario pidió dejar de repetir.

Con el 100% del corpus ahora en v3.3, la solución de raíz es: **v3.3 pasa a ser la ÚNICA fuente del
warehouse productivo**, v3.2 se retira como dependencia del pipeline (el JSONL v3.2 nunca se borra
— es dato histórico), y todo el puente por nombre-normalizado desaparece porque
`enrichment_project_mention` y `case_mention_index` van a vivir en la MISMA fila, materializados
por el mismo ETL.

En paralelo hay un segundo problema de raíz idéntico, nunca resuelto: `dashboard_data.py`'s
`n_projects_mentioned` por comuna (`dashboard_data.py:151-227`) atribuye CUALQUIER mención de
proyecto en un documento a la comuna resuelta de ESE documento, sin verificar si esa mención
específica es la del `case_mention` que realmente corresponde a esa comuna — el mismo bug que Fix
1D resolvió para el respaldo de conflictos, nunca portado a geografía. Ya existió un diseño previo
para esto (`diseno_geografia_case_mention_level_2026-09-23`, implementado en
`src/project_case_mention.py`/`src/project_geography.py`, medición real: -54% en el conteo
inflado) pero se **borró** en el commit de Fix 1D (`e6a5c18`) por quedar redundante frente a la
v3.3 — la geografía nunca se reconectó a la sustituta. Con el 100% del corpus en v3.3, ahora sí se
puede cerrar esto con la MISMA mecánica de Fix 1D/1E, reutilizando `case_mention_index` en vez de
reinventar un substring-matcher.

**Filosofía explícita de esta tarea** (pedido directo del usuario, "arreglar todo de raíz, no
pequeñas correcciones"): no se agrega v3.3 como una tercera fuente en paralelo a v1/v2 — v3.2
se retira del pipeline productivo por completo (el archivo JSONL se conserva como histórico, pero
ningún script productivo lo lee por defecto en adelante). El puente-por-nombre de
`load_v3_3_verified_links()` se elimina (ya no hace falta: una sola fuente, un solo nombre por
mención). El detector `exact_substring_v1` (heurística de texto, 44-56% de precisión, Fix 1A) se
retira del código vivo — ya no queda ningún documento sin `case_mention_index` verificado; se
conserva su historia en `audit/validation_summary.json` (inmutable) pero no como código activo.

**Costo de toda esta tarea: $0 USD.** Es 100% código + reconstrucción + tests sobre datos LLM ya
pagados y ya en disco. Ninguna llamada nueva a ningún proveedor.

## 1. Fase 2 — `enrichment_document`/`enrichment_project_mention` nativos de v3.3

### 1.1 Cambio de esquema: `proyectos_mencionados` deja de ser `list[str]`

v3.2: `proyectos_mencionados` es `list[str]` (nombres sueltos) —
`build_enrichment_tables.py:268-274` inserta el string crudo. v3.3: cada elemento es un objeto
`{nombre, case_mention_index, case_mention_index_verificada, case_mention_index_original_modelo}`
(`config/enrichment_schema_v3_3.json:12-40`, ya saneado por
`sanitize_project_associations_v3_3()` en `src/_enrich_pipeline_v3_3_pilot.py:135-176` antes de
persistirse — `case_mention_index` ya viene garantizado en rango `[0, n_case_mentions)` o `null`,
nunca hace falta re-validar el rango en el ETL). El resto de los campos del registro (actores,
instituciones, linea_tiempo, objeto_disputa, etc.) son estructuralmente idénticos entre v3.2 y
v3.3 — confirmado campo por campo, sin cambios de shape salvo este.

**Sin este cambio, correr `build_enrichment_tables.py`/`build_projects.py` tal cual contra v3.3
truena**: ambos hacen `.strip()`/tratan el item como string
(`build_enrichment_tables.py:268-274`, `build_projects.py` ~línea 153-165) — con un dict eso
lanza `AttributeError` o falla el binding de sqlite3.

### 1.2 Módulo nuevo compartido: `src/v3_3_enrichment_source.py`

Fuente única de verdad para "leer los 3 JSONL de v3.3", reemplazando la lectura ad-hoc duplicada
que hoy vive dentro de `build_conflicts.py::load_v3_3_verified_links()`. Expone:

- `V3_3_ENRICHMENT_FILES` (mover aquí desde `build_conflicts.py:221-224`, import desde ahí después).
- `load_v3_3_records() -> dict[url, record]`: lee los 3 archivos, **valida que ninguna URL se repita
  entre archivos** (raise explícito si sí — nunca "el primero gana" en silencio, a diferencia del
  patrón viejo de `build_enrichment_tables.py:220-222`; los 3 archivos deben ser disjuntos por
  construcción, así que un duplicado real es una señal de bug que hay que investigar, no ignorar).
- Reexportar `V3_3_URL_FUERA_DE_UNIVERSO` (el único documento del piloto nunca revisado por Sol) —
  se mantiene el mismo criterio de exclusión de Fix 1D: ese documento cae fuera de
  `load_v3_3_records()` por defecto (parámetro opcional para incluirlo si algún consumidor lo
  necesita explícitamente, documentado por qué).
- `CLASSIFICATIONS_SHA256_EXPECTED` + el guard de `classifications.jsonl` (mover desde
  `build_conflicts.py:219-220,278-287` tal cual, mismo valor, mismo mensaje de error).

`build_conflicts.py` importa este módulo en vez de reimplementar; `build_enrichment_tables.py` y
`build_projects.py` lo importan también. Esto es la eliminación real del código duplicado, no solo
mover líneas.

### 1.3 `src/build_enrichment_tables.py`

- `DEFAULT_ENRICHMENT` deja de ser un único path v3.2 → usa `load_v3_3_records()` del módulo nuevo.
- `_validate_project_associations()` (líneas 35-47): comparar `association` contra
  `item.get("nombre")` de cada elemento de `proyectos_mencionados`, no contra el elemento crudo.
- `_create_tables()`: **schema aditivo, nunca se quita nada** — `enrichment_project_mention` gana 2
  columnas nuevas nullable: `case_mention_index INTEGER`, `case_mention_id TEXT` (precomputado,
  `f"{document_id}:{idx}"` solo cuando `case_mention_index IS NOT NULL` — evita recomputar el
  string en cada consumidor). El resto de las 6 tablas no cambia de columnas (todos los demás
  campos v3.2/v3.3 coinciden 1:1, confirmado en la investigación).
- Insert de `enrichment_project_mention` (hoy `build_enrichment_tables.py:268-274`): usar
  `project.get("nombre","")`, `project.get("case_mention_index")`, y el `case_mention_id`
  derivado.
- Renombrar el archivo de salida por defecto: `Auditoria/integracion_v1/warehouse_v3_2.sqlite` →
  `Auditoria/integracion_v1/warehouse_enrichment.sqlite` (nombre neutral a la versión de contrato,
  ya que el archivo es "el warehouse intermedio de tablas enrichment_*", no algo atado a v3.2 per
  se — la confusión de este nombre ya causó 2 incidentes reales esta semana). Grep exhaustivo antes
  de renombrar: `grep -rn "warehouse_v3_2" src/ tests/ Trabajo/ docs/ audit/ README.md` y actualizar
  cada referencia real (confirmado por investigación: solo `src/build_projects.py::SOURCE_WAREHOUSE`
  y sus tests la usan como constante; puede haber menciones sueltas en prosa/comentarios que también
  hay que corregir, no solo el código).
- El JSONL v3.2 viejo (`Auditoria/enriquecimiento_v3_2_934/enrichment.jsonl`) **no se borra** — deja
  de ser el default, se conserva como archivo histórico.

### 1.4 `src/build_projects.py`

- Reemplazar su lectura directa del JSONL v3.2 (`ENRICHMENT_PATH`, hoy hardcoded) por
  `load_v3_3_records()` del módulo compartido — mismo criterio de universo (excluye
  `V3_3_URL_FUERA_DE_UNIVERSO`).
- Corregir el manejo de `proyectos_mencionados` (la línea `.strip()` que hoy truena con un dict) —
  extraer `.get("nombre","").strip()` de cada item antes de usarlo en el registro de proyectos.
- `SOURCE_WAREHOUSE` apunta al nuevo `warehouse_enrichment.sqlite` (post-rename).
- `_validate_source_warehouse()`/`SOURCE_WAREHOUSE_EXPECTED_TABLES`/`SOURCE_WAREHOUSE_MIN_DOCUMENTS`
  (guard de Fix 1E) se mantienen sin tocar su lógica — solo referencian el nuevo nombre de archivo.

### 1.5 `src/build_conflicts.py` — la simplificación real

Con `enrichment_project_mention.case_mention_index` ya materializado en el warehouse:

- `load_v3_3_verified_links()` se **reemplaza** por una consulta SQL directa:
  `SELECT document_id, nombre_proyecto, case_mention_index FROM enrichment_project_mention` — ya no
  hace falta re-leer los 3 JSONL en cada corrida, ni el puente por `_norm()`-nombre entre dos
  corridas LLM distintas (ya no hay dos corridas: `project_mention_resolved` y
  `enrichment_project_mention` vienen de la MISMA fuente v3.3, así que los nombres coinciden por
  construcción — el 15.6% de discrepancia documentado en el docstring actual deja de aplicar y así
  se anota en el código, no se borra la mención histórica sin explicar por qué ya no aplica).
- `_project_backing_evidence()`: eliminar la rama `exact_substring_v1`/`_mention_has_case_backing`
  por completo — **todo** proyecto mencionado ahora tiene (o no) un `case_mention_index` verificado
  por v3.3; si es `None`, la mención queda sin respaldo (correcto: v3.3 ya decidió explícitamente
  que no hay vínculo claro, no hace falta adivinar por substring). Mantener intacta la rama de
  fallback por grupo duplicado (Fix 1E) — sigue siendo necesaria y correcta.
- **Verificar empíricamente antes de borrar el código del detector viejo** (no asumir): reconstruir
  primero con ambos caminos activos, comparar cuántas filas de `conflict_evidence_backing`
  quedarían con `detector_version=exact_substring_v1` en la nueva reconstrucción (debería ser 0,
  porque ya no hay documentos fuera del universo v3.3) — si el número no es 0, investigar por qué
  antes de retirar el código (podría revelar un caso real donde v3.3 nunca corrió para un
  documento que sí tiene `enrichment_document`, lo cual sería un gap de cobertura real a resolver,
  no a ocultar).
- Actualizar el docstring del módulo (líneas ~40-55) para reflejar el pipeline nuevo (sin v1/v2 como
  dependencia productiva).

## 2. Fase 3 — Fix 1F: geografía real por `case_mention`

Con `case_mention_index` ya en el warehouse (§1.3), resolver
`(document_id, nombre_proyecto) → case_mention_id` es un JOIN directo, no un diccionario en memoria.

### 2.1 Nueva tabla `project_mention_geography` (en `src/build_geography.py`)

Reutilizar `_resolved_comuna_name_by_case_mention()` (ya existe en `build_geography.py:141-155`,
hoy solo usado internamente para geocoding) como la función que, dado un `case_mention_id`,
devuelve su comuna/`codigo_comuna_ine` real (de `case_mention.comuna` o del backfill de
`case_mention_geography`). Para cada fila de `enrichment_project_mention` con `case_mention_id` no
nulo: resolver comuna vía esa función; si el `case_mention` no tiene comuna propia, aplicar el
mismo fallback de grupo-duplicado de Fix 1E (`case_mention_duplicate_link`) antes de marcar
`unresolved` — igual patrón que `_project_backing_evidence()`, mismo principio "nunca adivinar,
marcar explícito".

```sql
CREATE TABLE project_mention_geography (
    document_id TEXT NOT NULL,
    project_mention_id TEXT NOT NULL,
    nombre_proyecto TEXT NOT NULL,
    case_mention_id TEXT,
    comuna TEXT,
    codigo_comuna_ine TEXT,
    match_method TEXT NOT NULL CHECK (match_method IN (
        'direct', 'via_duplicate_group', 'no_case_mention_index', 'case_mention_sin_comuna'
    )),
    PRIMARY KEY (document_id, project_mention_id)
);
```

Reporte auditable `audit/project_mention_geography_report.json` (mismo patrón que
`case_mention_duplicates_report.json`): conteos reales por `match_method`, nunca hardcodeados.

### 2.2 `src/dashboard_data.py::build_territories()`

Reemplazar la construcción actual de `n_projects_mentioned` (`dashboard_data.py:161-184`, la que
atribuye cualquier mención del documento a la comuna del documento) por un `JOIN` contra
`project_mention_geography` filtrando `codigo_comuna_ine = code AND match_method != 'unresolved'`
(o el nombre de estado que corresponda). Renombrar el campo — ya no es una aproximación, es un
conteo verificado — a `n_projects_verified` (o similar; decidir el nombre exacto al implementar,
documentando el cambio). Actualizar/retirar `nota_metodologica_geografia_proyectos`
(`dashboard_data.py:472-480`) para reflejar que ahora SÍ hay un vínculo directo verificado, citando
el nuevo mecanismo en vez de advertir su ausencia.

**Verificación esperada**: el conteo nuevo debería caer significativamente vs. el viejo
`n_projects_mentioned` (el diseño previo de 2026-09-23 midió -54% con un enfoque de substring más
débil que v3.3 — con v3.3 la caída real puede diferir; medir y reportar el número real, no asumir
que coincide con la cifra vieja).

## 3. Fase 4 — Verificación

Orden de reconstrucción completo (no existe hoy un único script que lo documente — confirmado por
investigación; se establece aquí y se documenta en `docs/architecture.md`/`README.md` como parte
del cierre):

```
1. python src/build_enrichment_tables.py     (NUEVO: fuente v3.3, ver §1.3)
2. python src/build_projects.py              (fuente v3.3, ver §1.4)
3. python src/resolve_project_review.py
4. python src/build_conflicts.py             (sin exact_substring_v1, ver §1.5)
5. python src/build_actor_registry.py
6. python src/build_actor_network.py
7. python src/apply_actor_registry_to_network.py
8. python src/build_geography.py             (agrega project_mention_geography, ver §2.1)
9. python src/build_geography_manzana.py
10. python src/build_dashboard.py            (agrega n_projects_verified, ver §2.2)
11. python src/generate_run_manifest.py      (SIEMPRE el último paso que toca el warehouse)
12. pytest -q
```

Verificaciones concretas antes de dar por cerrado:
- `PRAGMA integrity_check` = `ok`, `foreign_key_check` = 0 filas.
- Conteos antes/después: `enrichment_document` sigue en 934 filas: mismo documento, dato distinto
  (v3.3 en vez de v2). `conflict`/`conflict_evidence_backing`: comparar conteos totales y por
  `detector_version` — reportar el delta real, nunca asumir que debe quedar igual.
- 0 filas con `detector_version='exact_substring_v1'` en la reconstrucción nueva (§1.5) — si no es
  0, investigar antes de retirar el código del detector.
- Spot-check manual de ~15 conflictos y ~15 filas de `project_mention_geography` contra el texto
  real (mismo estándar que cada fix anterior de este proyecto).
- `pytest -q`: mismo criterio de CI (`pip install -e .[dev]` + `pytest -q`, `.github/workflows/tests.yml`)
  — 0 fallas nuevas (el fallo preexistente ajeno de `test_blind_review_html.py` es aceptado, no
  bloqueante, ya documentado en sesiones previas).
- Dashboard inspeccionado visualmente en el Browser pane (servido por HTTP, no `file://`) — sin
  errores de consola, `n_projects_verified` visible con su nota metodológica actualizada.
- `git diff --stat` revisado antes de commitear: `docs/index.html` va a mostrar un diff grande por
  ser un solo blob JS inline (confirmado por investigación, no hay forma de evitarlo) — normal, no
  señal de error.

## 4. Fase 5 — Limpieza y cierre

- `audit/validation_summary.json`: agregar bloque `fix_1f_geografia_case_mention_level` (mismo
  shape que `fix_1d_...`/`fix_1e_...`: fecha, `plan_aprobado_archivado`, descripción, cambios de
  código, resultado medido, verificación, tests, status) referenciando
  `diseno_geografia_case_mention_level_2026-09-23` como el diseño previo que esta tarea completa.
  Agregar bloque nuevo `migracion_v3_2_a_v3_3_completa_2026-09-26` documentando la migración de
  `enrichment_document`. Corregir (nunca reescribir en silencio — bloque nuevo fechado) la frase
  hoy falsa en `enrichment_schema_v3_3_case_mention_index.status`: *"el enrichment productivo...
  sigue siendo v3.2"*. Actualizar `gate_conflict_completo.componentes` (agregar `fix_1f_...`) y su
  `nota` (ya no es cierto que "el mapa público no se tocó").
- Archivar el plan aprobado verbatim: `audit/fix_1f_plan_2026-09-26.md` y/o
  `audit/migracion_v3_3_plan_2026-09-26.md` (mismo patrón ya usado para Fix 1D/1E, porque el archivo
  de plan local es mutable/efímero).
- `README.md`/`docs/architecture.md`: documentar el orden de reconstrucción COMPLETO (§3) — hoy
  ninguno de los dos lo tiene completo (README omite `build_geography*`/`build_dashboard`/
  `generate_run_manifest`; architecture.md omite ambos build_geography y el manifest). Esto es
  cerrar un gap de documentación real encontrado en la investigación, no una tarea nueva inventada.
- Confirmar que `src/project_case_mention.py`/`src/project_geography.py` siguen sin existir (ya
  borrados en Fix 1D) — no revivirlos; Fix 1F los reemplaza con una implementación mejor basada en
  v3.3 nativo, no con el prototipo viejo basado en substring.
- Actualizar bitácora FARO (`_FARO/memory-bank/`: `work-log.jsonl`/`BITACORA.md` vía
  `register_work_record`, `active-context.md`, `current-handoff.md` regenerado,
  `Trabajo/config/stage_roadmap.yaml` con bloque `current_status_2026-09-26`) — mismo estándar de
  todo el proyecto.
- Commits: varios, lógicos y revisables (no uno solo gigante) — sugerido: (1) módulo compartido +
  build_enrichment_tables.py + build_projects.py [Fase 2 ETL], (2) build_conflicts.py simplificado
  [Fase 2 consumo], (3) Fix 1F geografía completo [Fase 3], (4) docs + validation_summary + bitácora
  [Fase 5]. Cada commit con su propia corrida de `pytest -q` en verde antes del siguiente.

## 5. Tests

- `tests/test_build_enrichment_tables.py` (NUEVO — no existe hoy, confirmado por investigación):
  cobertura de `load_v3_3_records()` reutilizado desde el módulo compartido, el manejo del nuevo
  shape de `proyectos_mencionados`, la columna `case_mention_index`/`case_mention_id` persistida
  correctamente, y el guard de URLs duplicadas entre los 3 archivos.
- `tests/test_v3_3_enrichment_source.py` (NUEVO, para el módulo compartido §1.2): guard de
  sha256 de `classifications.jsonl`, exclusión de `V3_3_URL_FUERA_DE_UNIVERSO`, detección de URL
  duplicada entre archivos.
- `tests/test_build_projects.py`: actualizar donde asuma `proyectos_mencionados` como lista de
  strings; el guard `_validate_source_warehouse` se actualiza solo en el nombre de archivo, no en
  lógica.
- `tests/test_build_conflicts.py`: actualizar/retirar los tests de `load_v3_3_verified_links()` que
  asumían lectura de JSONL crudo (ahora es una consulta SQL); actualizar los tests de
  `_project_backing_evidence()` que ejercitaban la rama `exact_substring_v1` (documentar
  explícitamente por qué se retiran, no borrarlos en silencio — o convertirlos en tests de
  regresión que confirman que la rama ya no existe).
- `tests/test_build_geography.py` (hoy solo 5 tests, delgado): agregar cobertura de
  `project_mention_geography` — resolución directa, fallback por grupo duplicado, caso
  `case_mention_index=None`, caso `case_mention` sin comuna propia.
- `tests/test_dashboard_data.py`: nuevo test para `n_projects_verified` (o el nombre final)
  análogo a los tests ya existentes de backing v3.3 en `test_build_conflicts.py`.

## 6. Gate de cierre

`enrichment_document`/`enrichment_project_mention` construidos 100% desde v3.3 (v3.2 retirado del
pipeline productivo, conservado como histórico) · módulo compartido `v3_3_enrichment_source.py`
sin duplicación de lógica entre `build_enrichment_tables.py`/`build_projects.py`/`build_conflicts.py`
· `exact_substring_v1` retirado del código vivo, verificado con 0 filas reales antes de borrarlo ·
`load_v3_3_verified_links()` reemplazado por consulta SQL directa, sin puente por nombre
normalizado · Fix 1F: `project_mention_geography` construida y consumida por
`dashboard_data.py`, con match_method explícito nunca silencioso · reconstrucción completa en el
orden documentado · `integrity_check=ok`/`foreign_key_check=0` · tests nuevos + existentes en verde
(mismo criterio que CI) · spot-check manual de conflictos y geografía documentado en `audit/` ·
`audit/validation_summary.json` actualizado (bloques nuevos, nunca reescritura silenciosa de
bloques viejos) · plan archivado en `audit/` · documentación de arquitectura completa con el orden
real de reconstrucción · bitácora FARO actualizada · $0 de gasto LLM en toda la tarea.

## 7. Explícitamente fuera de alcance

- Los 3 arcos analíticos (red de actores/SNA/ERGM, institucionalidad, auditoría ESG) — son de los
  colegas del usuario, no se tocan (instrucción explícita y reiterada del usuario).
- Revisión del inventario de fuentes — mismo motivo.
- Cualquier re-clasificación o re-enriquecimiento con LLM — todo el trabajo de esta tarea opera
  sobre datos ya generados y pagados, cero llamadas nuevas.
- Fase C del dashboard geoespacial a nivel de manzana censal enlazada a conflictos — sigue fuera,
  mismo criterio que Fix 1D lo dejó (trabajo nuevo, no un fix de raíz de algo ya construido).
