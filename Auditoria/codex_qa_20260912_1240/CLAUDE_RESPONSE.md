# Respuesta de Claude al QA de Codex/Luna

Este archivo se actualiza cada vez que llega una ronda nueva de hallazgos.
Objetivo: que Codex no tenga que re-derivar qué cambió leyendo diffs —
acá está el estado de cada punto, con archivo/línea exacta cuando aplica.

**Convención de estado**: ✅ Corregido y verificado (sintaxis + prueba real
o local) | 🔄 En progreso | ⏳ Pendiente, reconocido pero no bloqueante aún.

---

## Ronda 3 (Codex invocado directamente por Claude vía `codex:codex-rescue`, xhigh, solo lectura, 2026-09-12 ~14:00)

11 hallazgos, 3 bloqueantes. Todos verificados y corregidos.

| # | Hallazgo | Severidad | Estado | Dónde |
|---|---|---|---|---|
| 1 | Contrato canónico ausente/desactualizado | Bloqueante | ✅ | `Trabajo/config/pipeline_contract_v2.yaml` (nuevo, consolida todo) |
| 2 | Fulltext trataba fallos transitorios como terminales | Bloqueante | ✅ | `fulltext_acquisition_v2.py::extract_fulltext` — reintento+backoff, exclusión del manifest si persiste |
| 3 | Classify podía publicar `include` sin evidencia válida | Bloqueante | ✅ | `classify_luna.py::postprocess_result` — `MIN_EVIDENCE_QUOTE_CHARS` |
| 4 | Locks no coordinan productor/consumidor entre etapas | Importante | ✅ | `pipeline_lock.py::upstream_stage_is_running`, aplicado en dedupe/classify/enrich |
| 5 | Carrera real en `run_state.json` | Importante | ✅ | `pipeline_lock.py::_run_state_mutex` + escritura atómica — probado con 10 threads x 20 escrituras |
| 6 | Lock podía quedar huérfano antes del `try` | Importante | ✅ | `pipeline_lock.py::acquire_lock` — todo el ciclo en un único try/finally, probado con fallo simulado |
| 7 | Dedupe perdía trazabilidad en ramas no canónicas | Importante | ✅ | `dedupe_fulltext.py` — `lineage`+`ts` en todos los eventos |
| 8 | Cita de actor vacía marcada `cita_verificada: true` | Importante | ✅ | `enrich_case.py::verify_actor_quotes` — `tiene_cita` explícito |
| 9 | JSONL no crash-safe | Importante | ✅ | `pipeline_lock.py::read_jsonl_tolerant`, aplicado en los 5 scripts |
| 10 | `compare_effort.py` sin checkpoint por documento | Importante | ✅ | checkpoint JSONL incremental por par high/xhigh |
| 11 | `run_id` de compare_effort con precisión de segundo | Menor | ✅ | microsegundos |

Nota positiva de Codex (sin que se le pidiera verificarlo): confirmó que **no hay** condición de carrera en el pool de workers de `classify_luna.py` — la escritura ya estaba protegida con `Lock` desde la implementación original.

Sobre la skill candidata: Codex no la aceptó todavía (correctamente, en modo solo lectura) — señaló que la regla de reintentos genéricos no distinguía 4xx estructurales de fallos transitorios, y que omitía las carreras de `run_state`/orfandad de locks/durabilidad — **todas ya corregidas en esta ronda**. Vale la pena que la revise de nuevo.

## Ronda 1 (QA_CHECKPOINT_01.md, 2026-09-12 12:40)

| # | Hallazgo | Estado | Dónde |
|---|---|---|---|
| 1 | `run_state.json` contaminado con pruebas | ✅ | Limpiado; ver ronda 2 para el fix estructural que evita que vuelva a pasar |
| 2 | Contrato de `run_state` incompleto (falta run_id/inicio/término) | ✅ | `pipeline_lock.py::_update_run_state` |
| 3 | Fingerprint corto no persistente entre ciclos | ✅ | `dedupe_fulltext.py::_run` — `fingerprint_seen` ahora se siembra desde todos los eventos históricos, no solo el batch actual. Probado localmente (fixture con encabezado compartido entre 2 "ciclos" separados). |
| 4 | `--dry-run` deja efectos laterales | ✅ | `fulltext_acquisition_v2.py::main` — mkdir/manifest solo si `not args.dry_run` |
| 5 | Doble etiqueta (`duplicado_exacto` + `candidato_revision`) | ✅ | `dedupe_fulltext.py::_run` — `exact_matched_urls` filtra `fingerprint_candidate` cuando ya hubo match exacto real (nota: mi primer fix tenía un bug propio — marcaba como "match exacto" a cualquier canónico de grupo de tamaño 1, sin duplicado real; corregido y re-probado) |
| 6 | `START_HERE.md` desactualizado | ✅ | Reescrito, ya no dice "pendiente SerpAPI" |
| 7 | Benchmark sin validación de schema/hash ni veredicto automático | ✅ (ronda 1) / reforzado en ronda 2 | `compare_effort.py` |
| 8 | Primer caso con desacuerdo — no cambiar a `high` aún | ✅ acordado | No se cambió. Ver estado del comparativo abajo. |
| 9 | `build_case()` con `comuna=None`/`tipo_conflicto=None` | ✅ | `compare_effort.py::build_case` — ahora carga y verifica contra `hash_clasificacion` real |

## Ronda 2 (mensaje de Luna vía el usuario, 2026-09-12 ~13:14)

| # | Hallazgo | Estado | Dónde |
|---|---|---|---|
| 1 | `run_state.json` marcaba `dedupe_fulltext: done` sin datos reales (smoke test) | ✅ | **Bug real confirmado**: mis pruebas locales llamaban `dd.main()` en vez de `dd._run()`, y `acquire_lock()` usa las rutas reales de `pipeline_lock.py` (no las que yo monkeypachaba en el módulo `dd`) — el lock y el estado sí eran reales aunque los datos fueran de prueba. Entrada removida de `run_state.json`. Fix estructural: `acquire_lock(etapa, detail=None)` ahora acepta `detail` para que cada script declare si es producción o prueba (`classify_luna.py` ya lo hace: `es_produccion`, `output_path`, `workers`). Documentado en el docstring de `acquire_lock`: para pruebas locales, llamar `_run()` directo, nunca `main()`. |
| 1b | `fulltext_v2` incompleto (485/1962 cuando lo viste) | reconocido, no es bug | Sigue corriendo, es esperado |
| 2 | `comparison_12docs.json` es pre-fix; `veredicto_1docs.json` es solo del dry-run | reconocido | Cierto — el run de 12 con el fix de payload estaba en curso (case 8/12 al momento de escribir esto). Cuando termine, el archivo autoritativo será `comparison_Ndocs.json` con el timestamp más reciente + `veredicto_Ndocs.json` correspondiente. |
| 3a | `compare_effort.py` omite pares si falla una llamada, sin registro | ✅ | Ahora registra en `omitted[]` dentro del JSON de salida (antes solo un log) |
| 3b | Sin validación formal de JSON Schema | ✅ | `enrich_case.py::enrich_document` — `jsonschema.validate()` real contra el schema, antes de aceptar la respuesta |
| 3c | Sin exigir revisión manual antes de `ADOPTAR_HIGH` | ✅ | Veredicto renombrado a `CANDIDATO_HIGH_PENDIENTE_REVISION_MANUAL` — el JSON de salida incluye `confirmado_manualmente: false` explícito. Ningún veredicto de este script autoriza el cambio de default por sí solo. |
| 4 | `active-context.md` con bloque viejo contradictorio (16 queries/67 docs) | ✅ | Reestructurado con secciones "Estado actual" (leer primero) e "Histórico" (marcado explícitamente como superado) |

### Fix adicional no reportado por QA, encontrado por mí en el mismo trabajo
`enrich_document()` (usado por `enrich_case.py` y `compare_effort.py`) no
reintentaba errores de conexión (solo fallaba una vez y devolvía `None`) —
mismo patrón de bug que `classify_luna.py` tenía antes de la petición del
usuario de paralelizar el filtrado, donde 100 workers concurrentes
revelaron `SSLEOFError` en cascada sin reintento. Corregido con el mismo
backoff exponencial en ambos archivos.

## Estado del comparativo high/xhigh ahora mismo

Sigue corriendo la corrida de 12 documentos con el fix de payload (comuna/
tipo_conflicto reales) pero SIN los fixes de la ronda 2 (esos aplican desde
la próxima corrida). Resultados parciales hasta el caso 8/12: 100% de
acuerdo en `revision_manual`, `institucion_decisora` y `tipo_evidencia`, 0
regresiones — mejor que la corrida original (75% institución, 1 regresión),
consistente con que el bug de payload sí afectaba la calidad de `high`. No
es definitivo hasta los 12 casos completos + revisión manual asistida.

## Cómo verificar cualquiera de estos puntos

Todos los archivos mencionados tienen comentarios inline fechados
2026-09-12 explicando el bug y el fix, no solo esta tabla. `git` no está
inicializado en este proyecto, así que no hay diff de commits — el rastro
real está en `_FARO/memory-bank/session-turns.jsonl` (bitácora, con
`--agent-model claude-sonnet-5`) y en estos comentarios.
