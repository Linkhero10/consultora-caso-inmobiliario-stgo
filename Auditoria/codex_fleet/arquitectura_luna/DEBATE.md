# Debate cruzado de auditorías — arquitectura/línea de datos/runtime

Fecha: 2026-09-12  
Modo: solo lectura; sin Claude, APIs ni procesos caros.  
Fuentes contrastadas: `arquitectura_luna/FINDINGS.md`, `datos_lineage_luna/FINDINGS.md` + `evidence.json`, `runtime_luna/FINDINGS.md`, código y artefactos del proyecto.

## Conclusión ejecutiva

Los informes son mayoritariamente concordantes. No hay contradicción material sobre la invalidez de la frontera v1/v2: todos observan el mismo problema desde niveles distintos. La causa raíz transversal es que el pipeline carece de una identidad de corrida/contrato que viaje desde discovery hasta cada salida y que se haga cumplir en los gates. La evidencia de snapshot es íntegra por bytes/hash, pero eso no significa que sea semánticamente compatible con v2.

El segundo problema de mayor impacto es pérdida silenciosa de cobertura: discovery reanuda por “existe cualquier fila del combo”, y fulltext reanuda por URL. Son fallas distintas, ambas destruyen la posibilidad de afirmar completitud. Dedupe y locks tienen fallas reales de crash-safety/liveness, pero son riesgos latentes porque todavía no existen outputs v2 de producción.

## Causa raíz versus síntoma

| Cluster | Hallazgos relacionados | Causa raíz | Síntomas/evidencia | Juicio |
|---|---|---|---|---|
| Contrato y versionado | F-001 + DL-03 + parte de DL-01 | No existe frontera de contrato por corrida: faltan versión de registro/hash, fingerprint de código/config y gate de campos requeridos | 95 filas del snapshot sin `periodo/nivel`; 67 filas fulltext con esos campos vacíos; `run_state` legacy junto a estado nuevo; proceso activo iniciado antes de los últimos parches | Unificar como P0-1. F-001/DL-03 son el mismo defecto observado en dos etapas; DL-01 es su manifestación operacional. |
| Reanudación de discovery | RL-01 | Completitud de query inferida desde cualquier resultado, en lugar de marker `query_completed`/ranks | Crash tras rank 1 hace que el combo quede omitido en el ciclo siguiente | P0-2 independiente; no se corrige con dedupe posterior. |
| Lineage por URL | F-002 | URL usada como identidad global antes de consolidar `origins[]` | 355 URLs con lineages distintas; el caso Infraestructura Pública conserva solo la primera | P1; dedupe no puede recuperar lo que fulltext descartó. |
| Idempotencia incremental | F-003 | `done_*_urls` sin hash de texto/clasificación, snapshot o contrato | Cambios de contenido/nuevos orígenes para la misma URL quedan omitidos | P1; DL-01/DL-02 agravan el problema pero no lo sustituyen. |
| Corrida pre-fix y fallos transitorios | DL-01 + DL-02 | No se aísla una corrida larga al cambiar código/contrato ni se registra fingerprint de implementación | Manifest observado contiene `http_error_429/503` y errores vacíos aunque código vigente dice no persistirlos; `run_state` no atribuye la corrida | P0-3 para aceptar el corpus actual: cuarentenar y relanzar; no es un falso positivo por estar el PID vivo. |
| Persistencia de dedupe | F-004 + RL-04 | Eventos y vista materializada no se publican como unidad transaccional, sin `fsync`/temp+replace/marker de batch | Puede perder `origin_added` después de un `canonical_elected` o dejar JSONL parcial | P1 latente; ambos hallazgos son manifestaciones del mismo defecto, no dos bugs independientes. |
| Locks y estado | RL-02 + F-006 + RL-03 | No hay recuperación/liveness ni ownership seguro del mutex; `running` es un semáforo sin prueba de proceso/versión | Crash duro deja lock+`running`; PID muerto o lock ausente no se distingue; timeout de 5 s puede romper exclusión | P1. RL-03 es un defecto condicional real; RL-02/F-006 son la misma carencia de recuperación. |
| Gates de salida | F-005 + DL-06 | Productores no comparten un gate semántico único | Clasificación no valida localmente schema; `evidence_verified=true` para no-include con cita vacía | F-005 P1 antes de producción; DL-06 P2 semántico, no compromete el gate de `include`. |

## Posibles falsos positivos o sobreclasificaciones

- **DL-04 (“no hay outputs v2”)** no es un bug de implementación por sí mismo: el upstream estaba ejecutándose y los consumidores correctamente no habían sido lanzados. Es una condición de preparación/cierre, útil para no declarar producción, pero no debe contarse como defecto adicional.
- **DL-05 (benchmark legacy)** es una advertencia de alcance, no una falla del comparador: el fixture declara v1 y el veredicto `MANTENER_XHIGH` está marcado como no confirmado manualmente. Solo se vuelve defecto si se usa para justificar una decisión v2.
- **DL-02 (429/503 persistidos)** es evidencia temporal de la corrida pre-fix, no refutación del código vigente. Precisamente demuestra que faltó aislamiento/versionado de la corrida larga; no debe “arreglarse” borrando filas.
- **DL-06** es una ambigüedad de semántica (`true` puede significar “la cadena vacía es grounded” o “hay una cita verificada”). Es real para consumidores, pero P2 mientras el contrato downstream no use ese booleano como prueba de inclusión.
- **RL-02** no prueba que el lock actual esté huérfano: la observación confirmó PID 42408 vivo y lock presente. Prueba que un `os._exit` deja estado irrecuperable automáticamente; es un riesgo de diseño, no una corrupción actual.
- **RL-03** requiere I/O/contención superior a 5 s. La prueba con timeout reducido es válida contra el mecanismo, pero la probabilidad operacional es menor que RL-01/F-001; por eso queda P1 condicionado, no P0.
- **Integridad de hash del snapshot** pasa: ambos informes confirman SHA-256 y conteo de líneas. El hallazgo es semántico (campos ausentes/mezcla), no que el archivo se haya alterado después de crear la meta.

## Contradicciones aparentes resueltas

### Snapshot legacy: 95 versus 67

No se contradicen. El snapshot contiene 95 filas legacy sin campos; fulltext solo materializó 67 URLs de ese subconjunto (por deduplicación de URL y filtros/resultados procesados). La reducción posterior no “corrige” el legacy: oculta parte de él.

### Dedupe: pérdida de eventos versus manifest truncado

Son dos superficies del mismo defecto de publicación. El log de eventos puede quedar completo solo hasta la mitad de un batch y bloquear el reintento por URL; la vista materializada puede truncarse durante `write_text`. La solución debe ser una publicación transaccional/reconstruible desde eventos, no dos parches aislados.

### Locks: proceso vivo versus falta de recuperación

El proceso observado está vivo, por lo que no hay prueba de huérfano actual. El runtime sí demuestra que la terminación dura salta el `finally`; `upstream_stage_is_running()` no comprueba PID ni lease. Por tanto, es un fallo de recuperación/liveness, no evidencia para matar el proceso vigente.

### Reanudación: combo de discovery versus URL de downstream

RL-01 ocurre antes de fulltext y pierde ranks restantes de una respuesta SERP. F-003 ocurre después y omite cambios/nuevos orígenes de una URL ya vista. Ambos requieren claves de completitud/versionado diferentes; dedupe no compensa ninguno.

## Ranking final para el coordinador

### P0 — impiden aceptar el corpus como producción

1. **P0-1 — Frontera de contrato/versionado ausente:** F-001 + DL-03 + DL-01. Aislar los 95 registros legacy y la corrida pre-fix; exigir versión/fingerprint/hash de entrada antes de aceptar cualquier salida.
2. **P0-2 — Discovery no reanudable por query parcial:** RL-01. Sin marker de completitud, el lote puede terminar con cobertura perdida e invisible.
3. **P0-3 — Manifest actual contaminado por outcomes de corrida pre-fix:** DL-02, entendido como consecuencia de P0-1. No borrar: cuarentenar intentos, reconstruir vista productiva y relanzar bajo contrato vigente.

### P1 — corregir antes de activar downstream/cerrar pipeline

1. **P1-1 — Pérdida de orígenes por deduplicación temprana de URL:** F-002.
2. **P1-2 — Idempotencia por URL sin versión de contenido:** F-003.
3. **P1-3 — Publicación no transaccional de dedupe:** F-004 + RL-04.
4. **P1-4 — Liveness/recuperación de locks y estado:** RL-02 + F-006; agregar ownership seguro al mutex (RL-03).
5. **P1-5 — Falta de `jsonschema.validate()` en clasificación:** F-005.

### P2 — corregir antes de reporting y métricas de calidad

1. **P2-1 — Semántica de `evidence_verified` para decisiones no-include:** DL-06.
2. **P2-2 — Separación explícita del benchmark legacy v1 frente a decisiones v2:** DL-05. No es un bug mientras se mantenga su rotulado y no se use para promover configuración v2.
3. **P2-3 — Documentar como estado de readiness la ausencia de outputs downstream:** DL-04. No abrirlo como defecto separado.

## Condición de cierre recomendada

No promover el snapshot/corpus actual. Cerrar P0 cuando exista una corrida aislada y versionada, snapshot validado semánticamente, discovery reanudable por `query_completed`, fallos transitorios fuera de la vista procesada y una reconstrucción limpia. Luego cerrar P1 con dedupe transaccional, lineage multi-origen, claves de reanudación por versión y gates homogéneos; recién después ejecutar clasificación/enrichment v2 y sus métricas.

