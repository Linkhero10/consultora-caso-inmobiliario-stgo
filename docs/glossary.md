# Glosario: términos de proceso que aparecen en comentarios y bitácora

Un lector nuevo va a encontrar nombres propios (**Sol**, **Luna**) en comentarios de código,
docstrings y en `Auditoria/`. Esta página explica qué son antes de que se lean como ruido o como
si la lógica "perteneciera a las IAs" en vez de al diseño del sistema.

## Qué son

**Sol** y **Luna** son colaboradores del proceso de revisión adversarial del proyecto —
verificación independiente de decisiones de diseño y de datos, no autoría del sistema. Su función
en el flujo de trabajo es la misma que cumpliría un revisor de código o un segundo par de ojos en
cualquier equipo de ingeniería: encontrar bugs reales, cuestionar supuestos metodológicos y exigir
verificación contra los datos reales antes de aceptar cualquier afirmación — incluidas las propias.

## Por qué aparecen tan seguido en el código

Cada vez que una revisión encontraba un problema real (no una alarma falsa), la corrección se
documentó en el propio comentario del código con la fecha y el hallazgo, en vez de solo corregir
en silencio. Es una decisión deliberada de trazabilidad: cualquiera puede reconstruir por qué el
código quedó como quedó, y qué bug concreto se estaba evitando al escribirlo así.

Ejemplo real (`Trabajo/scripts/build_conflict_registry_v1.py`):

```python
# [CORREGIDO 2026-09-18, hallazgo real de revisión] role tenía 2 fallas: ...
```

Este estilo de comentario seguirá apareciendo en el código de análisis/auditoría
(`Auditoria/`, `Trabajo/tests/`), donde es exactamente el registro de proceso que se busca
preservar. En los scripts de producción más visibles (`Trabajo/scripts/`), la migración hacia un
formato más neutro (referencia a un hallazgo por fecha, sin nombre propio) es un trabajo gradual en
curso — ver [`docs/versions.md`](versions.md) para el estado de cada componente versionado.

## La distinción que importa

El **diseño** (separar `PROJECT` de `CONFLICT`, las vistas `safe`/`extended`, la resolución de
identidad de actor) es una decisión metodológica tomada considerando el objeto de estudio
sociológico. La **revisión adversarial** es lo que forzó a que cada pieza de ese diseño esté
verificada contra los datos reales antes de darla por cerrada — son roles distintos, y el segundo
no reemplaza al primero.
