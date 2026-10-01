# Paso a paso: de principio a fin

Guía operativa para construir este tipo de producto desde cero, o ampliarlo con documentos nuevos, sin repetir los
errores que costaron la mayor parte del trabajo. Cada paso dice **qué hacer**, **el comando o archivo**, y **la
puerta** (condición que debe cumplirse antes de seguir). El porqué de cada regla está en los
[estándares](standards.md) (E1–E14).

Convención: las etapas 1–6 dependen del corpus de terceros y de la API de LLM (no se versionan); las 7–14 son
derivadas y se reconstruyen con `python src/rebuild.py`. Nunca se lanza una corrida pagada sin autorización explícita
para esa corrida (E14).

## Fase A — Diseño (antes de escribir código)

1. **Define las unidades y sus claves.** Escribe qué es un documento, una mención, un proyecto, un caso, un conflicto y un
   actor; la clave estable de cada uno y la cardinalidad entre ellos. Gate: un documento con dos conflictos y un
   conflicto con dos proyectos se pueden representar sin forzar. (E1)
2. **Define el contrato de extracción incluyendo los vínculos.** Todo par de entidades relacionadas dentro de un documento
   (proyecto ↔ mención, actor ↔ proyecto) lo declara el extractor con un índice verificable. Gate: el contrato tiene un
   segundo esquema, generado, para el registro persistido. (E2, E7) → `config/enrichment_schema.json`,
   `src/build_enrichment_record_schema.py`.
3. **Decide dónde viven las decisiones humanas.** `config/`, llaveadas por identificador estable, con evidencia y
   validación al cargar. Gate: ninguna decisión está llaveada por nombre. (E5)
4. **Diseña el descubrimiento con medición de cobertura.** Ventanas de fecha para todas las fuentes y un denominador
   externo (archivos de medios, una base de casos ya documentados). Gate: hay un plan para medir recall. (E13)
5. **Instala la higiene desde el primer commit.** `tests/test_release_hygiene.py`, `src/rebuild.py`,
   `src/render_docs_stats.py`, `.gitattributes` con LF. (E9–E11)

## Fase B — Corpus y extracción (con costo; requiere autorización)

6. **Descubre y descarga texto.** `src/discovery.py`, `src/fulltext_acquisition.py`. Gate: distribución de fechas por
   fuente revisada; documentos sin fecha contados.
7. **Clasifica** (`src/classify.py`). Piloto de 10–30 documentos con resultado esperado conocido; luego validación humana
   de una muestra aleatoria con veredictos **en tabla** (id, veredicto, motivo). Gate: error medido aceptable y decisión
   explícita de escalar con presupuesto. (E3)
8. **Extrae con LLM.** Ensayo sin gasto: `python src/enrich.py --run-name main`. Corrida pagada:
   `python src/enrich.py --run-name main --confirm-paid-run --max-cost-usd <tope>`. Gate: 0 registros cuarentenados sin
   revisar; cada cita verificada como subcadena literal; costo registrado. (E7, E14)

## Fase C — Construcción derivada (sin costo)

9. **Base y extracción → warehouse de etapa.** Con el corpus: lo produce el constructor de la capa base y
   `python src/build_enrichment_tables.py`. Sin el corpus: `python src/extract_stage_warehouse.py --stage enrichment`.
10. **Revisión de unidad de caso por documento.** `config/document_case_unit_review.json` (una fila por documento, con
    evidencia si corrige). Gate: todo documento extraído tiene fila.
11. **Reconstruye todo:** `python src/rebuild.py` (o `--from <etapa>`; `--list` muestra el orden). Las etapas son:
    tablas de extracción → proyectos → resolución de identidad → duplicados → conflictos → actores → red → geografía →
    tablero → manifiesto → cifras de la documentación.
12. **Identidad de proyectos.** La cola `project_review_queue` debe quedar sin pares abiertos. Cada decisión nueva va a
    `config/project_identity_decisions.json` (pareja exacta de `project_id`, clase de identidad, evidencia literal con
    hashes). Si cambia el conjunto de proyectos: `python src/rebuild.py --regenerate-baseline "motivo"`. Gate: el
    resolvedor falla cerrado si una decisión no coincide con la cola o con la evidencia. (E5, E6)
13. **Huecos de vínculo.** Menciones sin `case_mention_index`: adjudica a mano en
    `config/project_mention_index_corrections.json` (con cita); elegibilidad de una mención excluida:
    `config/case_mention_eligibility_adjudications.json`; geografía de una mención en grupo de duplicados:
    `config/reviewed_duplicate_group_geography_links.json`. Una adjudicación resuelve una cosa, no transfiere el resto.
13b. **Conflictos duplicados.** Una misma disputa puede aparecer como varios conflictos (alias, componentes, edificios de un mismo
    fallo). Genera parejas candidatas (respaldo compartido, documentos compartidos, etiquetas parecidas), adjudícalas con evidencia
    literal siguiendo `docs/protocolo_adjudicacion_duplicados.md` y registra las fusiones en
    `config/conflict_merge_decisions.json` (pareja de `project_id`, motivo, cita literal). Compartir un artículo, una inmobiliaria o un
    tribunal NO basta; ante la duda, no fusionar. Tras fusionar, vuelve a clasificar el alcance
    (`python src/scope_jev.py --classify-conflicts ...`) porque los conflictos fusionados tienen otro `conflict_id`.
14. **Verifica.** `python -m pytest -q` debe quedar en verde, incluidas higiene, orden, cifras y versión. Gate: el bloque de
    cifras de README/START_HERE coincide con el warehouse (`python src/render_docs_stats.py --check`).

## Fase D — Validación y publicación

15. **Decide qué se puede afirmar.** Antes de cerrar, mide de extremo a extremo con una muestra ciega nueva (paso 16).
    Las cifras de la documentación deben declarar el resultado y sus límites. (E3, E4)
16. **Validación ciega de extremo a extremo.**
    1. Arma la muestra (aleatoria + dirigida a los conflictos sin respaldo):
       `python src/build_conflict_holdout.py --output-dir intermediate/review_samples/blind_validation --seed <semilla> --main-n 60 --stress-n 20 --no-exclusion`
       (si hay una validación previa, pasa `--calibration-ids` con sus IDs para excluirlos). La muestra no contiene ningún campo del detector.
    2. Copia `docs/protocolo_validacion_ciega.md` a esa carpeta como `REVIEW_INSTRUCTIONS.md` y entrégaselo a un revisor
       independiente (idealmente humano; si es un modelo, sin permiso para invocar otros agentes y sin acceso al warehouse).
    3. El revisor escribe `verdicts.json` (un veredicto por conflicto, con cita literal).
    4. Puntúa: `python src/score_blind_validation.py` → `audit/blind_validation_report.json` (intervalos de Wilson; veredicto
       según el sistema marque respaldo o no; acuerdo con el respaldo).
    5. Resume el resultado y sus límites en `audit/validation_summary.json` y `audit/data_quality_report.md`.
    Gate: los veredictos se cruzan con el sistema **después** de recibirse.
17. **Publica.** `python src/rebuild.py`, luego `python -m pytest -q`; commit; PR. El PR debe llevar las cifras generadas,
    el resultado de la validación y los límites conocidos. Tras fusionar, completa el manifiesto:
    `python src/generate_run_manifest.py --release-commit <SHA>`.

## Filtro de alcance con un modelo de decisión (piloto)

La validación ciega mostró que el error grave del producto es sobre todo de **alcance** (disputa inexistente, tema fuera
del estudio). Eso es clasificación con opciones fijas, no extracción. `src/scope_jev.py` prueba un modelo de decisión (Jev,
vía Requesty, modelo fijo `typesafe/jev-1.13.0`, con la misma `REQUESTY_API_KEY` de la extracción; ~US$0,04 por millón de tokens de entrada; la corrida de las dos muestras costó menos de US$0,01) con tres preguntas
tipadas: ¿disputa concreta?, ¿tema?, ¿qué foco tiene el proyecto?. **No sirve para extraer** citas ni nombres: la extracción
sigue siendo del LLM.

1. Ensayo (sin gasto, estima el costo): `python src/scope_jev.py --eval-blind`.
2. Corrida pagada, con autorización explícita y tope: `python src/scope_jev.py --eval-blind --confirm-paid-run --max-cost-usd 0.50 --workers 50`. Para otra muestra: `--sample-dir <carpeta>`.
3. Lee `intermediate/scope/blind_eval_report.json`: de lo que pasa el filtro, cuánto es correcto; cuánto error grave se
   filtra; cuántos buenos se pierden. Los umbrales de `RULE` son hipótesis: calibrarlos con datos etiquetados antes de usar el
   filtro en el pipeline.
4. Solo si supera al criterio actual en una muestra ciega **distinta** de la usada para calibrar, integrarlo (E4). Ya está integrado:
   `python src/scope_jev.py --classify-conflicts --confirm-paid-run --max-cost-usd 0.15 --workers 50` escribe las decisiones por
   conflicto en `config/conflict_scope_decisions.json` (usa la API y el corpus; ~US$0,05 para 817 conflictos) y la etapa
   `scope_gate.py` de `rebuild.py` las aplica sin llamar a la API, creando `conflict_scope` y la vista `conflict_conservative`.
   Un conflicto nuevo o con otra agrupación queda `sin_evaluar` hasta volver a clasificar.

## Ampliar con documentos nuevos

1. Descubre y descarga los documentos nuevos; clasifícalos (paso 7) — solo los nuevos.
2. Extrae solo los pendientes: `python src/enrich.py --run-name <nueva>` ya omite URLs extraídas en cualquier corrida previa.
3. Añade sus filas a `config/document_case_unit_review.json`.
4. `python src/rebuild.py --regenerate-baseline "ampliación: <qué>"` si aparecen proyectos nuevos; resuelve la cola nueva (paso 12).
5. Mide otra vez con una muestra ciega que excluya las anteriores (paso 16).

## Qué no hacer

- No escribir cifras a mano en documentación; no llavear decisiones por nombre; no usar una heurística como filtro sin medir
  su precisión; no heredar estado de una construcción previa; no dejar nombres de versión, revisores o rutas internas en
  el repositorio; no lanzar una corrida pagada sin autorización para esa corrida.
