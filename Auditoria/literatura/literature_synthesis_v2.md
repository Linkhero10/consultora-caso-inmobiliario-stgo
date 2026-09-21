# Síntesis FARO v2: fenómeno inmobiliario/urbano en Santiago

**Estado:** base de trabajo; no equivale a una revisión sistemática ni autoriza inferencias causales. Las afirmaciones deben volver al PDF y página.

## Ejes integrados

| Eje | Evidencia capturada | Uso analítico | Límite |
|---|---|---|---|
| Densificación y altura | Herrmann–van Klaveren (2013); Vergara–Asenjo (2019); MINVU/MPRMS | Codificar tipología, escala, norma, sombra, espacio público y controversia | Casos/argumentos; no padrón completo de permisos |
| Gentrificación y desplazamiento | López-Meza–Gasic (2014); Valencia (2019); Censo/CASEN/EPV | Conectar regulación, inversión, precios, composición y movilidad | No inferir desplazamiento desde una sola tendencia |
| Patrimonio y acción colectiva | Colin (2017); Casanova (2021); Valencia (2021) | Secuencia amenaza → organización → repertorio → decisión → resultado | Evidencia cualitativa; no prevalencia de opinión |
| Vivienda e integración | DS19 y evaluación UC/CChC (2023) | Separar diseño del subsidio, implementación, convivencia y resultados | Cobertura y licencia deben revisarse por fuente |
| Opinión y cohesión | Cadem (2018); COES ELSOC; MINVU (2026) | Contexto de confianza, seguridad, satisfacción, apoyo y legitimidad | No identifica por sí solo un conflicto/proyecto |
| Base territorial | Censo 2024, CASEN 2024, ARClim, GTFS, MINVU permisos | Denominadores, contexto socioespacial, calor, accesibilidad y actividad autorizada | Unidades/periodos no son intercambiables |

## Hipótesis de trabajo, no resultados

1. La controversia aumenta cuando la densificación visible se combina con una brecha entre norma/instrumento y formas de vida barriales.
2. La patrimonialización puede producir protección y revalorización simultáneas; ninguna de las dos implica automáticamente desplazamiento.
3. Los conflictos deben modelarse como trayectorias de eventos y decisiones, no como conteo de noticias.
4. La legitimidad de proyectos depende de resultados distributivos, seguridad, acceso a servicios, confianza y repertorios organizativos, además de la oposición declarada.
5. Los permisos MINVU son una exposición/actividad potencial; no deben convertirse directamente en “conflictos” sin evidencia documental del caso.

## Próximo piloto analítico

Para diez casos: Matta Sur, Yungay, Santa Isabel, Villa Olímpica, Villa Frei, Empart Salvador, un caso DS19 y tres casos de densificación reciente. Cada caso debe tener: `source_id`, fecha/página, comuna/CUT, proyecto/instrumento, actores, acción, decisión, resultado, unidad y nivel de evidencia. El join territorial preferido es CUT/ComCod; el nombre es solo respaldo humano.

## Gates antes de publicar

- Revisar visualmente los 5 documentos marcados por FARO (`needs_review`/advertencias PDF).
- Definir estimando y ponderadores antes de abrir CASEN nacional; conservar microdatos aislados.
- Verificar que permisos, Censo, ARClim y prensa no compartan falsamente la misma unidad temporal.
- No usar redes sociales como prevalencia; solo como evidencia contextual de baja representatividad y con minimización de datos.
- Mantener la clasificación de prensa como provisional hasta snapshot v3 y reconciliación de lineage.
