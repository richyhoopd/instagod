# Feeds diarios para thescene-web: agenda + música nueva + cron

**Fecha:** 2026-06-07 · **Estado:** aprobado por Ricardo ("haz lo que creas más correcto")

## Meta
La web (Next 16 en Vercel, repo richyhoopd/thescene-web) debe mostrar SIEMPRE info fresca: noticias (memes publicados), agenda de shows (semana/mes) y música nueva (semana/mes), todo ligando al post de IG correspondiente. Sin volverla dinámica: contenido committeado + redeploy de Vercel.

## Restricción física
La DB es local (Mac de Ricardo). El refresco corre LOCAL (launchd) y empuja al repo web; GitHub Actions no aplica aquí (Vercel redeploya con el push). Cadena diaria: 21:30 `src.ig_insights` (ya existe, refresca ig_posts/permalinks) → 21:45 web-sync (nuevo).

## Diseño

### 1. `scripts/sync-content.mjs` (repo web) — EXTENDER, no reescribir
Lo existente queda intacto (stories + módulo `agenda` parseado de captions, que consume la portada WIP de otro agente). Se AGREGA una llave nueva top-level en `src/content/gdl.json`:

```jsonc
"secciones": {
  "agenda": {
    "permalink": "https://instagram.com/p/...",  // carrusel shows más reciente (semanal o mensual)
    "semana": [ {"fecha": "2026-06-12", "bandas": "Kabala · Wyyrd", "lugar": "Foro X", "ciudad": "GDL"} ],
    "mes":    [ ... ]                            // ventana 8-30 días (disjunta de semana)
  },
  "musicaNueva": {
    "permalink": "...",                          // carrusel releases más reciente
    "semana": [ {"fecha": "2026-06-04", "banda": "a l a m e d a", "titulo": "Yorke | Parsons", "tipo": "Live session", "cover": "/img/gdl/covers/<hash>.jpg"} ],
    "mes":    [ ... ]
  },
  "actualizado": "2026-06-07T21:45:00-06:00"
}
```
- Queries espejo de instagod (`eventos_ventana`/`releases_ventana`): shows futuros con `status != 'pasado' AND irrelevante = 0`, fecha hoy→+7 / +8→+30; releases `fecha_evento` últimos 7 / 8-30 días. Filtro `bands.account_id = (SELECT id FROM accounts WHERE slug='gdl'+'scene')` — multi-ciudad ready.
- Shows agrupados por fecha+lugar (misma lógica que `agrupar_por_evento`: mismas fecha+venue → bandas concatenadas con " · ").
- Releases: título sin sufijo "(sencillo)" (se separa a `tipo`, como `_parse_titulo` de instagod).
- Covers: copiar `data/covers/<hash>.jpg` → `public/img/gdl/covers/` (solo las referenciadas).
- Permalinks de sección: `ig_posts p JOIN content_queue q ON q.id = p.queue_id` con `q.tema_semilla LIKE 'shows %'` / `'releases %'`, el de `p.timestamp` más reciente. Sin post aún → permalink null (la página esconde el link).
- DB en `readOnly` (node:sqlite) — no toca el WAL.

### 2. Rutas nuevas de periódico (archivos NUEVOS — cero colisión con el WIP de page.tsx)
- `src/app/[city]/agenda/page.tsx` — sección "Agenda": lista editorial por fecha (semana arriba, "Resto del mes" abajo), link "Ver en Instagram →" al carrusel.
- `src/app/[city]/musica-nueva/page.tsx` — sección "Música Nueva": filas con mini-cover cuadrada + banda + título + tipo + fecha, mismo link de sección.
- Estilo: DESIGN.md al pie de la letra — página blanca, tinta #0a0a0a, UN verde de red (masthead/acentos), Tinos para titulares/cuerpo, Poppins solo labels, headline-first, deadpan absoluto (es la parte VERDADERA del periódico: datos reales servidos con seriedad editorial). Server components puros, sin JS cliente.
- Ciudad sin datos (cdmx/mty) → mensaje editorial sobrio ("Esta sección llega pronto a tu ciudad."), no 404.
- La portada ligará estas rutas cuando su agente integre (no toco page.tsx).

### 3. Cron `com.gdlscene.web-sync.plist` (launchd, 21:45 diario)
`node scripts/sync-content.mjs` y, si hay diff, `git add` SOLO `src/content public/img` → commit "content: sync diario" → push → Vercel redeploya. Log a `data/logs/web-sync.log` (instagod). Si la Mac duerme a las 21:45, launchd lo corre al despertar.

## Coordinación
- thescene-web tiene WIP ajeno en `src/app/[city]/page.tsx` y `src/proxy.ts`: NO tocarlos; commits siempre con paths explícitos (scripts/, rutas nuevas, src/content, public/img), jamás `git add -A`.
- instagod: solo lectura (la DB); nada que commitear ahí.

## Criterio de éxito
1. `node scripts/sync-content.mjs` produce `gdl.json` con `secciones` pobladas de la DB real (incluye los 15+ releases y shows vigentes) + covers copiadas.
2. `npm run build` verde; `/gdl/agenda` y `/gdl/musica-nueva` renderizan con data real y link al carrusel.
3. launchd cargado; primera corrida real commitea y pushea; Vercel despliega.
