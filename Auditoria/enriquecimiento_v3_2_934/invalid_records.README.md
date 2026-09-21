# invalid_records.jsonl — estado

Este archivo contiene **cuarentena historica, no errores vigentes**.

Las 2 entradas que quedan corresponden a 2 intentos fallidos del MISMO documento
(`https://elquintopoder.cl/ciudad/casa-de-italia-en-vina-del-mar-y-galeria-imperio-en-santiago/`),
durante el episodio del bug de `actores[11]` (2026-09-17). Ese documento fue
reintentado con exito y esta presente y valido en `enrichment.jsonl` (verificar
con `grep -c "casa-de-italia-en-vina-del-mar" enrichment.jsonl` -> debe dar 1).

`errors.jsonl` (en esta misma carpeta) esta vacio -- 0 errores vigentes en la
corrida.

No borrar este archivo: es la traza de auditoria de como se llego al 934/934
final, incluyendo los intentos que no funcionaron antes del fix.
