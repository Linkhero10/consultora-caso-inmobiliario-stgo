# Informe para Sol: variabilidad no explicada en la segunda pasada actor-only

**Fecha:** 2026-09-17
**Autor:** Claude (sesión `caso_inmobiliario_stgo`)
**Para:** Sol — pedir segunda opinión sobre posibles soluciones de diseño

---

## ACTUALIZACIÓN 2026-09-17 (noche) — tras la respuesta de Sol, con datos nuevos que cambian la conclusión

Sol respondió a este informe con una hipótesis muy razonable (enrutamiento de
OpenRouter a distintos proveedores backend) y recomendó, antes que nada,
fijar el proveedor y repetir la llamada varias veces controlando esa
variable. Se hizo exactamente eso, con resultados que **descartan el
enrutamiento como causa y revisan al alza la tasa real de "respuesta
superficial"**. El resto de este documento (§1-9 más abajo) es el informe
ORIGINAL, sin editar, tal como Sol lo vio. Esta sección es la continuación.

### Lo que se hizo

1. Se verificó que la respuesta de OpenRouter SÍ expone el proveedor real
   (`data["provider"]`, ej. `"OpenAI"`) — campo que nunca se había estado
   capturando en ningún script de esta pipeline.
2. Se repitió la llamada baseline (idéntica a la Variante A: mismo prompt,
   mismo schema, `effort=xhigh`, `max_tokens=28000`) **4 veces seguidas
   sobre `radio.uchile.cl`**, sin fijar proveedor, registrando el proveedor
   real de cada respuesta.
3. Se repitió el mismo experimento **4 veces seguidas sobre
   `lavozdelosquesobran.cl`** (el documento que hasta ese momento tenía 0/4
   respuestas profundas en todos los intentos previos).

### Resultado

**`radio.uchile.cl` (4 llamadas nuevas):**

| Intento | Proveedor | reasoning_tokens | actores encontrados | costo |
|---|---|---|---|---|
| 1 | OpenAI | 12.430 | 12 | $0.01629 |
| 2 | OpenAI | 15.538 | 12 | $0.01971 |
| 3 | OpenAI | 8.804 | 12 | $0.01166 |
| 4 | OpenAI | 10.169 | 12 | $0.01318 |

**`lavozdelosquesobran.cl` (4 llamadas nuevas):**

| Intento | Proveedor | reasoning_tokens | actores encontrados | costo |
|---|---|---|---|---|
| 1 | OpenAI | 8.804 | 10 | $0.01190 |
| 2 | OpenAI | 9.736 | 10 | $0.01256 |
| 3 | OpenAI | 5.178 | 10 | $0.00707 |
| 4 | OpenAI | 12.332 | 10 | $0.01566 |

**Las 8 llamadas nuevas vinieron del mismo proveedor ("OpenAI") y las 8
fueron "profundas" (5.178-15.538 `reasoning_tokens`), cada una encontrando
actores reales.**

### Recuento total acumulado por documento (todas las rondas del informe + estas 8 llamadas)

| Documento | Intentos superficiales | Intentos profundos | Total |
|---|---|---|---|
| `radio.uchile.cl` | 4 | 5 (incluye 1 truncado por tope de tokens) | 9 |
| `lavozdelosquesobran.cl` | 4 | 4 | 8 |

**Conclusión revisada: la tasa real de respuesta superficial es de
aproximadamente 50% por llamada, no ~80-100% como sugería la muestra inicial
(2-4 intentos por documento, insuficiente para estimar la proporción real).
No es una propiedad fija de estos 2 documentos -- es varianza estocástica
real del modelo/proveedor para una tarea que acepta una lista vacía como
respuesta válida.** El enrutamiento a distinto proveedor queda descartado
como explicación: las 8 llamadas profundas confirman "OpenAI", igual que la
llamada de control mínima hecha para verificar que el campo existiera.
(Limitación: no se pudo confirmar retroactivamente el proveedor de las
llamadas superficiales anteriores a este cambio, porque no se capturaba ese
campo -- ya corregido para corridas futuras.)

### Cambio de diseño aplicado

Con p≈0.5 por intento, la matemática de "cuántas confirmaciones hacen falta"
cambia radicalmente respecto a la estimación original de Sol (que asumía
p≈0.2 y calculaba ~14 confirmaciones necesarias):

```
p(fallo) = 0.5
N=2 → 25% de falso vacío (justo lo que paso en la Ronda 4 del informe)
N=5 → ~3%
```

Se subió `N_CONFIRM_EMPTY` de 2 a 5 en `actor_second_pass_v1.py`. El costo
esperado por documento sigue dominado por el ÚNICO intento profundo que
hace falta (~$0.01-0.02), ya que los intentos superficiales cuestan
centavos (~$0.0002 cada uno) -- el retry no es la parte cara.

### Restricción real de presupuesto

Costo total gastado en toda esta investigación (todas las rondas, todos los
diagnósticos): **$0.194** de los $1.87 originales. Quedan aproximadamente
**$1.68**.

Con el diseño de N=5 confirmaciones, escalar a los 266 documentos completos
costaría aproximadamente **$4-5 USD** (266 × ~$0.015-0.02/doc promedio) --
**por encima del presupuesto restante**. No se ha escalado. Las opciones
pendientes de decisión: (a) recargar saldo en la API antes de correr los 266,
o (b) hacer primero el canario de 20-30 documentos que Sol sugirió en el
punto 10 de su respuesta (costo estimado ~$0.4-0.5, sí alcanza con el
presupuesto actual) para medir `P(actores_adicionales | saturated)` antes de
comprometer un gasto mayor.

### Preguntas que ya no hace falta responder (resueltas con datos)

- Pregunta 1 del informe original (¿varía el proveedor?): **No, en las 8
  llamadas de control fue siempre "OpenAI".**
- Pregunta 3 (¿cuántas confirmaciones?): **N=5 con la tasa real medida
  (~50%), no 14 como se estimó con p=0.2.**

### Pregunta nueva para Sol

Dado que el enrutamiento queda descartado y la tasa real es ~50% (no ~80%
como se pensaba), ¿sigue pareciéndote necesario el rediseño hacia extracción
independiente completa (Variante B/tu propuesta de `actor_second_pass_v2`
con `B - A` como diferencia de conjuntos), o el enfoque más simple de "más
confirmaciones" (N=5) sobre el diseño actual (Variante A) es suficiente
dado que ahora tenemos una tasa de fallo medida y no solo estimada?

---

## SEGUNDA ACTUALIZACIÓN 2026-09-17 (noche) — Sol respondió, se construyó y validó `actor_second_pass_v2`, resultado: la recomendación de Sol quedó parcialmente confirmada, parcialmente refutada

Sol respondió a la actualización anterior manteniendo su recomendación
original (no confiaría en `N=5` sobre reintentos idénticos porque la
secuencia de 8 llamadas consecutivas profundas es estadísticamente rara bajo
un `p=0.5` verdaderamente independiente -- P(8 seguidas)≈0.39% -- y señaló
correctamente que **elegimos esos 2 documentos justamente porque ya habían
mostrado un patrón inusual**, lo cual introduce sesgo de selección real en
la estimación de `p`. Recomendó construir `actor_second_pass_v2`: extracción
completa e independiente (sin `YA_EXTRAIDOS`), mismo schema de actor,
`maxItems=30`, comparación `B - A` hecha en código, no delegada al LLM.

### Lo que se construyó

- `Trabajo/prompts/actor_second_pass_v2.md` -- prompt de extracción
  exhaustiva desde cero (sin lista de referencia).
- `Trabajo/config/actor_second_pass_v2_schema.json` -- mismo shape de actor,
  `maxItems=30` en vez de 12.
- `Trabajo/scripts/actor_second_pass_v2.py` -- llama al modelo sin
  `YA_EXTRAIDOS`, compara localmente contra la primera pasada con un
  heurístico de normalización de nombres (NO resolución de entidades real,
  documentado explícitamente como tal), guarda `provider`/`reasoning_tokens`/
  `finish_reason` por documento.

### Primera prueba (sin mecanismo de reintento, 1 llamada por documento)

| Documento | pass1 | pass2 | nuevos | reasoning_tokens | resultado |
|---|---|---|---|---|---|
| `radio.uchile.cl` | 12 | 23 | 11 | 13.984 | ✅ Encontró EXACTAMENTE los 6 actores reales identificados a mano (Macarena Cañas, Sol Letelier, Carolina Casanova, Salvador Ferrer, Christian Espejo, Alfredo Parra) + 5 más legítimos |
| `lavozdelosquesobran.cl` | 12 | **0** | 0 | **27** | ❌ **Falló otra vez -- 0 actores, ni siquiera los 12 ya conocidos** |

**Este es el dato clave: el rediseño de Sol (quitar el atajo de "lista
vacía", pedir extracción completa desde cero) NO eliminó el modo de falla.**
`lavozdelosquesobran.cl` volvió a dar una respuesta casi sin razonamiento
(27 tokens) incluso sin la posibilidad de "comparar contra una lista y
confirmar que está completa" -- la hipótesis de que el atajo específico de
`YA_EXTRAIDOS` era la causa raíz no se sostiene con este resultado. El modo
de falla parece más fundamental que el diseño del prompt.

### Fix aplicado: disparador de reintento por conteo, no por vacío

En vez de reintentar solo cuando el resultado es literalmente vacío, se
agregó `N_CONFIRM_LOW=5`: si la segunda pasada (independiente, `maxItems=30`)
encuentra MENOS actores que la primera pasada (que ya está confirmada y
válida), eso es una señal de alarma -- la segunda pasada debería encontrar
al menos los mismos, al ser más permisiva. Se reintenta hasta 5 veces,
quedándose con el resultado de mayor conteo si todos fallan.

### Segunda prueba: `lavozdelosquesobran.cl` con el fix

| Intento | reasoning_tokens | actores encontrados | resultado |
|---|---|---|---|
| 1 (de hasta 5 posibles) | 17.389 | 23 (12 conocidos + **11 nuevos**) | ✅ Exitoso a la primera |

Los 11 nuevos incluyen los 4 actores reales identificados a mano (Segundo
Tribunal Ambiental, Seremi de Vivienda y Urbanismo, Contraloría General de
la República, María Angélica Benavides Casals) más 7 adicionales legítimos.
2 citas no verificaron literalmente (DOM de Peñalolén, Jorge Peña Vial) y se
sanearon correctamente (preservadas en `cita_original_modelo`, no
descartadas) -- la verificación de citas sigue funcionando como diseñado.

### Conclusión combinada

- **Sol tenía razón en la crítica metodológica**: la muestra de 8 llamadas
  consecutivas profundas NO era una prueba limpia de `p=0.5` -- había sesgo
  de selección real (se probaron los 2 documentos ya conocidos como
  "difíciles"), y su escepticismo sobre confiar en reintentos puramente
  idénticos estaba bien fundado.
- **Sol tenía razón en que `v2` (extracción completa e independiente) da
  MUCHO mejor calidad cuando el modelo se compromete**: en ambos documentos,
  cuando `v2` funcionó, encontró exactamente (o mejor que) los actores
  reales verificados a mano, con más precisión que la Variante A original.
- **Pero el dato nuevo (0/0 en `lavozdelosquesobran.cl` con `v2` en el
  primer intento) muestra que el modo de falla estocástico NO es exclusivo
  del diseño diferencial** -- persiste incluso en una tarea de extracción
  abierta sin atajo de "lista vacía trivial". Esto sugiere que el mecanismo
  no está completamente identificado todavía (como la propia Sol anticipó:
  "el mecanismo exacto no está identificado").
- **Diseño final adoptado**: `actor_second_pass_v2` (extracción completa,
  mejor calidad) + reintento disparado por conteo bajo (no solo por vacío),
  hasta 5 intentos. Validado 2/2 en los documentos difíciles conocidos,
  costo total de esta ronda de validación: **$0.04289**.

### Costo acumulado de toda la investigación

**$0.237** de los $1.87 originales. Quedan aproximadamente **$1.633** --
alcanza holgadamente para el canario aleatorio de 20-30 documentos que Sol
propuso (`--random-sample`, ya implementado en el script con `--seed` para
reproducibilidad). No se ha corrido todavía; pendiente de autorización
explícita antes de gastar más.

---

## TERCERA ACTUALIZACIÓN 2026-09-17 (noche) — Quality gate implementado siguiendo la segunda respuesta de Sol

Sol respondió de nuevo señalando un problema real en el diseño: aceptar un
intento solo porque `len(B) >= len(A)` es insuficiente -- B podría tener MÁS
actores que A y aun así omitir varios centrales de A mientras agrega ruido
secundario. También señaló que elegir "el intento de mayor conteo" entre
intentos fallidos es el criterio equivocado (debería preferir cobertura, no
volumen).

### Lo que se implementó (sin gastar dinero -- todo local)

- `quality_metrics(pass1, pass2_verified)`: calcula `central_recall`
  (cuántos actores `central` de A reaparecen en B), `total_recall` (cuántos
  de A en total reaparecen en B), `quote_verified_rate` (qué fracción de las
  citas de B verificaron literalmente), y `new_central_count`.
- `passes_quality_gate()`: exige `len(B) >= len(A)` **Y**
  `central_recall >= 0.90` **Y** `total_recall >= 0.75` (umbrales de Sol,
  explícitamente marcados como ajustables tras observar el canario, no como
  verdades universales).
- `qa_score()`: orden de desempate lexicográfico cuando NINGÚN intento pasa
  el gate -- `central_recall` primero, luego `total_recall`, luego
  `quote_verified_rate`, luego actores centrales nuevos, y el conteo bruto
  solo al final. Reemplaza el criterio anterior de "quedarse con el mayor
  conteo".
- `N_CONFIRM_LOW=5` cambia de semántica: ya no es "reintentar hasta
  conseguir un conteo alto", es "reintentar hasta conseguir UN resultado que
  pase el gate de calidad".
- `actores_final` en la salida: unión de A y B_valid con procedencia
  (`source_pass`: `first`/`second`/`both`) -- un actor válido de la primera
  pasada NUNCA se pierde solo porque una inferencia estocástica de B no lo
  repitió.

### Verificación (sin llamar a la API, siguiendo la advertencia de Sol de no seguir sobre-ajustando con Radio UChile / La Voz)

Se agregaron 6 tests unitarios nuevos (`test_actor_second_pass_v2.py`),
incluido el caso exacto que describió Sol: un intento con 13 actores (más
que los 12 de A) pero que solo recupera 5 de los 12 centrales -- el gate
ingenuo por conteo lo habría aceptado, el gate nuevo lo rechaza
correctamente. Suite completa del proyecto: **91/91** (85 anteriores + 6
nuevos).

### Estado: listo para el canario, pendiente autorización

No se volvió a probar sobre los 2 documentos conocidos (para no
sobre-ajustar, como recomendó Sol). El script está listo para
`--random-sample 25 --seed <N> --confirm-real-run`. Presupuesto disponible:
**~$1.633**, suficiente según el costo observado en las pruebas reales
(promedio ~$0.014-0.024/doc en intentos profundos). No se ha ejecutado
todavía -- pendiente de autorización explícita del usuario.

---

## CUARTA ACTUALIZACIÓN 2026-09-17 (noche) — Canario de 25 documentos ejecutado, resultados completos

Autorizado y corrido: `--random-sample 25 --seed 42`. Resultados con las
métricas exactas que pidió Sol:

| Métrica | Resultado |
|---|---|
| % con ≥1 actor nuevo (B-A>0) | 21/25 (84%) |
| % con ≥1 actor CENTRAL nuevo | 21/25 (84%) |
| % sin ningún actor nuevo | 4/25 (16%) |
| actores nuevos por doc (media / mediana) | 9.32 / 10.0 |
| actores centrales nuevos por doc (media / mediana) | 6.48 / 6.0 |
| docs que llegaron al nuevo tope (maxItems=30) | 5/25 (20%) |
| intentos necesarios (media) | 2.12 -- 16 docs en 1 intento, 5 en 2-4, **4 agotaron los 5 intentos sin pasar el gate** (CORREGIDO: esta fila decía "5" por error de escritura; el numero correcto, verificado directo contra `actor_second_pass_v2.jsonl` con `gate_passed==False`, es 4 -- coincide con la sección de abajo, que siempre dijo 4/25. Sol detectó correctamente la inconsistencia.) |
| `quote_verified_rate` de los actores nuevos | 228/233 = **97.9%** |
| costo total del canario | **$0.82834** |
| costo por doc (media / mediana) | $0.03313 / $0.02604 |

### Hallazgo nuevo: 4/25 (16%) agotaron los 5 intentos SIN pasar el gate -- más de lo esperado

Con la tasa ~50% medida antes, se esperaba `0.5^5≈3%` de fallos totales por
documento -- 4/25 es mucho más alto. Los 20 intentos de esos 4 documentos
(5 cada uno) dieron TODOS `reasoning_tokens` en el rango 19-40, sin una sola
excepción -- no parece ser mala suerte con una moneda de 50%, parece un
sub-grupo de documentos con una probabilidad de fallo mucho más alta que el
promedio general. 3 de los 4 comparten el tema "Lo Barnechea", el cuarto es
de un tema distinto (guetos verticales en Estación Central) -- no se
encontró un factor común claro (longitud del texto: 6.483-17.219
caracteres, sin patrón). Estos 4 documentos NO se recuperaron -- quedan con
`actores_final` = solo los de la primera pasada (nunca se pierde nada, pero
tampoco se ganó nada en estos 4).

### Revisión manual de un caso límite

Se revisó a mano el documento con menor `total_recall` (0.83, perdió 2 de
12 actores de la primera pasada: "Santiago Braganza" y "Mónica Pérez",
ambos secundarios) y con más actores nuevos (20, llegando al tope de 30).
Es un artículo sobre el estallido social (ocupación de calles) donde la
primera pasada YA había incluido actores tipo "Manifestantes"/"Primera
Línea"/"Carabineros" -- los actores nuevos de v2 (ciudadanos, rescatistas,
bomberos, etc.) siguen el mismo criterio de alcance que la primera pasada ya
tenía para este documento borderline, no es una regresión de precisión
introducida por v2.

### El hallazgo más importante: proyección de costo para los 266 completos

**$8.81 USD** (266 × $0.03313/doc, el promedio real medido en este
canario) -- **muy por encima tanto del presupuesto original ($1.87) como
del restante actual (~$0.80 tras gastar $1.065 en toda la investigación)**.
El costo por documento resultó mucho mayor de lo estimado originalmente
(~$0.014-0.024/doc en las pruebas de validación con 2 documentos) porque
varios documentos del canario aleatorio encontraron muchos más actores
nuevos (hasta 20, llegando al tope de 30) y consumieron más tokens de
razonamiento que los 2 casos de validación inicial.

### Estado y decisión pendiente

No se ha escalado a los 266 completos. Antes de decidir, hace falta: (1)
recargar saldo en la API (el canario ya demostró que el diseño funciona:
84% de los documentos saturados sí tenían actores reales adicionales, con
97.9% de citas verificadas), o (2) evaluar si con el presupuesto restante
(~$0.80) alcanza para un subconjunto priorizado de los 241 documentos
restantes en vez de todos. Pendiente de decisión del usuario.

---

## QUINTA ACTUALIZACIÓN 2026-09-17 (noche) — correcciones tras la tercera respuesta de Sol: discrepancia 4/5 resuelta, auditoría de precisión, flag de truncamiento

### 1. Discrepancia 4 vs 5 -- Sol tenía razón, era un error real de escritura

Verificado directo contra `actor_second_pass_v2.jsonl` con `gate_passed ==
False`: **el número correcto es 4**, no 5. La fila de la tabla en la
sección anterior decía "5 agotaron los 5 intentos" por error de tipeo mío
-- el resto del informe (título de la sección, texto explicativo) siempre
dijo 4/25 correctamente. Corregido en la tabla original, dejando anotado el
error para que quede trazable.

### 2. Flag de truncamiento para los 5 documentos que saturan `maxItems=30`

Se agregó `actores_pass2_posiblemente_truncados` (bool) a la salida del
script y se aplicó retroactivamente (sin gastar API) a los 5 documentos del
canario que llegaron al tope: estos quedan marcados explícitamente como "30
es un piso, no necesariamente una lista exhaustiva" -- mismo patrón que
`actores_posiblemente_truncados` de la primera pasada.

### 3. Auditoría manual de precisión (69 actores nuevos, 5 documentos)

Se clasificó cada actor nuevo de 5 documentos (oversampling los de 15-20
nuevos y los que llegaron a 30, como pidió Sol) en: correcto (central o
secundario, identidad específica) vs. vago/genérico (descripción colectiva
sin nombre propio, ej. "muchas autoridades", "los comités", "algunos
apoderados") vs. fabricado.

| Documento | Nuevos | Correctos | Vagos/genéricos | Fabricados |
|---|---|---|---|---|
| `terram.cl` (humedal Quilicura) | 18 | 18 | 0 | 0 |
| `defendamoslaciudad.cl` (Parisi/masones) | 18 | 16 | 2 | 0 |
| `hic-net.org` (Movimiento de Pobladores) | 13 | 7 | 6 | 0 |
| `latercera.com` (Comité de Ministros) | 10 | 9-10 | 0-1 | 0 |
| `df.cl` (requerimientos inmobiliarios) | 10 | 7 | 3 | 0 |
| **Total** | **69** | **~57-58 (~83-84%)** | **~11-12 (~16-17%)** | **0** |

**Ningún actor fabricado** -- toda cita verificada rastrea a un fragmento
real del texto. Pero ~1 de cada 6 actores nuevos es una descripción
colectiva vaga ("muchas autoridades", "algunos apoderados", "las
constructoras") con cita real pero sin identidad específica -- útil como
evidencia de contexto, de valor limitado como nodo en un análisis de redes
(exactamente el tipo de entrada que Darío necesitaría filtrar o descartar
antes de construir el grafo). El documento `hic-net.org` (un ensayo más
sociológico/histórico que una nota de incidente puntual) concentra la
mayoría del ruido (6/13, 46%) -- parece un problema dependiente del género
del artículo, no un fallo generalizado del diseño.

### Conclusión combinada final

- Recall: 84% de documentos saturados con ≥1 actor central nuevo real,
  mediana 6 por documento -- confirmado como corrección material, no
  cosmética.
- Precisión: ~83-84% de los actores nuevos son entradas de calidad para una
  red de actores; ~16-17% son descripciones vagas (no fabricaciones, pero
  de bajo valor como nodo) que convendría filtrar en el postprocesamiento
  antes de construir cualquier red.
- 4/25 (16%) documentos con fallo persistente del modo superficial en los 5
  intentos -- mecanismo aún no identificado, no bloquea el resto.
- 5/25 (20%) vuelven a saturar en el nuevo tope de 30 -- ahora marcados
  explícitamente, no descartados silenciosamente.
- Costo real proyectado a los 266: **$8.81**, sobre un presupuesto que ya
  gastó $1.065 de $1.87 (quedan ~$0.80).

### Bandera `nombre_generico` (respuesta a "¿qué hacemos con el % de vagos/genéricos?")

Siguiendo el mismo patrón ya establecido en todo el pipeline (sanear sin
descartar, marcar la incertidumbre, dejar la decisión de uso para la etapa
correspondiente): se implementó `is_nombre_generico()` en
`actor_second_pass_v2.py` -- heurístico de superficie (prefijos
cuantificadores tipo "muchas"/"algunos"/"un" + ausencia de sustantivo
propio con mayúscula), **no NLP real**. Probado contra las 69 etiquetas
manuales de la auditoría de precisión: **97.1% de acuerdo, 0 falsos
negativos** (nunca deja pasar un vago sin marcarlo), 2 falsos positivos
defendibles ("la policía", "comunidad quilicurana" -- casos límite
razonables de marcar por exceso de cautela).

Se aplicó retroactivamente a los 25 documentos del canario (sin gastar
API): de 533 actores en `actores_final` (unión completa A∪B), **91 (17.1%)
quedaron marcados `nombre_generico=true`** -- consistente con el 16-17%
medido a mano en la muestra de 69. El campo se agrega a cada actor
individual (no se descarta nada) más un conteo agregado
`nombre_generico_count` por documento para filtrar rápido. La decisión de
incluir o excluir estos nodos en la red queda para la etapa de análisis
(Darío / entity resolution definitivo), no se toma aquí.

### SEXTA ACTUALIZACIÓN 2026-09-17 (noche) — correcciones de Sol (redacción/matemática) y de Luna (higiene de datos), aplicadas

**Correcciones de redacción de Sol** (no afectan el código, solo cómo se
describe la evidencia):
- Donde este informe dice "84% de documentos con actor central nuevo
  REAL", la formulación correcta es: **"84% de documentos con al menos un
  actor adicional clasificado como central por la segunda pasada; la
  auditoría manual dirigida (69 actores, no aleatoria) encontró ~83-84% de
  esas entradas sustantivamente válidas."** No se verificó a mano cada
  actor central nuevo de los 21 documentos que pasaron el gate.
- El 83-84% de precisión es una **precisión observada en auditoría
  adversarial/dirigida** (se sobremuestrearon deliberadamente los casos más
  difíciles: 15-20 actores nuevos y los saturados en 30) -- no una
  estimación insesgada representativa de los 266 documentos completos. Es
  razonable esperar que la precisión real sobre una muestra aleatoria sea
  igual o mejor, pero eso no se ha medido.
- Corrección matemática: **241 documentos restantes** (266 - 25 ya
  procesados) × $0.03313/doc = **$7.99**, no $8.81 (que era la proyección
  sobre los 266 completos sin descontar el canario ya hecho).

**Hallazgo real de higiene de datos de Luna, verificado y corregido:**
`actor_second_pass_v2.jsonl` mezclaba 26 registros -- los 25 del canario
aleatorio + 1 registro de la validación dirigida anterior sobre
`lavozdelosquesobran.cl`, sin ningún campo que los distinguiera. Verificado
directo contra el archivo: exactamente como sospechó Luna. Además, ese 1
registro de validación no tenía el campo `gate_passed` (se generó con una
versión anterior del script, antes de implementar el quality gate) -- al
contarlo junto con el canario como "gate_passed=False" por defecto (None es
falsy), se leía como un 5º fallo que en realidad no existe (ese documento
sí encontró los actores esperados). Corregido:
- Separado en `actor_second_pass_v2.canario_25_seed42.jsonl` (25, ahora
  también el archivo canónico `actor_second_pass_v2.jsonl`) y
  `actor_second_pass_v2.validacion_dirigida_2docs.jsonl` (1), cada registro
  con `run_type` explícito.
- Archivo mezclado original preservado como
  `actor_second_pass_v2.MEZCLADO_SUPERADO_2026-09-17.jsonl` (nunca se
  borra, se archiva).
- Backfill del campo `gate_passed=true` en el registro de validación, con
  nota explicando por qué faltaba.

**Manifest formal construido** (pedido por Luna):
`Trabajo/scripts/build_actor_second_pass_v2_manifest.py` ->
`Auditoria/enriquecimiento_v3_2_934/actor_second_pass_v2/run_manifest_canario_25_seed42.json`
-- congela hashes de prompt/schema/script y los umbrales del quality gate
(central_recall>=0.90, total_recall>=0.75, N_CONFIRM_LOW=5,
PASS2_MAX_ITEMS=30), documenta comando exacto, seed, muestra, universo
completo (266, con hash), y todos los resultados agregados. Cualquier
cambio futuro a estos archivos rompe la comparabilidad con estos 25
documentos -- mismo patrón que `universo_congelado_934.json`.

**Hallazgo adicional** (lectura manual de los 4 documentos con fallo
persistente, sin costo): 3 de los 4 ya tenían `revision.nivel` != "ninguno"
en la PRIMERA pasada (mezclan varios proyectos, fechas dudosas) -- posible
correlación entre complejidad/ambigüedad del artículo (ya detectada por el
propio pipeline) y el modo de falla superficial de la segunda pasada. No
confirmado con muestra suficiente, queda como hipótesis para investigar si
se revisita este subgrupo en el futuro.

**Estado de integración FARO** (pedido por Luna): `active-context.md`,
`stage_roadmap.yaml` y `stage_state.json` actualizados con el estado real
de `actor_second_pass_v2` -- explícitamente marcado como **NO integrado al
warehouse principal**, experimental, con el puente
`documento -> caso/proyecto -> actor/evento` (señalado por Luna) todavía
sin resolver antes de cualquier fusión a un análisis de redes real.

### Decisión pendiente (sin ejecutar nada más)

Sol recomienda explícitamente NO hacer un subconjunto priorizado por
presupuesto (riesgo de sesgo de selección en la red: los documentos más
complejos tendrían mejor extracción que los simples) y en su lugar elegir
entre: (a) parar aquí, dejar los 25 documentos del canario procesados, y
esperar más saldo para correr los 241 restantes con el mismo diseño
congelado, o (b) recargar el saldo ahora (~$9-10 sugeridos por Sol) y
terminar los 266 en una sola pasada limpia. No se ha tomado la decisión --
pendiente del usuario.

## 1. Contexto y objetivo

El enrichment v3.2 (934 documentos) ya está completo y su warehouse construido (ver `stage_state.json`). Uno de los pendientes declarados no bloqueantes es una **segunda pasada actor-only**: 266/934 documentos (28.5%) quedaron marcados `actores_posiblemente_truncados=true` porque la primera pasada satura el array de actores en `maxItems=12` — el schema no permite más de 12 actores por documento, y varios artículos mencionan más.

Se diseñó un pipeline separado (`Trabajo/scripts/actor_second_pass_v1.py`) para hacer una segunda llamada LLM, angosta, que solo pida actores ADICIONALES no capturados en la primera pasada, sin tocar el resto del registro. El objetivo de esta ronda de pruebas era validar el diseño en una muestra chica (3 documentos) antes de autorizar gasto en los 266 completos.

**Presupuesto real disponible en la API al momento de estas pruebas: USD 1.87.**

## 2. Resultado: el diseño funciona, pero encontramos un problema de fondo no resuelto

No es un problema de "quality del prompt" simple. Es **variabilidad aparentemente no determinista en cuánto "piensa" el modelo** (medido por `reasoning_tokens`) para la MISMA llamada exacta, con consecuencias directas en si encuentra o no actores reales que sabemos (verificado a mano) que están en el texto.

## 3. Diseño del pipeline

### 3.1 Prompt del sistema (texto completo, `Trabajo/prompts/actor_second_pass_v1.md`)

```
Eres un analista que revisa un articulo de prensa sobre un conflicto inmobiliario/urbano en Santiago. Ya se extrajo una PRIMERA lista de actores de este articulo, pero el articulo probablemente menciona MAS actores que no entraron porque la primera pasada tenia un tope de 12.

Tu tarea es encontrar SOLO actores ADICIONALES que NO esten ya en la lista que se te entrega, siguiendo las mismas reglas que la primera pasada:

1. Un "actor" tiene un rol estructural real en el conflicto (demanda, es demandado, decide, media, o participa organizadamente) o esta mencionado de forma relevante -- no cualquier nombre propio que aparece de pasada.
2. nivel_involucramiento: central (ejecuta una accion, la recibe, toma una decision, o participa organizadamente) o secundario (aparece mencionado pero sin ese rol estructural). No descartes actores secundarios -- eso es exactamente lo que se perdio en la primera pasada por el tope de 12; etiquetalos como secundario, no los omitas.
3. cita debe ser un fragmento LITERAL y contiguo del texto entregado, nunca inventado ni parafraseado. Si no hay una cita directa razonable, deja el campo vacio.
4. No infieras un actor que no esta mencionado explicitamente en el texto.
5. stance: postura que EL TEXTO documenta para ese actor especifico frente al proyecto/conflicto (apoya/se_opone/neutral/mixto), no un tono general del articulo. Usa no_determinable si el texto no permite determinarlo.
6. proyecto_asociado: si el articulo menciona mas de un proyecto/edificio con nombre propio (ver PROYECTOS_MENCIONADOS mas abajo), indica a cual se refiere la participacion de este actor especifico (copia literal de uno de esos nombres). Cadena vacia si solo hay un proyecto o no se puede determinar.
7. NO repitas ningun actor de la lista YA_EXTRAIDOS que se te entrega (compara por nombre, no solo por string exacto -- "Municipalidad de Nunoa" y "el municipio" pueden ser el mismo actor ya extraido).
8. Si genuinamente no hay actores adicionales mas alla de los ya extraidos, devuelve una lista vacia -- no inventes actores para llenar espacio.

Responde solo con el JSON pedido por el schema.
```

### 3.2 Contenido del mensaje de usuario (por documento)

```
YA_EXTRAIDOS (no los repitas): [lista de los <=12 nombres de la primera pasada]
PROYECTOS_MENCIONADOS: [lista de proyectos del documento]

TEXTO DEL ARTICULO:
<texto completo del articulo, hasta 30.000 caracteres>
```

### 3.3 Schema de respuesta (JSON Schema estricto, `response_format: json_schema`)

Reutiliza el mismo shape de item de actor que el schema de la extracción original (`enrichment_schema_v3_2.json`): `nombre`, `tipo` (enum de 12 valores), `rol` (enum de 5 valores), `stance` (enum de 5 valores), `nivel_involucramiento` (`central`/`secundario`), `cita`, `proyecto_asociado`. Envuelto en `{"actores_adicionales": [...]}`, `maxItems: 12`.

### 3.4 Parámetros del modelo

- Modelo: `openai/gpt-5.6-luna` (mismo modelo de toda la pipeline)
- Iteración 1 (prueba inicial): `reasoning.effort = "medium"`, `max_tokens = 6000`
- Iteración 2 (tras fallar la 1): `reasoning.effort = "xhigh"`, `max_tokens = 16000`
- Iteración 3 (fix actual): `reasoning.effort = "xhigh"`, `max_tokens = 28000`, más lógica de "doble confirmación" (ver §6)

## 4. Universo de la segunda pasada

266 de 934 documentos (28.5%) tienen `actores_posiblemente_truncados=true`. Costo real de la PRIMERA pasada completa sobre esos 266 (ya pagado, es el dato de referencia para estimar la segunda): **USD 7.2226** total, promedio **USD 0.02892/doc**, mínimo 0.01332, máximo 0.07321, mediana 0.02785.

## 5. Cronología completa de las pruebas (3 documentos fijos en las primeras 3 rondas)

Documentos de prueba:
1. `https://radio.uchile.cl/2026/03/10/el-minvu-rechazo-un-perdonazo-para-edificio-ilegal-de-la-universidad-san-sebastian/` — 5.264 caracteres, ~855 palabras, 12 actores en primera pasada (saturado)
2. `https://lavozdelosquesobran.cl/opinion/la-municipalidad-de-penalolen-obedecio-a-un-miembro-de-la-elite/24042025` — 8.028 caracteres, ~1.274 palabras, 12 actores en primera pasada (saturado)
3. `https://interferencia.cl/articulos/inmobiliaria-pocuro-inicia-tala-de-arboles-nativos-en-penalolen-alto-tras-visto-bueno-de` — 7.513 caracteres, ~1.240 palabras, 12 actores en primera pasada (saturado)

**Nota importante**: el documento que SIEMPRE funcionó bien (interferencia.cl) NO es el más largo de los 3 — lavozdelosquesobran.cl es más largo (8.028 vs 7.513 caracteres) y sin embargo falló siempre. La longitud del texto por sí sola no explica el patrón.

### Ronda 1 — `effort=medium`, `max_tokens=6000`

| Documento | actores nuevos | reasoning_tokens | costo |
|---|---|---|---|
| radio.uchile.cl | 0 | 20 | $0.00007 |
| lavozdelosquesobran.cl | 0 | 21 | $0.00008 |
| interferencia.cl | 3 | 1.034 | $0.00159 |
| **Total** | | | **$0.00174** |

### Ronda 2 — `effort=xhigh`, `max_tokens=16000`, sin cambiar nada más

| Documento | actores nuevos | reasoning_tokens | costo |
|---|---|---|---|
| lavozdelosquesobran.cl | 0 | 28 | $0.00036 |
| radio.uchile.cl | 0 | 31 | $0.00012 |
| interferencia.cl | 11 | 11.394 | $0.01513 |
| **Total** | | | **$0.01560** |

**Hallazgo de esta ronda**: subir el esfuerzo de `medium` a `xhigh` NO cambió el resultado de los 2 documentos que fallaban (siguen en `reasoning_tokens` de 20-34, prácticamente idéntico a `medium`). El nivel de esfuerzo solicitado no parece ser la variable causal.

### Ronda 3 — Diagnóstico quirúrgico sobre UN documento (radio.uchile.cl), 3 variantes de técnica, cada una 1 sola llamada

**Variante A — baseline** (prompt/schema idénticos a la Ronda 2, `effort=xhigh`, pero con `max_tokens=16000` igual que antes):

```
reasoning_tokens=15569  cost=$0.0195594  finish_reason="length" (CORTADO por el tope de tokens)
```

Esta es la MISMA llamada exacta que en la Ronda 2 dio `reasoning_tokens=31` y "0 actores". Esta vez, sin cambiar nada, dio `reasoning_tokens=15569` (500x más) y produjo actores reales (Megavisión, Liceo Alemán, etc. — visible en lo que alcanzó a generar antes de cortarse por el tope de tokens). **Esta es la evidencia central de que el problema es variabilidad estocástica de la misma llamada, no una propiedad fija del documento.**

**Variante B — sin la lista "YA_EXTRAIDOS", sin `response_format` json_schema, pidiendo la lista COMPLETA de actores desde cero** (no solo los "adicionales"):

Prompt usado:
```
Eres un analista que lee un articulo de prensa sobre un conflicto inmobiliario/urbano en Santiago. Lista TODOS los actores (personas, instituciones, empresas) con un rol estructural real en el conflicto (demanda, es demandado, decide, media, o participa organizadamente) o mencionados de forma relevante, sin ningun limite de cantidad. Para cada uno: nombre, rol (demandante/demandado/autoridad_decisora/mediador/mencionado), nivel_involucramiento (central/secundario), y una cita literal del texto. No omitas ninguno por brevedad. Responde en JSON: {"actores": [{"nombre":..., "rol":..., "nivel_involucramiento":..., "cita":...}]}
```

```
reasoning_tokens=13478  cost=$0.018573  finish_reason="stop" (completo, sin cortarse)
```

Encontró correctamente (mezclado con los ya conocidos, sin filtrar): Universidad San Sebastián, Desarrollo Inmobiliario Bellavista S.A., Municipalidad de Recoleta, DOM de Recoleta, Carlos Reyes, y siguió generando una lista extensa y correcta (respuesta completa, no truncada).

**Variante C — mismo prompt/schema que A, pero con una advertencia explícita agregada**:

Se agregó al prompt original: *"ADVERTENCIA IMPORTANTE: este documento fue marcado por un sistema automatico como 'actores_posiblemente_truncados=true', lo que significa que la primera pasada probablemente NO capturo a todos los actores reales del texto. Es MUY POCO PROBABLE que la respuesta correcta sea una lista vacia -- vuelve a leer el texto completo, nombre por nombre propio mencionado, y verifica cada uno contra la lista YA_EXTRAIDOS antes de concluir que no hay mas."*

```
reasoning_tokens=11202  cost=$0.01508785  finish_reason="stop"
```

Encontró correctamente (verificado a mano contra el texto): periodistas de Megavisión, Liceo Alemán, Congregación Religiosa del Verbo Divino, Gonzalo Cornejo, Minvu, **Macarena Cañas**, **Sol Letelier**, **Carolina Casanova** — exactamente los actores reales que un humano identifica leyendo el artículo completo.

Costo total de esta ronda diagnóstica (3 llamadas): **$0.05322**.

### Ronda 4 — Fix aplicado: `max_tokens=28000` + "doble confirmación" antes de aceptar un resultado vacío

Cambio de diseño: si la primera llamada da 0 actores adicionales, el script NO lo acepta de inmediato — hace una segunda llamada fresca (no un reintento por error, una llamada nueva completa) antes de aceptar "0" como definitivo (`N_CONFIRM_EMPTY = 2`).

| Documento | Intento 1 | Intento 2 | resultado final |
|---|---|---|---|
| lavozdelosquesobran.cl | 34 reasoning_tokens, 0 actores | 27 reasoning_tokens, 0 actores | 0 (confirmado 2 veces) |
| radio.uchile.cl | 31 reasoning_tokens, 0 actores | 34 reasoning_tokens, 0 actores | 0 (confirmado 2 veces) |
| interferencia.cl | 11.413 reasoning_tokens, 10 actores | (no necesitó 2do intento) | 10 |

Costo total de esta ronda: **$0.01504**.

**Conclusión de la Ronda 4**: el tope de tokens más alto SÍ evitó el corte (`finish_reason="length"` no volvió a aparecer). Pero 2 confirmaciones NO fueron suficientes para destrabar los 2 documentos problemáticos -- dieron 4 respuestas superficiales seguidas en total (contando la Ronda 2 + esta), todas entre 27 y 34 `reasoning_tokens`. Solo 1 de 5 intentos conocidos sobre `radio.uchile.cl` (contando el diagnóstico) fue profundo.

## 6. Los actores reales que el modelo sigue sin encontrar (verificados a mano, leyendo el texto completo)

### `radio.uchile.cl` — actores presentes en el texto, ausentes en la primera pasada Y en los 4 intentos fallidos de la segunda pasada:
- **Sol Letelier** — alcaldesa sucesora de Recoleta, "nunca atinó a nada"
- **Carolina Casanova** — arquitecta/abogada que intervino recientemente ("puso las cosas en su justo lugar")
- **Salvador Ferrer** — funcionario que aprobó la recepción final cuestionada
- **Christian Espejo** — abogado que gestionó la petición en nombre de la inmobiliaria
- **Macarena Cañas** — Fiscal que recibió la denuncia de corrupción
- **Alfredo Parra** — arquitecto de la DOM de Recoleta que emitió el permiso

(Encontrados correctamente por la Variante C del diagnóstico, en la única llamada "profunda" lograda para este documento.)

### `lavozdelosquesobran.cl` — actores presentes en el texto, ausentes en todos los intentos hasta ahora:
- **Segundo Tribunal Ambiental** — anuló el proyecto el 19/07/2023
- **Seremi de Vivienda y Urbanismo** — recibió el caso trasladado por la municipalidad
- **Contraloría General de la República** — recibió la denuncia
- **María Angélica Benavides Casals** — ministra de la 3ª Sala de la Corte Suprema, mencionada por nombre

(Este documento NUNCA tuvo una llamada "profunda" en ninguna de las 4 rondas -- 100% de los intentos fueron superficiales.)

## 7. Resumen de costos de toda esta investigación

| Ronda | Costo |
|---|---|
| 1 — medium, 3 docs | $0.00174 |
| 2 — xhigh, 3 docs | $0.01560 |
| 3 — diagnóstico, 3 variantes, 1 doc | $0.05322 |
| 4 — xhigh + doble confirmación, 3 docs | $0.01504 |
| **Total gastado en esta investigación** | **$0.08560** |

Presupuesto original: $1.87. Restante aproximado: **$1.78**.

## 8. Preguntas abiertas para Sol

1. ¿Es esperable/documentado que un modelo con razonamiento configurable (`reasoning.effort`) pueda ignorar el nivel de esfuerzo solicitado y variar su `reasoning_tokens` en 2-3 órdenes de magnitud (20 vs 15.000+) para la MISMA llamada exacta? ¿Hay algún parámetro adicional (temperature, top_p, seed) que podamos fijar para reducir esta varianza?
2. La Variante B (pedir la lista COMPLETA sin lista de exclusión, sin schema JSON estricto) funcionó bien en la única prueba que hicimos. ¿Es razonable la hipótesis de que darle al modelo un "atajo" (comparar contra una lista ya dada) lo invita a una verificación superficial, mientras que pedirle construir la lista desde cero fuerza un análisis más profundo? ¿Hay literatura o experiencia previa sobre esto con modelos de razonamiento?
3. Si escalamos con el diseño actual (Variante A + N confirmaciones) a los 266 documentos completos, ¿qué valor de `N_CONFIRM_EMPTY` recomendarías dado que ~1 de cada 4-5 intentos parece ser "profundo" para los casos problemáticos? ¿O directamente rediseñar hacia el patrón de Variante B (pedir todo, diferenciar localmente) para TODOS los documentos, no solo como fallback tras confirmar vacío?
4. La Variante B no usa `response_format: json_schema` estricto -- ¿vale la pena sacrificar la validación estructural estricta a cambio de una respuesta más confiable, verificando/normalizando el formato localmente después?
5. ¿Existe algún riesgo de que estemos midiendo mal el "esfuerzo real" -- es decir, que `reasoning_tokens` bajo no signifique necesariamente que el modelo "no trabajó", sino que resolvió la tarea genuinamente rápido para esos 2 documentos, y que los actores que un humano encuentra a mano sean, bajo alguna lectura razonable del prompt, "no estructurales" y el modelo tenga razón en omitirlos? (Nuestra lectura es que no -- Salvador Ferrer, por ejemplo, tomó una decisión administrativa central -- pero vale la pena que alguien más lo revise con ojos frescos).

## 9. Estado actual / decisión pendiente

**No se ha escalado a los 266 documentos.** El diseño actual no es confiable todavía para un lote grande sin gastar de más en reintentos, y sin entender la causa raíz no sabemos si 2, 5 o 10 confirmaciones serían suficientes de forma consistente. Se espera la opinión de Sol antes de decidir el siguiente paso (más confirmaciones vs. rediseño hacia Variante B vs. otra alternativa).
