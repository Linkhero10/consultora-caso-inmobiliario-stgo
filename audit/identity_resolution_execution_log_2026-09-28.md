# Bitácora de ejecución — resolución de identidad PROJECT

## 2026-09-28 — checkpoint inicial de continuación

- Rama de trabajo: `codex/historical-case-references`.
- HEAD observado al iniciar: `f24b377` (`Checkpoint project identity reconciliation`).
- Límite: no editar `main`, no reconstruir ni escribir el warehouse publicado, no fusionar el PR.
- Estado: el reporte de simulación guardado puede estar desactualizado respecto del código/overrides; volver a generarlo solo después de fijar adjudicaciones.
- Hallazgo recibido de la revisión externa: CI de `f24b377` habría fallado por una prueba de rutas Windows en Linux (`345 passed, 1 failed, 5 skipped`). **Pendiente de verificación directa**, no aceptar aún el diagnóstico ni los conteos.
- Medida de continuidad acordada: este archivo registra decisiones y el siguiente paso al momento; actualizar después de cada bloque, junto con el checkpoint FARO cuando corresponda.
- Siguiente paso único: comprobar el estado remoto del PR/CI y reproducir exactamente el fallo antes de tocar lógica de identidad.
- Decisiones metodológicas vigentes: coincidencia de nombres no basta; no propagar alias transitivamente; mantener refs históricos irresueltos sin inventar identidad; publicar solo tras resolver toda ambigüedad que afecte topología.

## 2026-09-28 — portabilidad del test (diagnóstico y corrección local)

- `gh run list` y `gh pr view` no pudieron consultar GitHub: el proxy local rechazó la conexión. El CI reportado por Claude/Sol queda **sin verificación remota independiente** en este entorno.
- Reproducción conceptual: `Path("C:/checkout")` es absoluta en Windows, pero es una ruta relativa bajo `pathlib` POSIX; la prueba fijaba rutas Windows y por eso no era portable. El código productivo no cambia.
- [SUPERADO] Corrección intermedia: la prueba usó `tmp_path` y comparó rutas resueltas; ese enfoque se reemplazó abajo porque este sandbox bloqueó el acceso temporal de pytest.
- Verificación pendiente en este punto: correr prueba focal y suite; la CI remota solo podrá confirmarse si vuelve la conectividad de GitHub.
- No se tocó warehouse, resolver, adjudicaciones ni branch `main`.

## 2026-09-28 — bloqueo de verificación local y regla anti-repetición

- La primera corrida focal de pytest no llegó a ejecutar la prueba: falló creando la carpeta temporal del host (`PermissionError: [WinError 5]`) y tampoco podía escribir `.pytest_cache` en este worktree. Esto es **bloqueo del entorno**, no PASS ni FAIL del test.
- Segundo intento en otra carpeta temporal del host también fue denegado antes de ejecutar el test. Tercer intento en la raíz de visualizaciones sí creó el directorio, pero pytest terminó con `PermissionError` al enumerarlo durante `sessionfinish`; no es evidencia de un fallo de la función. Se evitó ese acoplamiento: la prueba ahora usa rutas relativas y comprueba `resolve()` sin fixture/IO, suficiente para esta función pura.
- [CERRADO] La primera ejecución focal sin plugins temporales corrió el test y falló en la expectativa del nuevo test: el resolver devuelve paths absolutos también para defaults. Se corrigió la expectativa a `repo.resolve()` y la siguiente ejecución pasó.
- Resultado focal actual: `py -m pytest -q tests/test_historical_project_pair_builder.py -p no:cacheprovider -p no:tmpdir` → `1 passed` en 0.04 s. El cambio toca solo el test, no lógica productiva ni warehouse. El run remoto de CI sigue pendiente de una nueva ejecución en el PR; no se declara CI corregido todavía.
- Regla operacional para evitar repetición tras compactación: antes de retomar, leer este ledger y comprobar únicamente si cambió el HEAD/diff o llegó un CI nuevo; si no cambió, continuar desde el próximo paso escrito, no reabrir el diagnóstico.
- Suite completa ejecutada con permiso autorizado y temporales aislados: `py -m pytest -q --basetemp <raíz-escribible> -p no:cacheprovider` → **346 passed, 5 skipped**, exit 0. No hubo cambios a resolver, datos ni warehouse.
- Siguiente paso de este checkpoint: revisar diff/estado, commit y push de este arreglo; después observar el CI del PR. No continuar la adjudicación de pares dentro de este mismo fix. Si CI remoto no puede consultarse, dejarlo como no verificado y conservar el comando/run esperado, sin repetir la suite local sobre el mismo fingerprint.
- Estado exacto de la corrección: `tests/test_historical_project_pair_builder.py` usa paths relativos y compara defaults/argumentos explícitos ya resueltos; prueba focal y suite local pasan. No afirmar que el CI remoto está arreglado hasta observar un run verde.
- Regla anti-bucle desde esta fecha: este log es el ledger operativo único para esta tarea. Cada checkpoint registra HEAD, pregunta cerrada, evidencia y solo el siguiente paso; no se vuelve a auditar ni recalcular un bloque cerrado salvo que cambie su hash/entrada o aparezca evidencia contradictoria. No repetir diagnósticos ya anotados ni reabrir el inventario completo al compactar.
- Límite de la unidad actual: cerrar la corrección de portabilidad y publicar ese cambio si la verificación local focal pasa. El trabajo de identidad (10 pares bloqueantes y el universo mayor de pares) permanece separado y no se mezcla con este fix.

