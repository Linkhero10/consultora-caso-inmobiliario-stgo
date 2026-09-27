# Auditoría Sol — migración v3.2 → v3.3

## Cobertura
- 30/30 reconexiones revisadas.
- 68/68 pares abiertos revisados.
- 89/89 documentos focales priorizados.
- 30/30 documentos no focales congelados.
- Cambios de producción aplicados: **no**.

## Hallazgos prioritarios
1. **Ciudad Parque Bicentenario / Plan Maestro de Ciudad Parque Bicentenario:** la decisión histórica `kept_separate` **no es transferible**. La relación recomendada es `alias`, confianza alta.
2. **Data Center de Google / data center de Google Chile en Cerrillos:** la separación es sustantivamente plausible porque Quilicura y Cerrillos son proyectos distintos, pero debe verificarse que el ID genérico A corresponda efectivamente a Quilicura. `si_con_reserva`, confianza media.

## Resumen reconexiones
{"si": 14, "no": 13, "si_con_reserva": 1, "incierto": 2}

## Drift
539 adjudicaciones de nombres en 119 documentos.
{
  "equivalente": 306,
  "no verificable": 106,
  "omisión respaldada": 69,
  "irrelevante": 46,
  "proyecto/granularidad distinta": 4,
  "no respaldado": 8
}

## Limitación
El paquete no contiene los fulltext locales. Cuando una URL no fue accesible o la literalidad no demostraba atribución, la decisión se dejó como `no verificable`, en vez de completar por inferencia.
