# Auditoría integral para Sol — segundo agente revisando el trabajo de Claude

**Fecha**: 2026-09-18. Este documento es el punto de entrada: qué ya se revisó, qué falta, y qué archivos
usar para cada pieza. El objetivo es que Sol pueda actuar como segundo agente sobre el resto del trabajo
técnico de esta sesión, con el mismo rigor que ya aplicó a las dos piezas anteriores.

## Ya revisado por Sol (no repetir)

1. **Cola de 253 pares de fusión de proyectos** — confirmó 222/253, refutó 31/253. Las 31 correcciones
   fueron reverificadas por Claude contra evidencia real y aplicadas. Resultado final: 133 fusionados /
   120 separados. Ver `Auditoria/integracion_v1/project_review_queue_resuelta.json` (ya actualizado) y
   `Auditoria/validacion_humana_v3_2/INFORME_auditorias_sol_2026-09-18.md` sección 1.
2. **Muestra de 50 documentos de validación humana del enrichment** — 21 ok / 17 error_menor / 12
   error_grave. Hallazgo estructural: falta un gate `documento → unidad de caso` antes de la extracción.
   Ver el mismo informe, sección 2.

## Pendiente de revisar ahora — 2 piezas nuevas

### 3. Lógica de `resolution_status` del puente (`build_case_project_bridge.py`)

Esta es la pieza que decide, para cada actor/institución/evento, a qué `project_id` queda vinculado — es
el insumo directo de cualquier análisis de redes (arco de Darío). La regla:

- `resolved_explicit`: `proyecto_asociado_raw` no vacío y coincide con una mención del documento.
- `resolved_single_project`: `proyecto_asociado_raw` vacío, pero el documento menciona exactamente 1
  proyecto (sin ambigüedad real).
- `unresolved_ambiguous`: `proyecto_asociado_raw` vacío Y el documento menciona 2+ proyectos — nunca se
  adivina cuál.
- `unresolved_no_project`: el documento no menciona ningún proyecto con nombre propio.

Conteos reales: `resolved_explicit` 5281, `resolved_single_project` 8447, `unresolved_ambiguous` 2895,
`unresolved_no_project` 3796 (total 20419).

**Qué revisar**: `Auditoria/integracion_v1/bridge_audit_package_para_sol.json`, clave
`muestra_resolution_status` — 10 registros aleatorios por cada uno de los 4 estados (40 en total, semilla
fija 20260918), cada uno con `proyecto_asociado_raw`, las menciones del documento, y una pregunta directa:
¿la regla se aplicó bien? El código fuente está en `Trabajo/scripts/build_case_project_bridge.py`,
función `resolve_association()`.

### 4. Candidatos de prefijo del crosswalk entidad↔actor (`reconcile_classification_layer_with_v3_2.py`)

Al conectar la capa antigua de clasificación (`entity_role`) con la capa v3.2 (`enrichment_actor_v3_2`),
5143/8215 coincidieron por nombre exacto. Otros 320 NO coinciden exactamente pero el nombre v3.2 empieza
con el nombre de clasificación seguido de más texto (caso real encontrado: v3.2 a veces embebe el cargo
en el nombre, ej. "Sergio Ventura" → "Sergio Ventura, Director de Obras..."). Estos 320 quedaron marcados
como candidato, **nunca fusionados automáticamente**.

**Qué revisar**: mismo archivo, clave `muestra_candidatos_prefijo_entity_crosswalk` — 30 casos aleatorios.
Para cada uno, decir si son genuinamente la misma persona/institución (en cuyo caso se pueden promover a
match confirmado) o si el prefijo es engañoso (dos entidades distintas que casualmente comparten las
primeras palabras del nombre). Código fuente en
`Trabajo/scripts/reconcile_classification_layer_with_v3_2.py`, función `build_entity_actor_crosswalk()`.

## Cómo responder

Igual que las veces anteriores: no hace falta correr código. Cada registro ya trae lo necesario. Marcar
`veredicto_sol` solo en los que se esté en desacuerdo o haya duda real; dejar `null` en los que se
confirme. Un `resumen_revision_sol` al final del archivo, como en las auditorías anteriores, ayuda a que
la revisión quede auditable.

## Código fuente completo (para revisión de lógica, no solo de datos)

Adjuntos en esta entrega:
- `Trabajo/scripts/build_case_project_bridge.py`
- `Trabajo/scripts/resolve_project_review_queue.py`
- `Trabajo/scripts/reconcile_classification_layer_with_v3_2.py`
- `Trabajo/scripts/build_bridge_audit_package_for_sol.py` (el script que generó la muestra de esta
  entrega — para que Sol pueda verificar que el muestreo mismo no está sesgado)

## Estado de verificación técnica al momento de esta entrega

- Suite de tests: **144/144**.
- `PRAGMA integrity_check = ok`, `foreign_key_check` vacío en `warehouse_v3_2_bridge.sqlite`.
- Ningún script de esta entrega llamó a la API (todo el trabajo de esta sesión, incluidas las 31
  correcciones y este paquete, fue determinista/local, sin costo).
