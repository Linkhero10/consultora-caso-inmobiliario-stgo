# Base de datos: red de actores sobre conflictividad inmobiliaria en Santiago

**Fecha:** 18 de septiembre de 2026
**Preparado por:** Felipe
**Archivo de datos:** `warehouse_v3_2_bridge.sqlite` (~79 MB, adjunto por separado)

## Resumen

Esta base de datos SQLite contiene el corpus de 934 documentos sobre conflictos inmobiliarios y
urbanos en Santiago, procesado hasta tres niveles de identidad: proyecto, conflicto y (parcialmente)
actor institucional. Cada nivel cuenta con trazabilidad de las decisiones de fusión y separación tomadas
sobre los datos, y distingue explícitamente entre información revisada manualmente y derivaciones
automáticas.

Esta entrega corresponde a infraestructura de datos, no a un análisis. El objetivo es dejar la base
lista para el análisis de red propiamente dicho: roles actorales, brokerage, comunidades, temporalidad
y territorios.

## Punto de partida: la vista para construir la red actor–conflicto

```text
actor_event_project_link_conflict_safe      2.223 filas · 130 documentos · 96 conflictos
actor_event_project_link_conflict_extended  2.358 filas · 134 documentos · 130 conflictos
```

Esta vista ya contiene el vínculo `actor → proyecto → conflicto` con el filtro conservador aplicado, y
es la que se utilizó para construir la red de referencia descrita más abajo.

Campos principales:

| Campo | Descripción |
|---|---|
| `nombre` | Nombre del actor tal como aparece en el texto |
| `source_table` / `source_id` | Origen de la extracción |
| `document_id` | Documento de origen |
| `project_id` | Proyecto asociado |
| `conflict_id` | Conflicto asociado |
| `resolution_status` | Ya filtrado a `resolved_explicit` en ambas vistas |

Para obtener identidad institucional resuelta (ver más abajo):

```text
nombre normalizado (minúsculas, espacios colapsados)
    → actor_alias.nombre_norm
    → actor_registry.entity_id / canonical_label
```

## Otras tablas y vistas relevantes

### `document_conflict_case_safe` (557 filas)

Capa documental de validación: identifica qué documentos tratan cada conflicto como protagonista
(`role IN ('focal', 'co_focal')`), restringida a documentos clasificados como caso único. Es la vista
adecuada para verificar o citar la evidencia de un conflicto puntual; la construcción de la red en sí se
apoya en `actor_event_project_link_conflict_safe`.

Existe también `document_conflict_case_extended` (599 filas), que incorpora menciones contextuales
revisadas manualmente, útil para análisis de sensibilidad.

La tabla `document_conflict` sin filtrar (1.268 filas) no debe usarse directamente: combina evidencia
revisada con menciones mecánicas sin revisar y con documentos panorámicos.

### `conflict`, `conflict_project`, `conflict_case` (839 conflictos)

Unidad de análisis principal. Un conflicto puede involucrar uno o más proyectos (20 de los 839 casos
son multi-proyecto, con evidencia revisada manualmente de que corresponden al mismo conflicto — por
ejemplo, el litigio entre un cementerio y el trazado de un teleférico sobre su terreno). Los 819
restantes son unidades de un solo proyecto derivadas automáticamente a partir de la identidad de
proyecto ya depurada; no han sido validadas individualmente, por lo que deben entenderse como un piso
razonable y no como una afirmación de que existen exactamente 839 conflictos.

### `actor_registry`, `actor_alias` (6 entidades, 29 alias)

Resolución de identidad para instituciones nacionales que aparecían fragmentadas en el texto — por
ejemplo, "Contraloría" y "Contraloría General de la República" contabilizadas como actores distintos.

Quedan deliberadamente sin resolver en esta versión:

- Cortes de Apelaciones y Tribunales Ambientales sin sede identificada (Chile cuenta con 17 y 3
  respectivamente; una fusión sin verificación caso a caso introduciría certeza inexistente).
- Direcciones de Obras Municipales sin comuna identificada (cada una de las 32 comunas de la Provincia
  de Santiago cubierta por el corpus tiene su propia DOM; no corresponden a una institución única).
- SEREMI regionales.
- Personas naturales.

La resolución de cualquiera de estas categorías requiere trabajo dirigido a casos específicos, no una
regla general aplicable de una vez.

## Resultado de referencia

Al resolver la identidad de las seis instituciones sobre `actor_event_project_link_conflict_safe`:

| Actor (identidad resuelta) | Conflictos únicos |
|---|---:|
| Corte Suprema | 17 |
| Contraloría General de la República | 17 |
| Corte de Apelaciones de Santiago | 16 |
| Ministerio de Vivienda y Urbanismo (MINVU) | 14 |
| Servicio de Evaluación Ambiental (SEA) | 12 |
| Concejo Municipal | 10 |
| Consejo de Monumentos Nacionales (CMN) | 8 |
| Consejo de Defensa del Estado (CDE) | 6 |
| Superintendencia del Medio Ambiente (SMA) | 6 |

Antes de resolver identidad, la Contraloría aparecía dividida en dos nodos (10 y 7), sin acercarse a
Corte Suprema. La fragmentación textual subestimaba su multiafiliación observada en la red. Cabe
precisar que esta medida corresponde a grado bipartito — número de conflictos únicos en que interviene
el actor — y no a una medida de centralidad universal ni de brokerage.

## Estructura de las tablas

```text
document (3.884, corpus completo)
  └─ enrichment_document_v3_2 (934, documentos enriquecidos)
       └─ document_unidad_caso_sol (clasificación: caso único / panorámico / fuera de universo / etc.)

project (990, identidad de proyecto)
  └─ project.case_id (862, identidad de caso — fusiones de homónimos y variantes de escritura)
       └─ project_phase / project_phase_link (relación matriz–fase, p. ej. "Urbanya" y "Urbanya Etapa I")

conflict (839, identidad de conflicto — puede agrupar 2+ case_id cuando corresponde al mismo litigio)
  ├─ conflict_case, conflict_project (proyectos/casos que componen cada conflicto)
  ├─ document_conflict (documentos que discuten cada conflicto, con rol y fuente)
  └─ conflict_relation (conflictos relacionados pero no fusionados — ver caso abierto más abajo)

actor_registry / actor_alias (6 entidades institucionales resueltas)
```

## Caso abierto: Población La Victoria y Rancagua Express

Un mismo territorio y actor colectivo (Población La Victoria) sostiene una toma de terreno fundacional
de 1957 y, décadas después, una protesta contra el proyecto ferroviario Rancagua Express. No se ha
determinado si corresponde a un conflicto con episodios sucesivos o a dos conflictos distintos
conectados únicamente por territorio y memoria colectiva; queda registrado en `conflict_relation` con
estado `pending_human_decision`.

Se trata de una pregunta que un análisis de trayectorias y temporalidad puede resolver mejor que una
decisión tomada sobre la sola estructura de los datos. La tabla `conflict_episode` está creada pero
vacía, a la espera de que se modele este tipo de trayectorias longitudinales con fechas verificadas.

## Alcance de esta entrega

El trabajo descrito hasta aquí responde a la pregunta de si el dato representa correctamente la
realidad: identidad de proyecto, identidad de conflicto e identidad de actor institucional. Esa parte
está verificada y cerrada.

A partir de aquí, las preguntas son de análisis, no de construcción de datos:

- Roles actorales (instituciones reguladoras, empresas, organizaciones sociales).
- Brokerage y actores puente entre conflictos.
- Comunidades y clusters dentro de la red.
- Comparación entre la vista conservadora (`actor_event_project_link_conflict_safe`) y la extendida
  (`actor_event_project_link_conflict_extended`) como análisis de sensibilidad.
- Temporalidad y territorio, para lo cual `conflict_episode` está disponible si resulta necesario
  poblarla.

Si el análisis identifica un actor relevante que aún aparece fragmentado en variantes de texto —como
ocurría antes con la Contraloría—, se puede resolver puntualmente con evidencia verificada; es
preferible a intentar automatizar la resolución para todo el corpus de una vez.
