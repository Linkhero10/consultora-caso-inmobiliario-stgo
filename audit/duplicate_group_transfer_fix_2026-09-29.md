# Corrección de transferencias por grupo de duplicados

Fecha de trabajo: 2026-09-29 (America/Santiago). La reconstrucción fue generada el 2026-09-30 UTC.

## Decisión

La pertenencia a `case_mention_duplicate_link` es una señal heurística de posible duplicidad, no una relación verificada entre `project_mention` y una `case_mention` concreta. Por tanto, no autoriza transferir evidencia de objeto ni comuna entre miembros del grupo.

- El respaldo de conflicto requiere el `case_mention_id` apuntado por el índice v3.3 de esa mención de proyecto, elegibilidad aplicable y evidencia de objeto verificada en esa misma mención. Se eliminó el respaldo por una mención hermana, tanto en grupos con decisiones mixtas como en grupos sin decisiones mixtas.
- La geografía acepta la comuna de la mención enlazada directamente si su propia `case_mention` es `include` y tiene comuna resuelta. Si la mención pertenece a un grupo, pero no resuelve directamente su geografía, queda `ambiguous_duplicate_group` y sin comuna, salvo una adjudicación específica `reviewed_geography_only`.
- Esa excepción manual continúa limitada a geografía: no cambia `include/exclude`, focalidad, conflicto ni evidencia. El enlace revisado existente se conservó y volvió a aplicarse.
- El dashboard solo cuenta `direct` y `via_reviewed_duplicate_group`. La tabla geográfica ya no permite por `CHECK` el método retirado `via_duplicate_group`.

## Efecto comprobado

Base de partida: commit `f0cea223352885705b0e05387fdf9fd7e4affc70`; SHA-256 del warehouse `9c4d2da86daebf19b1b84aa6007687fc503aecd61cd54ce45eb5e20a5abd4179`.

| Indicador | Antes | Después |
|---|---:|---:|
| Conflictos totales | 817 | 817 |
| Conflictos con algún respaldo | 506 | 506 |
| Conflictos sin respaldo exacto | 311 | 311 |
| Filas `conflict_evidence_backing` | 1.782 | 1.769 |
| Filas de respaldo por grupo de duplicados | 13 | 0 |
| Menciones geográficas `direct` | 760 | 760 |
| Transferencias geográficas automáticas por grupo | 7 | 0 |
| Transferencia geográfica manual revisada | 1 | 1 |
| Menciones geográficas ambiguas de grupos | 6 | 18 |
| Sin índice / sin inclusión / sin comuna | 201 / 257 / 40 | 201 / 252 / 40 |

Las 13 filas retiradas de respaldo eran 9 `v3_3_verified_index_via_duplicate_group` y 4 `...via_duplicate_group_mixed_decision`, distribuidas en 5 proyectos y 5 conflictos. Esos cinco conflictos siguen respaldados por otras filas; por eso el total 506 no cambia. La eliminación significa que ya no se atribuye esa cita al proyecto mediante el grupo; no declara falso el conflicto ni impide adjudicarlo con evidencia directa en el futuro.

El aumento de 6 a 18 filas geográficas ambiguas se compone exactamente de 7 antiguas `via_duplicate_group` y 5 que antes figuraban como `case_mention_no_incluido` aunque pertenecían a un grupo. Ambas transiciones ahora quedan explícitamente sin comuna hasta tener adjudicación específica.

## Reconstrucción y verificación

- Código probado y guardado en los commits `792ed9a0beb9602128f749b578e533b71df1470e` y `6232901f4322a84554b6f1315c2bbefe5b9cd32e`; este último fija LF para que los hashes de los generadores sean idénticos en Windows y Linux.
- Cadena reconstruida en el worktree aislado: `build_conflicts` → registro/red de actores → geografía → contexto censal → dashboard → manifiesto.
- Warehouse candidato SHA-256: `b477bd81ffc5bf4a097289ee0134cf58d7c0877b8d8db000dcd95b22c6970f7f`.
- `PRAGMA integrity_check = ok`; `foreign_key_check = 0`.
- Comprobaciones directas: 0 filas de respaldo con método de grupo; 0 citas que apunten a evidencia no verificada o a otro `case_mention`; 0 transferencias geográficas automáticas; 0 comunas en filas ambiguas; 0 discrepancias en las 760 asignaciones directas.
- Suite completa: 361 passed, 7 skipped; suites focalizadas de conflictos/geografía/dashboard: 103 passed, 1 skipped.
- El dashboard fue regenerado y su nota metodológica ya describe la regla nueva.

## Alcance y estado de publicación

No se alteraron clasificaciones upstream ni se adjudicaron grupos nuevos. Este arreglo cierra la ruta automática de transferencia; las 18 filas ambiguas siguen necesitando evidencia/adjudicación individual si se quiere recuperar geografía. Los casos de pertenencia a grupos no fueron re-auditados semánticamente uno por uno.

El trabajo está aislado en la rama `fix/case-mention-fallback`. `main` y su warehouse publicado no se modificaron. Esta rama aún requiere push/PR y revisión antes de cualquier merge o publicación.
