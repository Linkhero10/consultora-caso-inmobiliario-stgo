-- Consultas descriptivas reproducibles para case_warehouse_v1.sqlite.
-- No inferir causalidad ni usar nombres de comuna como clave si existe CUT/ComCod.

-- 1. Casos incluidos por comuna y tipo de conflicto.
SELECT comuna, tipo_conflicto, COUNT(*) AS n
FROM press_classification
WHERE decision = 'include'
GROUP BY comuna, tipo_conflicto
ORDER BY n DESC;

-- 2. Contexto territorial unido por código oficial.
SELECT comuna, poblacion, inmigrantes, viviendas_hacinadas,
       hot_days_present, hot_days_future_ssp245
FROM v_context
ORDER BY poblacion DESC;

-- 3. Permisos de vivienda: tendencia anual por comuna (piloto oficial MINVU).
SELECT comuna, year, SUM(value) AS unidades_permisos
FROM minvu_permisos
WHERE metric = 'unidades' AND tipo_vivienda = 'total'
GROUP BY comuna, year
ORDER BY comuna, year;

-- 4. Permisos de vivienda: m2 por tipo.
SELECT comuna, year, tipo_vivienda, SUM(value) AS m2_permisos
FROM minvu_permisos
WHERE metric = 'm2'
GROUP BY comuna, year, tipo_vivienda
ORDER BY comuna, year, tipo_vivienda;

-- 5. Red actor-actor: grado observado en los casos incluidos.
SELECT source_actor AS actor, COUNT(*) AS out_degree
FROM actor_edge
GROUP BY source_actor
UNION ALL
SELECT target_actor AS actor, COUNT(*) AS in_degree
FROM actor_edge
GROUP BY target_actor
ORDER BY 2 DESC;

-- 6. Literatura: relaciones argumentales registradas, no una inferencia causal.
SELECT source_id, source_label, relation, target_id, target_label, evidence_file
FROM literature_edge
ORDER BY source_id, target_id;
