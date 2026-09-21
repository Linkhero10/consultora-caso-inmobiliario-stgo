# Implementación Codex — correcciones de integridad (2026-09-12)

## Alcance

Se corrigieron únicamente capas downstream y de runtime. No se detuvo ni se
editó `brightdata_discovery.py`, ni se modificaron los artefactos que Claude
estaba escribiendo durante la clasificación de producción.

## Correcciones aplicadas

- `snapshot_discovery.py`: clasifica contratos; el snapshot v3 conserva las
  filas legacy en un archivo separado y deja el snapshot principal solo con
  discovery v2.
- `fulltext_acquisition_v2.py`: preserva todos los orígenes por URL; no mezcla
  filas legacy; verifica que los artefactos del manifest existan y sean JSON
  válido antes de considerar una URL procesada; escribe contenidos con
  reemplazo atómico.
- `dedupe_fulltext.py`: la vista materializada puede recuperar el lineage
  vigente desde los JSON de contenido, sin mutar el log append-only; omite
  contenidos truncados en vez de convertirlos en hashes falsos.
- `classify_luna.py` y `enrich_case.py`: omiten contenidos corruptos sin
  tumbar toda la corrida; queda validación formal del schema y semántica
  correcta de `evidence_verified`.
- `pipeline_lock.py`: mutex de `run_state` con token de propietario; no borra
  un mutex de un proceso vivo, no elimina un lock de etapa reemplazado por otro
  proceso, registra `state_schema_version=2` y marca `skipped` con hora de
  término.
- `read_jsonl_tolerant()` admite ahora `fail_on_invalid=True`; dedupe y la
  reparación bloquean ante JSONL corrupto en vez de publicar una vista parcial.
- `repair_fulltext_lineage.py`: herramienta segura para reconstruir los
  355 orígenes desde un snapshot, sin pagar nuevamente clasificación. Por
  defecto simula; exige `--apply` y bloquea si alguna etapa productora o
  consumidora está activa. Después exige reconstruir la vista de dedupe.

## Verificación

Prueba local reproducible:

```text
Ran 8 tests ... OK
```

También se validó la sintaxis AST de los siete scripts modificados. No se
ejecutaron llamadas API ni se relanzó producción.

## Estado y límite

La corrida actual de clasificación de Claude debe tratarse como provisional:
usa un `fulltext_v2` generado sobre el snapshot pre-v3. La reparación recuperó
los orígenes alternativos, pero Claude confirmó 67 URLs legacy sin
`periodo`/`nivel`; esas filas todavía no pueden presentarse como parte del
contrato v2. El texto y las decisiones no quedan automáticamente invalidados,
pero no corresponde cerrar el pipeline ni lanzar enriquecimiento como si el
corpus estuviera homogéneo.

Cuando Claude libere la corrida, el orden seguro es:

1. Crear un snapshot v3 nuevo del discovery ya detenido.
2. Aislar las 67 URLs legacy y ejecutar adquisición/dedupe con el contrato
   v2, o usar `repair_fulltext_lineage.py --snapshot-run-id <id> --apply` si
   el texto v2 es idéntico y se quiere evitar nuevas llamadas.
3. Reconstruir la vista de dedupe y verificar los orígenes recuperados (la
   reparación actual deja 375 URLs con múltiples orígenes en fulltext).
4. Reutilizar o volver a clasificar solo después de esa comprobación.

El bug de reanudación dentro de una consulta del discovery sigue pendiente y
no se tocó porque Claude aún tenía ese proceso activo.

La revisión final queda registrada también en
`Auditoria/codex_fleet/OPEN_FINDINGS_20260912.md`, incluyendo la evidencia
actual: 9 tests OK, AST de 8 scripts OK, JSONL real validado estrictamente y
67 filas legacy detectadas.
