# Crosspost a X/Twitter y Facebook (jun 2026)

Misma aprobación de Telegram; `publish.py` (cron horario en Actions) publica en
las 3 redes. Nada cambia antes de la publicación.

## Flujo

```
Telegram aprueba → fila approved en Sheet → publish.py
                          ┌────────────────┼────────────────┐
                      instagram.py     x_twitter.py     facebook.py
                      ig_post_id       tw_post_id       fb_post_id
```

## Decisiones

- **Sheet**: columnas nuevas `tw_post_id`, `fb_post_id` al final (no rompen filas).
- **Estado**: `published` solo cuando todas las plataformas *habilitadas* tienen id.
  Fallo parcial → la fila sigue `approved` con nota; el cron siguiente reintenta
  SOLO las que falten (columna vacía = pendiente). Escritura al Sheet inmediata
  tras cada plataforma → sin duplicados si el job muere a medias.
- **Kill switch**: `CROSSPOST_X=0` / `CROSSPOST_FB=0` apagan una red sin tocar IG.
- **Captions**: X = sin @handles de IG (no etiquetan a nadie) + recorte limpio a
  280; FB = caption completo sin @handles. IG queda igual.
- **Carruseles**: FB = post multi-foto (`attached_media`, sin tope de 4);
  X = hilo (tweet con 4 imágenes + replies con el resto).
- **Auth**: X OAuth 1.0 (tokens sin expiración, app "Pay Per Use" — vigilar
  créditos); FB token de Página permanente (se invalida si cambia la contraseña
  de FB del admin; regenerar vía Graph Explorer + exchange).

## Fases

0. ✅ Credenciales (FB_PAGE_ID=1146548078548923 "GDL Scene Daily"; X @gdlscene).
1. `src/x_twitter.py` + `src/facebook.py` + config + smoke test real.
2. Fan-out en `publish.py` + columnas Sheet + tests con mocks.
3. Carruseles en ambas redes.
4. Secrets en Actions + primer ciclo vigilado.
