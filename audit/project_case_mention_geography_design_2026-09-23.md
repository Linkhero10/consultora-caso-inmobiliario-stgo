# Propuesta de diseño: atribución geográfica proyecto → case_mention

**Estado:** propuesta arquitectónica; no implementada.
**Recomendación:** implementar con cambios como prototipo aislado; no promover a producción hasta superar los gates de validación de este documento.
**Alcance:** corregir la atribución del conteo de proyectos por comuna del dashboard. No modificar el warehouse, la clasificación ni el conteo de conflictos en esta propuesta.

## Resumen ejecutivo

El diagnóstico de base es correcto: project_mention_resolved conecta un project_id con un documento, no con la case_mention que sustenta el nombre del proyecto. El mapa puede entonces transferir a un proyecto la única comuna encontrada en otra mención del mismo documento.

No implementaría tal cual la mitigación de excluir solo excluded_case_mention y non_included_case_mention. Esa regla quita contradicciones explícitas, pero deja document_level_candidate sin resolución y conserva la atribución del proyecto a la comuna del documento. Tampoco asumiría que ambiguous_direct es equivalente a verified_direct.

Propongo separar dos relaciones y componerlas solo cuando ambas estén respaldadas:

1. project mention → case_mention + evidencia de objeto.
2. case_mention → código de comuna resuelto.

El conteo principal por comuna debe usar únicamente relaciones elegibles en ambas etapas, sin fallback desde el documento completo. Los casos ambiguos o sin enlace siguen siendo información útil, pero se reportan como no resueltos y no se asignan silenciosamente. La palabra “verificado” debe describir que la cita aparece literalmente en la fuente, no que el proyecto o su ubicación sean verdad externa comprobada.

Para el primer despliegue calcularía el enlace durante la construcción estática del dashboard, usando un módulo determinista, y conservaría un artefacto lateral reproducible con cada relación candidata y sus hashes. No añadiría todavía una tabla al warehouse canónico: hoy el único consumidor medido es el conteo n_projects y el cálculo reportado tarda alrededor de 0,1 segundos. Si aparece un segundo consumidor analítico real, se puede materializar después la misma relación en una tabla derivada versionada.

## Evidencia revisada y límites del snapshot

La revisión se hizo contra HEAD a6cc1330eb4517c6837d4caaef3e151367c5e11e. Huellas del snapshot leído:

| Insumo | SHA-256 |
|---|---|
| data/warehouse.sqlite | 673A433398B46E320DD48DFFFB72F46F10F29936E2BD3BC0ED9047761FEA0D08 |
| src/project_case_mention.py | 9DD224E8B020CEED51E15A76CD486ECC5B7062D743202833357DC3AF32047474 |
| audit/geografia_blind_spot_comuna_unica_2026-09-23.json | 20C59EA88A51DCD9D490F55D780514C34A7C3450F0C4845BFDC96D5582CD59C1 |

Comprobaciones de solo lectura sobre ese warehouse:

- project_mention_resolved tiene 1.393 filas y 1.393 combinaciones distintas de project_id, document_id y raw_nombre_proyecto; no encontré grupos duplicados de esa clave.
- Hay 1.613 documentos con exactamente un código de comuna distinto entre sus case_mentions con código.
- 2.732 case_mentions tienen código de comuna no vacío; ningún código no vacío quedó fuera de territory.
- No encontré filas donde evidence.document_id difiera de case_mention.document_id.

El informe de blind spot registra 124 filas sospechosas, 118 pares únicos documento-proyecto, 90 pares proyecto-comuna que saldrían del conteo y 19 de 29 comunas afectadas. Esos valores sirven como diagnóstico, no como baseline liberable todavía: el informe no registra el SHA del warehouse ni el del linker que los generaron. Antes de comparar o cambiar el dashboard, hay que reconstruir esos números desde el snapshot con huellas fijadas. Las 1.481 filas de enlaces mencionadas en la documentación pueden superar las 1.393 menciones fuente porque el linker emite una fila por evidencia coincidente; los artefactos deben distinguir filas de enlace, menciones fuente y pares únicos.

También hay drift documental que no cambia esta propuesta, pero puede confundir a quien reproduzca los antecedentes:

- audit/homonym_partition_auditoria.json conserva el estado anterior de 89 revisados y 42 pendientes; active-context.md y el resultado separado de la segunda tanda indican que el universo de 131 ya se intentó completo.
- audit/fix_1c_investigation.md aún dice que 13 pares ambiguous_direct quedaron sin revisar; audit/cierre_frentes_acotados_2026-09-23.json registra la revisión de los 13 grupos únicos como legítimos. Para este diseño tomo el cierre más reciente como estado vigente y el informe anterior como historial no reconciliado.

## Diagnóstico propio

dashboard_data.py construye doc_comuna con una comuna única por documento y luego agrega todos los project_id de ese documento bajo ese código. La protección de comuna única evita el producto cartesiano en documentos con dos o más comunas distintas, pero no demuestra que cada proyecto mencionado pertenezca a la única case_mention geográfica. Por eso n_projects es vulnerable aunque n_conflicts y n_conflicts_backed tengan filtros más estrictos.

project_case_mention.py ofrece una base experimental útil: empareja nombres normalizados con citas de objeto literales y distingue coincidencias incluidas, excluidas, no incluidas y casos documentales sin match. Aun así, el estado verified_direct es una salida algorítmica, no una adjudicación humana ni prueba independiente de geografía. La validación manual reportada de diez enlaces es un buen smoke test, no una estimación de precisión.

Identifiqué tres condiciones que el consumidor futuro debería cerrar antes de confiar en esos estados:

1. La especificación del linker exige que la evidencia y la case_mention pertenezcan al mismo documento, pero la función agrupa la evidencia por case_mention_id y no comprueba explícitamente que evidence.document_id == case_mention.document_id. El snapshot actual no contiene discrepancias (0 filas); falta el guard para entradas corruptas o fixtures adversariales.
2. La comparación acepta que el nombre del proyecto contenga toda la cita, además de aceptar que la cita contenga el nombre. Esto puede convertir una cita genérica o un fragmento corto del nombre en verified_direct. Por ejemplo, “Villa” no debería bastar por sí sola para sustentar cualquier proyecto cuyo nombre contenga esa palabra. Una coincidencia breve debe quedar como candidata ambigua salvo que exista un alias controlado y suficientemente distintivo.
3. La función corta el análisis cuando encuentra una sola case_mention incluida que coincide; no conserva en esa salida coincidencias paralelas con menciones excluidas/no incluidas. Para una salida auditable conviene registrar todos los candidatos y separar el estado resumido de cada mención fuente del estado de cada arista candidata.

No son evidencia de corrupción presente en el warehouse; son brechas entre el contrato deseado y la lógica de enlace que debe endurecerse antes de usarla para una atribución pública.

## Alternativas consideradas

### A. Excluir solo coincidencias en menciones excluidas/no incluidas

Es el cambio más pequeño y detecta contradicción explícita. No basta como solución final: los document_level_candidate siguen heredando la comuna documental, y ambiguous_direct queda tratado como positivo pese a que no identifica una mención única. La usaría solo como control transitorio si la salida se etiqueta claramente como incompleta.

### B. Atribución compuesta estricta en dos etapas — recomendada

Resolver primero el enlace del nombre del proyecto a una case_mention incluida y a su evidencia de objeto; resolver después la comuna de esa misma mención. El proyecto se cuenta en una comuna solo si los dos enlaces pasan los controles. No se usa la comuna única del documento como sustituto.

Es la mejor relación entre alcance y rigor: soluciona la contaminación conocida sin alterar clasificación, conflicto ni identidad de proyecto. Mantiene unresolved como estado real en vez de convertirlo en falso o asignarle la única comuna disponible.

### C. Cambiar el contrato aguas arriba para que cada proyecto se extraiga dentro de una case_mention

Es una solución de raíz potencial, pero requiere cambiar el contrato del enriquecimiento/clasificación, validar una nueva salida y probablemente reprocesar datos. No la haría parte de este arreglo. Además, project_mention_resolved no debe recibir simplemente una columna case_mention_id: un proyecto puede relacionarse con varias menciones y una mención puede describir varios proyectos. La cardinalidad correcta es una relación puente muchos-a-muchos, no un atributo único.

## Diseño recomendado

### 1. Mantener inalterada la identidad fuente

Conservar project_mention_resolved como relación histórica proyecto-documento-mención de texto. No reescribirla ni reinterpretar una de sus filas como si ya tuviera case_mention_id. La nueva atribución se produce aparte y con versión propia.

### 2. Construir candidatos de enlace con controles duros

Congelar el linker experimental actual como baseline reproducible. Si se modifica su criterio de coincidencia, crear una versión nueva del algoritmo en vez de alterar silenciosamente el significado de verified_direct.

Para cada combinación fuente de proyecto, documento y nombre:

- Solo aceptar como enlace textual elegible una cita de objeto con verified=1, asociada al mismo document_id que la case_mention y al mismo documento de la mención de proyecto.
- Exigir decision_final_amplio=include para el universo principal. Exclude, uncertain, insufficient_content y demás estados se conservan en provenance, pero no generan asignación de comuna.
- Aceptar coincidencia literal suficientemente distintiva o alias explícito y versionado. Un fragmento genérico, coincidencia semántica o embedding solo crea una candidata a revisión.
- Recoger todas las menciones coincidentes, no detenerse en la primera positiva. Esto permite detectar una colisión entre include y exclude, dos proyectos con nombres similares o varias menciones geográficas.
- Conservar project_id, document_id, raw_nombre_proyecto, case_mention_id, evidence_id, decisión de la mención, método de match, motivo, versión del algoritmo y huellas de entradas. Los textos originales permanecen en evidence y se referencian por ID.

El resultado no debe reducir cada caso inmediatamente a un booleano. El estado del enlace y el de la geografía son dimensiones diferentes.

### 3. Resolver comuna desde esa misma mención

Para cada case_mention enlazada, obtener el código únicamente desde la geografía de esa mención: primero el codigo_comuna_ine válido contra territory; si está vacío, la resolución determinista ya existente en case_mention_geography. Registrar cuál fuente se usó.

Si el código falta, no pertenece al universo territorial o hay fuentes de geografía incompatibles, el enlace proyecto-mención puede seguir siendo útil, pero no se convierte en project-comuna. Nunca volver al código de otra mención del documento.

La relación geográfica resultante debe manejar estados separados, como:

- asignación textual directa con comuna resuelta;
- candidato directo con varias case_mentions;
- mención no incluida;
- nombre visto solo a nivel documental;
- enlace directo sin comuna resuelta;
- código fuera del universo;
- geografía conflictiva que requiere revisión.

Los nombres son ilustrativos; el contrato final debe usar enums estables y exhaustivos. En particular, ambiguous_direct no se promueve al conteo principal por el mero hecho de que los casos focales revisados antes resultaran legítimos. Puede producir una vista de sensibilidad si todos los candidatos apuntan a la misma comuna, pero debe seguir marcado como candidato y no confundirse con un enlace único proyecto-mención.

### 4. Definir n_projects sin ambigüedad

En el mapa principal, contar valores distintos de project_id por codigo_comuna_ine solo cuando exista una atribución textual directa admisible, de una case_mention incluida, con comuna propia resuelta. Un project_id puede contarse en más de una comuna solo cuando haya un enlace elegible independiente en cada comuna; si los enlaces se contradicen o la identidad es dudosa, se envía a revisión en lugar de declarar multi-comuna automáticamente.

Los document_level_candidate, ambiguous_direct, excluded_case_mention, non_included_case_mention y las menciones sin comuna no se presentan como geográficamente resueltos. Tampoco se eliminan del corpus ni del registro del proyecto: simplemente no forman el numerador geográfico estricto.

La UI debe llamar al indicador algo como “proyectos con atribución textual directa a una comuna” y explicar que las citas se validan como texto literal. No debe decir “ubicación real verificada”. Para que el usuario vea la cobertura, el panel de detalle puede mostrar por separado cuántos proyectos o pares quedan sin atribución; no los suma a ninguna comuna.

No tocar n_conflicts, n_conflicts_backed, n_documents ni n_actors en este cambio.

### 5. Persistencia proporcional al uso actual

No añadiría ahora tablas nuevas a data/warehouse.sqlite. El cálculo es determinista, barato y tiene un consumidor medido. El pipeline puede calcular los enlaces una vez durante la construcción estática y emitir, junto con el dashboard, un sidecar JSONL/JSON de auditoría con:

- versión y huellas de algoritmo, warehouse y configuración;
- cantidad de menciones fuente, enlaces candidatos, pares únicos y atribuciones proyecto-comuna;
- distribución por estado de enlace y de geografía;
- lista de enlaces candidatos con IDs de provenance;
- comparación del conteo geográfico anterior y nuevo por código INE.

Así se puede auditar el resultado sin migrar la base ni recalcularlo en cada navegador. Si luego conflict, análisis de red u otro consumidor requiere consultar el enlace en SQL, el mismo producto puede materializarse como tabla derivada project_case_mention_link_v2. No mutar project_mention_resolved ni mezclar la tabla derivada con datos fuente.

## Alcance

Incluye:

- reemplazar para n_projects la inferencia documento→proyecto por una atribución compuesta proyecto→case_mention→comuna;
- mantener estados candidatos sin asignar cuando la evidencia no alcance;
- nuevo artefacto reproducible, tests y rótulo/metodología del indicador;
- comparar la serie por comuna antes/después con el warehouse y código fijados.

No incluye:

- cambios a clasificación LLM, prompt, schema o enriquecimiento;
- cambios al detector de conflictos ni a conflict_evidence_backing;
- relajar include/exclude ni modificar casos revisados;
- v2 semántico, embeddings, alias sin curación o homónimos automáticos;
- ubicación a nivel de dirección, coordenada, manzana censal o sitio focal;
- alterar el conteo de conflictos y actores.

## Riesgos y controles

| Riesgo | Control propuesto |
|---|---|
| Un literal corto o genérico produce falso enlace | Reglas de distintividad, alias explícitos versionados y casos negativos de regresión; los casos débiles se quedan como candidatos. |
| Evidencia pertenece a otro documento o mención | Validar los tres document_id de project mention, case_mention y evidence antes de emitir una arista; abortar o poner en cuarentena la fila inconsistente. |
| Un proyecto aparece varias veces o en varias menciones | Mantener aristas separadas y deduplicar el indicador final por project_id + comuna, nunca por conteo de citas. |
| Un proyecto es realmente lineal o multi-comuna | Aceptar cada comuna solo por evidencia propia y mantener una razón/estado explícito de multi-comuna; no inferirlo de una contradicción. |
| Menor n_projects se interpreta como desaparición de proyectos | Renombrar el indicador, mostrar coverage/unresolved en separado y conservar la medición anterior como serie histórica document-level. |
| Cambio de lógica y comparación sobre la misma muestra usada para diseñarlo | Congelar reglas antes de una revisión ciega nueva; separar muestra de diseño, muestra de validación y stress sample. |
| Deriva de fuente o de algoritmo | Hashes obligatorios del warehouse, código del linker, configuración y sidecar; abortar la comparación si cambian sin regenerar el baseline. |

## Plan de tests y migración

### Fase 0 — congelar baseline

Registrar SHA-256 del warehouse y del código, versión del método, salida JSONL completa del linker, resumen por estado y métricas actuales por comuna. Recalcular también los 118 pares únicos y los 90 pares proyecto-comuna del informe; si los números difieren, documentar cuál snapshot produjo cada serie. No editar el warehouse.

### Fase 1 — pruebas unitarias del enlace

Cubrir al menos:

1. Proyecto citado literalmente dentro de evidencia de objeto incluida en su misma case_mention y documento.
2. La misma cita bajo otra case_mention con comuna distinta: la comuna de la mención no se propaga al proyecto.
3. Cita presente solo en exclude, uncertain o insufficient_content: no asignación positiva.
4. Ninguna cita de objeto verificada: estado unresolved, no “no existe el proyecto”.
5. Cita no verificada o con rol acción/geográfica: no enlace directo.
6. project mention, case_mention y evidence con document_id incompatibles: no enlace; error/cuarentena visible.
7. Fragmento genérico del nombre: no direct; un alias controlado sí puede pasar si está aprobado y versionado.
8. Una mención incluida más una coincidencia excluded del mismo nombre: conservar ambas señales y no esconder la colisión por short-circuit.
9. Varias citas para la misma case_mention: no inflar el conteo de proyectos.
10. Varias case_mentions incluidas con el mismo código versus códigos distintos: ambas quedan ambiguas para el enlace; la primera puede ir a sensibilidad geográfica, la segunda a unresolved/review.
11. Código vacío, inválido o fuera de territory: enlace textual conservado, ninguna comuna inferida.
12. Proyecto respaldado en varias noticias: contar una vez por comuna; permitir varias comunas únicamente con enlaces distintos elegibles.

### Fase 2 — integración no productiva

Ejecutar sobre copia/hash fijado. Comprobar que ninguna de las 118 parejas sospechosas entra al conjunto principal por evidencia de una mención no incluida; medir qué hace el linker con document_level_candidate y ambiguous_direct en vez de dejarlos pasar. Congelar los IDs de regresión para que una reejecución revele cambios, no solo reproduzca totales agregados.

Verificar que solo cambie n_projects y su texto explicativo: n_conflicts, n_conflicts_backed, n_documents, n_actors y el resto del JSON del dashboard deben ser idénticos al baseline. La misma entrada debe producir el mismo hash de sidecar en dos corridas independientes.

### Fase 3 — revisión independiente antes del mapa público

Con el algoritmo congelado, tomar una muestra nueva y ciega de atribuciones positivas directas para adjudicar proyecto, mención y comuna contra las fuentes originales. Revisar también una submuestra separada y estratificada de ambiguous_direct y document_level_candidate para estimar qué proporción es recuperable; esa muestra dirigida no sirve para estimar prevalencia del universo.

Fijar antes de mirar el resultado el criterio de aceptación. Para un indicador que se presenta como directo, mi criterio mínimo es cero atribuciones erróneas observadas en la muestra positiva independiente y ninguna asignación automática de filas no resueltas. Esto no prueba que el error poblacional sea literalmente cero; solo habilita la versión evaluada dentro de sus límites. Cualquier falso positivo observado bloquea la promoción hasta explicar y corregir la causa, seguido de un conjunto de validación nuevo.

### Fase 4 — migración controlada

Solo después de gates unitarios, integración y revisión independiente: cambiar el mapa para consumir la nueva proyección, actualizar metodología/nota de datos, publicar los conteos antes/después y los estados no resueltos, y conservar el artefacto anterior con sus hashes. No rebuild del warehouse, salvo que una decisión posterior opte explícitamente por materializar la relación derivada.

## Recomendación de gate

**implementar_con_cambios**, limitado a un prototipo determinista y reversible para el conteo de proyectos por comuna.

No implementar tal cual el filtro de solo excluded/non-included: es una mitigación parcial. Antes de producción, cerrar los tres controles del linker, ejecutar la integración sobre un snapshot hash-pinned y aprobar una revisión independiente nueva. Hasta entonces, el dashboard público y el warehouse permanecen intactos; los candidatos ambiguos/no resueltos no se promueven.

La salida esperada de la siguiente etapa no es “resolver todo proyecto”, sino poder decir con precisión:

- cuántos proyectos tienen atribución textual directa a una comuna;
- cuántos siguen como candidatos ambiguos o solo documentales;
- qué evidencia sustenta cada asignación;
- qué versión del algoritmo y qué warehouse produjeron el resultado.

## Fuentes del repositorio consultadas

- src/project_case_mention.py — linker experimental y límites de la regla literal.
- src/dashboard_data.py — cálculo actual de comuna única y n_projects.
- src/build_conflicts.py — separación entre evidencia de conflicto y mención documental de proyecto.
- src/build_geography.py — resolución de comuna a nivel case_mention.
- docs/architecture.md y docs/methodology.md — identidad por capas y no propagación de relaciones.
- audit/geografia_blind_spot_comuna_unica_2026-09-23.json — medición del punto ciego.
- audit/cierre_frentes_acotados_2026-09-23.json — cierre más reciente de los grupos focales.
- audit/homonym_partition_auditoria.json y audit/homonym_low_batch2_resultado.json — auditoría de distribución geográfica y su segunda tanda.
- audit/fix_1c_investigation.md — antecedentes de falsos positivos; contiene estados históricos que se deben leer junto al cierre más reciente.
