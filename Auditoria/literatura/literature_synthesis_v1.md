# Literatura y marco analítico — conflicto inmobiliario/urbano en Santiago

## Estado de la evidencia

Esta primera colección contiene tres artículos de acceso abierto descargados,
conservados en PDF y extraídos a Markdown. Un cuarto enlace del Repositorio de
la Universidad de Chile devolvió una página de protección anti-bot, por lo que
no se contabiliza como paper descargado. El detalle técnico está en
`literature_ingestion_manifest_v1.json` y
`literature_ingestion_exceptions_v1.json`.

## Fuentes incorporadas

| ID | Fuente | Caso/unidad | Aporte al proyecto | Límite |
|---|---|---|---|---|
| LIT-001 | López, Meza y Gasic (2014), *Neoliberalismo, regulación ad-hoc de suelo y gentrificación: el historial de la renovación urbana del sector Santa Isabel, Santiago* | Sector Santa Isabel, comuna de Santiago; renovación urbana y captura de renta | Propone observar constructibilidad, actores inmobiliarios, propietarios residentes y desplazamiento exclusionario como proceso socioespacial | Caso histórico localizado; no debe generalizarse mecánicamente a las 32 comunas |
| LIT-002 | Valencia Palacios (2019), *¿Gentrificación en zonas patrimoniales? Estudio de cinco casos en Santiago de Chile* | Cinco zonas patrimoniales pericentrales | Permite separar patrimonialización, valorización, deterioro, conflicto y desplazamiento; útil para el arco institucional/patrimonial | La declaratoria patrimonial no prueba por sí sola gentrificación ni causalidad |
| LIT-003 | *La nostalgia en la producción urbana: la defensa de barrios en Santiago* (2017) | Defensa vecinal de barrios y transformaciones urbanas | Aporta una dimensión narrativa y afectiva: memoria barrial, pérdida, identidad y oposición a cambios urbanos | Es evidencia cualitativa situada, no encuesta representativa |
| LIT-004 | Plaza Pública/Cadem, Estudio N°235 (2018) | Encuesta nacional, 704 casos | Permite contrastar aceptación/rechazo de edificios en altura, vivienda social y equipamientos cerca del barrio | Es una medición nacional de 2018; no equivale a opinión específica de las 32 comunas ni a la situación actual |
| LIT-005 | COES, *Radiografía de la Cohesión Social en Chile 2016-2023* (2024) | Panel urbano ELSOC | Proporciona contexto longitudinal sobre conflicto, confianza, convivencia y cohesión social | No es un registro de conflictos inmobiliarios ni identifica automáticamente proyectos |
| LIT-006 | COES, *Comparación metodológica internacional ELSOC* (2022) | Diseño de encuesta/panel | Documenta posibilidades y límites de comparar ELSOC con otros paneles | Es documentación metodológica, no resultados sustantivos sobre Santiago |

## Hipótesis operativas que la literatura permite medir

1. **Regulación como condición de conflicto:** los conflictos no se reducen a
   “vecinos versus inmobiliarias”; debe observarse qué instrumento, permiso,
   ordenanza o decisión institucional habilita o restringe el proyecto.
2. **Densificación y distribución desigual:** la cantidad de unidades, altura,
   constructibilidad y localización deben cruzarse con población residente,
   hacinamiento, tenencia y accesibilidad, sin afirmar causalidad con datos
   transversales.
3. **Desplazamiento exclusionario como mecanismo, no como etiqueta:** la
   literatura propone examinar capacidad de reemplazo, precios y acceso a
   bienes urbanos; una noticia sobre oposición no demuestra desplazamiento.
4. **Patrimonio como campo de disputa:** la declaratoria puede producir
   valorización, restricciones, deterioro o defensa barrial; el resultado debe
   verificarse con normas, expedientes y testimonios.
5. **Narrativas vecinales:** memoria, identidad, seguridad, sombra, ruido,
   congestión y pérdida de barrio son variables analíticas, pero no deben
   convertirse en indicadores cuantitativos sin codificación explícita.

6. **Opinión y conflicto no son equivalentes:** la encuesta Cadem/Plaza
   Pública de 2018 muestra que la aceptación depende del tipo de proyecto y
   equipamiento; el rechazo a edificios en altura no puede extrapolarse a una
   oposición general a la vivienda social o a toda densificación.
7. **Cohesión como contexto:** ELSOC permite estudiar confianza, arraigo,
   percepción de conflicto y desigualdad territorial como condiciones sociales
   alrededor de los casos, pero no debe utilizarse para adjudicar causalidad a
   una noticia individual.

## Variables que conviene conectar con el pipeline

- `instrumento_regulador` y `institucion_decisora`;
- `etapa_proyecto`, `altura`, `unidades`, `constructibilidad` cuando aparecen
  en una fuente literal;
- `tipo_conflicto` y `tipo_accion`;
- `argumento_vecinal` (categoría controlada, no sentimiento automático);
- `patrimonio_declarado`, `zona_tipica`, `inmueble_afectado`;
- `indicio_desplazamiento` con valores `mencionado`, `evidenciado`,
  `no_determinable`, nunca inferido solo por densidad;
- `fuente_primaria_secundaria` y `nivel_de_evidencia`.

## Próxima revisión

La síntesis no autoriza todavía una teoría causal ni una medición de
gentrificación para toda la provincia. Antes de usarla en productos públicos
se debe ampliar el corpus con documentos oficiales, permisos/recepciones,
instrumentos de planificación y evidencia territorial comparable.
