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
- [CERRADO] Límite anterior: cerrar la corrección de portabilidad y publicar ese cambio si la verificación local focal pasa. El trabajo de identidad (10 pares bloqueantes y el universo mayor de pares) queda como siguiente unidad, no se mezcló con este fix.

## 2026-09-28 — cierre del fix de portabilidad y continuación

- El checkpoint quedó publicado como commit `5fdc610c44419392a07edc76bb26e68221c50df8` en `codex/historical-case-references`, PR #1.
- CI remoto observado directamente: run `36495235721`, workflow `tests`, estado final `success`.
- Verificación local del mismo fingerprint: prueba focal `1 passed`; suite completa `346 passed, 5 skipped`, exit 0. No se tocó lógica del resolver, warehouse, adjudicaciones ni `main`.
- La falla reportada para `f24b377` queda cerrada: se eliminó la ruta Windows codificada del test y se validó en suite local y CI Linux. No volver a investigar esta falla salvo regresión o un run nuevo que la reproduzca.
- Medida anti-bucle: este ledger es el checkpoint de continuación. En una reanudación, leer solo su último bloque, comprobar si cambió HEAD/CI, y pasar al siguiente ítem listado; no reconstruir otra vez las causas ni los conteos ya cerrados.
- Próxima unidad: resolver conservadoramente los 10 pares PROJECT que bloquean la topología con la evidencia ya reunida; no reabrir los 68 pares ni repetir búsquedas salvo que una pareja carezca de fuente decisiva o cambie el warehouse/hash. Mantener separadas las fusiones, separaciones y relaciones padre/componente; no editar SQLite ni publicar hasta que el gate de topología quede satisfecho.

## 2026-09-28 — disposición v2 de los diez bloqueos y checkpoint anti-bucle

- Continuación desde HEAD `a13c8087d7b5cc10c9cac7e3c18deccd6ce70d66`; rama `codex/historical-case-references`. No se cambió `main` ni la SQLite.
- Resolución exacta de la lista de diez: fila 53 / `facad8bf50f968e5f69a` queda `distinct_entities` (no merge); fila 175 / `4b4059b24dd41fe0f032` queda `same_identity` en el overlay candidato (merge simulado, canónico histórico `bb5755a35f19ada504ca13a4`). Las dos mantienen `production_promoted=false`.
- Ocho quedan explícitamente abiertos, no olvidados: fila 40 Chaguay/exChaguay; 61 Edificio Santa Petronila/calle Santa Petronila; 79 Costanera Center/Cenco Costanera; 84 Alto Las Condes/Cenco Alto Las Condes; 93 Reserva La Dehesa exChaguay/Reserva La Dehesa; 126 Recreo/calle Recreo; 193 descripciones de torres 30/32; 226 proyecto Bellavista/Bellavista. Para cada uno, los predicados y la evidencia de reentrada están en `audit/project_identity_topology_dispositions_2026-09-28_v2.md`.
- Overlay versionado y pinneado: `audit/project_identity_adjudication_overrides_2026-09-28_v2.json`, SHA-256 `1dc0cedb34e95a24bcb6d756d56a5be25f913742d0e3405ca400b04f9abd00c4`. El simulador y las pruebas apuntan a v2; v1 se conserva como historial.
- Simulación reproducida por `audit/simulate_project_identity_resolution_2026_09_28.py` con warehouse `data/warehouse.sqlite` read-only, fulltext local y CLASSIFIED_63: 52 abiertos iniciales → 38 `kept_separate`, 8 `merged`, 6 todavía abiertos; 12 decisiones previamente cerradas cambiaron (8 merge→separate, 2 merge→review, 2 separate→merge). Estado agregado simulado: 117 merged, 131 separate, 8 review. Los ocho finales son los seis anteriores no resueltos más filas 61 y 79 reabiertas por evidencia histórica insuficiente. SHA reporte `efeffd7ae9eed4989dc3c502a8e194b8676bdc8e049679992a1d3494f04bfb51`; SHA warehouse fuente antes/después `685af6a951356c0c7e7249525fcb89362f8801a4c259f614571d775fb329c33c`; integridad `ok`, FK=0. Gate de publicación: bloqueado antes de escritura.
- Pruebas del resolver: tres pruebas focales pasaron; módulo completo `tests/test_resolve_project_review.py`: 50 passed. Las primeras tentativas de la suite chocaron con ACL de temporales del sandbox, no con asserts; al usar elevación autorizada y un basetemp nuevo, el módulo pasó. No repetirlo con el mismo fingerprint.
- Verificación integral del fingerprint v2: `python -m pytest -q -p no:cacheprovider --basetemp <temporal nuevo>` → **347 passed, 5 skipped**, exit 0, 20.24 s. La CI de este fingerprint todavía no existe: se comprobará una sola vez tras el push.
- Decisión/anti-bucle registrada en la bitácora FARO como `turn-20260928-235123-8add23` (rol `builder`, modelo `gpt-5.6-luna`).
- El resultado de referencia publicado en el checkpoint anterior (10 bloqueos y conteos v1) queda superado por el reporte v2. No borrar ni reescribir su historia.
- Regla anti-bucle vigente: este ledger más el dossier v2 son la única continuidad operativa de este bloque. Al retomar, comprobar HEAD, hashes del overlay/warehouse y CI; si no cambiaron, ir al paso siguiente escrito. No recalcular los 52 casos, no volver a buscar genéricamente nombres ya investigados, no repetir pruebas con el mismo fingerprint. Una nueva búsqueda solo se abre para satisfacer un predicado de reentrada de una fila concreta.
- Siguiente paso único: revisar el diff final, commit/push de este checkpoint y observar una vez el CI nuevo. No reconstruir warehouse, promover decisiones ni fusionar el PR. Tras CI verde, registrar el SHA/run en FARO y terminar: no hacer un commit adicional solo para anotar el resultado de CI. Reabrir únicamente si cambia el fingerprint/CI o llega evidencia que cumpla un criterio de reentrada de los ocho casos.


## 2026-09-29 — cierre de los 8 pares y reconstrucción integral (Claude, a pedido de Felipe)

- Continuación desde HEAD `bca445da11e18c9b35fd56c330de5af24a4aaecb`. Felipe pidió cerrar los 8 pares abiertos y dejar todo listo. Trabajo hecho en el checkout principal sobre la rama local `close-identity-8`, publicada en `codex/historical-case-references`.
- Los 8 pares se decidieron con evidencia de fuente; detalle y criterio de cada uno en `audit/project_identity_closure_2026-09-29.md`. Overlay v3 pinneado, SHA-256 `82f8b1d409562033a244fe266be0f75bd42b2c153cd3251d08cd5507d5fc3626`. Reemplaza al v2 (que se conserva).
- El cierre exigió revertir dos fusiones legacy por nombre que las fuentes contradicen (Reserva La Dehesa / ex Chaguay; proyecto Bellavista / edificio DIB).
- Se corrigió un defecto de portabilidad: con `core.autocrlf=true` el checkout de Windows alteraba los bytes de los artefactos con hash fijado; `.gitattributes` ahora fuerza LF.
- Reconstrucción integral completa (build_projects → resolve → detect_case_mention_duplicates → build_conflicts → actor registry/network → geography → dashboard → manifest). Cola: 118 merged, 138 kept_separate, 0 abiertos. Warehouse `ef776d1f9294021751d1b74f602523eaabe6d02e18f7d6b4b68c61bfa6d1436d`, integrity ok, 0 FK.
- Este cierre supera el reporte de simulación v2 y el dossier de diez bloqueos; no se borran.
- Regla anti-bucle: no reabrir estos 8 sin evidencia nueva del tipo indicado en el rationale de cada uno.
