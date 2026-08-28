---
target: portal-fase4-frontend
total_score: 19
p0_count: 4
p1_count: 3
timestamp: 2026-08-21T21-23-32Z
slug: portal-fase4-frontend
---
# Critique: portal de colaboradores (frontend portal-fase4)

Probado en vivo (Chrome, DB copia segura) + revisión de código + detector determinístico.
Objetivo declarado: usable por core team NO técnico, estándar Airbnb.

## Design Health Score

| # | Heurística | Score | Hallazgo clave |
|---|-----------|-------|----------|
| 1 | Visibilidad del estado | 2 | Preview de estilos en "Generando..." infinito sin worker; salud de conexiones sin estado hasta apretar "Probar"; posts de junio listados como "Próximas publicaciones" sin marcar atraso |
| 2 | Sistema ↔ mundo real | 1 | Jerga técnica en toda la UI: `TELEGRAM_BOT_TOKEN`, "LLM", "prompts", "slug", "JSON crudo", "la fila", "endpoint", "el motor", "Listicle", "Meme #1719" |
| 3 | Control y libertad | 2 | Aprobar (= publicar en IG) sin confirmación ni undo; item programado no se puede reprogramar/despublicar desde el drawer (solo drag); agendar es drag-drop-only |
| 4 | Consistencia | 3 | Vocabulario shadcn consistente; spanglish intermitente; "gdlscene" vs "@pensionmas" |
| 5 | Prevención de errores | 1 | Aprobar a un clic (icon-only) en lista de 87; JSON crudo editable a mano; zona horaria = texto libre IANA; sin resumen antes de "Generar" |
| 6 | Reconocimiento > memoria | 2 | 12 chips idénticos "La agenda de… Pendiente"; claves de secretos como nombres de env vars; presets = swatch "Aa" sin preview real |
| 7 | Flexibilidad y eficiencia | 2 | Sin bulk approve para 87 pendientes; sin atajos; "Reusar tema" bien |
| 8 | Estética y minimalismo | 3 | Limpio y sobrio, pero dashboard = lista infinita; triple encabezado redundante; tema 100% acromático sin identidad |
| 9 | Recuperación de errores | 2 | "Reintentar" en drawer bien; errores Pydantic crudos en inglés en login; "Generando..." sin timeout ni error |
| 10 | Ayuda y documentación | 1 | Cero onboarding; empty states no enseñan ("No hay temas sugeridos por ahora."); Horarios explica internals de la API en vez de ayudar |
| **Total** | | **19/40** | **Funcional para su autor; bloqueante para no técnicos** |

## Veredicto anti-patrones

**LLM assessment:** No es slop visual clásico (nada de gradient text, side-stripes, eyebrows). El problema es de otro tipo: es una **UI de desarrollador para desarrolladores** con piel shadcn default. El slop está en el contenido: nombres internos del sistema (env keys, ids, slugs, JSON) presentados como UI, tema zinc acromático sin un solo color de marca, y patrones "primer borrador" (lista sin límite, textareas vacíos sin guía).

**Detector determinístico:** 1 hallazgo — `broken-image` en `preset-editor.tsx:71` (`<img>` de preview sin src hasta que llega el preview). Sin otros antipatrones estructurales. Overlay en browser: omitido (audit multi-página autenticado; evidencia por screenshots).

## Lo que funciona

1. **Arquitectura de navegación correcta**: Dashboard / Calendario / Crear / Biblioteca / Ajustes es exactamente el modelo mental correcto; el switcher de marcas en header está bien resuelto.
2. **Feedback de mutaciones**: toasts con contenido útil ("Aprobado, programado para 22 ago 3:00 p.m."), skeletons en cargas, "Guardar caption" aparece solo con cambios sucios, Eliminar con AlertDialog.
3. **Wizard de crear**: 5 pasos con progressive disclosure real; nada intimida en el paso 1.

## Priority Issues

**[P0-1] Jerga técnica en superficies de usuario (heurística 2, transversal).**
Dónde: cards de /brands (badges `TELEGRAM_BOT_TOKEN`, `IG_ACCESS_TOKEN`, `IG_USER_ID`); Conexiones (claves en monospace, "LLM"); Voz ("prompts", "para el LLM", "Hashtags de prompts"); Estilos ("presets globales del motor", "JSON crudo", slug `gdlscene_clasico`); drawer ("Meme #1719", "descarta la fila"); Biblioteca ("slideshow todo_lo_que_sabemos:"); Horarios ("la API todavía no expone un endpoint para editar posting_slots"); Nueva marca (campo "slug"); wizard ("el motor", "Listicle", "default").
Por qué importa: el usuario objetivo no sabe qué es un token ni un JSON; cada pantalla le exige traducción o rendirse. Es la distancia #1 contra el estándar Airbnb.
Fix: diccionario de UI en español humano (Instagram → "Conexión con Instagram", TELEGRAM_BOT_TOKEN → "Bot de Telegram", LLM → "Motor de textos (IA)", sin ids internos en títulos, sin slugs visibles, autogenerar slug desde nombre).

**[P0-2] Aprobar = publicar de verdad, a un clic y sin explicación (heurísticas 3+5).**
Dónde: dashboard (87 filas con iconos ✓/✕ sin label ni confirm), drawer (botón Aprobar sin confirm).
Por qué: es LA acción irreversible del producto (sale al Instagram real de la marca) tratada con menos fricción que "Eliminar" (que sí confirma). Un misclick en la lista publica contenido.
Fix: confirmación con contexto ("Se programará para el 22 ago 3:00 p.m. y se publicará en @gdlscene") + labels de texto en botones + deshacer inmediato (ventana de gracia) o al menos "despublicar" desde programado.

**[P0-3] Editor de Estilos = textarea de JSON crudo (heurísticas 2+5).**
El spec pedía editor visual con preview; hoy: inputs de color por nombre ("blanco"/"verde"), y `roles` "solo se edita en el JSON crudo de abajo". Preview se cuelga en "Generando..." si el worker no corre (sin timeout/error).
Fix: controles visuales por rol (fuente/tamaño/estilo con selects), JSON escondido tras "Avanzado", preview con estados de error y timeout.

**[P0-4] Dashboard invertido: lista infinita de pendientes entierra todo (heurística 8, IA).**
87 filas sin límite ni bulk actions; Salud de conexiones y Temas quedan al fondo (inalcanzables); nav de sección no sticky.
Fix: dashboard = resumen (5 pendientes + "Ver los 87 →" al calendario/vista filtrada, salud arriba con estado persistido, próximas 3). Bulk approve/reject en una vista dedicada.

**[P1-5] Errores del backend crudos y en inglés.**
Login mostró Pydantic verbatim: "value is not a valid email address: The part after the @-sign...". El patrón `err.detalle` → UI se repite en toda la app.
Fix: mapa de errores en `lib/api.ts` (status+error → mensaje en español); genérico amable como fallback.

**[P1-6] Calendario dominado por "Rechazado" y chips indistinguibles.**
La mayoría de filas visibles son rechazadas (histórico) mezcladas con el plan; tray "Pendientes sin horario" = 12+ chips truncados idénticos con badge "Pendiente" redundante; agendar solo por drag (sin alternativa por clic, inservible en móvil/teclado).
Fix: filtro de estados con "Rechazados" apagado por default (o atenuados), chips con más texto y sin badge, acción "Programar…" en el drawer con selector de slot.

**[P1-7] Configuración paraliza: Voz = 6 textareas vacíos sin guía; salud sin estado; zona horaria IANA a mano.**
Fix: placeholders con ejemplos reales por campo, texto de ayuda de 1 línea, select de zona horaria (opciones MX comunes), guardar y probar la conexión mostrando el último resultado persistido.

**[P2-8] Identidad y pulido**: tema zinc 100% acromático (cero color de marca), sin logo/branding en login, login sin aviso "solo por invitación" ni opción de corregir correo, "Lunes, 17 De Agosto" (De capitalizado), triple encabezado redundante, empty states que no enseñan.

## Persona red flags

**Colaborador editor no técnico (persona core)**: entra al dashboard → 87 filas; los badges rojos de su marca dicen `IG_ACCESS_TOKEN`; cree que el sistema está roto. Quiere mover un post de día: la única vía es drag-drop que no descubre. Aprueba por accidente desde la lista: no hay confirm ni undo → pánico. **Abandona y le escribe a Ricardo por WhatsApp.**

**Manager de marca nueva**: configura su marca → Voz: 6 cajas vacías sin ejemplos → escribe dos líneas con culpa. Estilos → "JSON crudo" → cierra la pestaña. Zona horaria → no sabe el formato IANA. **Configura 20% y el contenido sale genérico.**

**Ricardo (admin power user)**: todo le funciona porque él ES el traductor de la jerga; sin bulk actions pierde 10 min diarios aprobando de a uno; sin filtro de rechazados el calendario no le sirve para ver el plan.

## Observaciones menores

- `prueba_web` con nombre "Prueba" y `@prueba` aparece en producción para todos.
- Biblioteca no explica su propósito ni diferencia con el calendario (solo carruseles).
- "Todos los estados" del filtro de Biblioteca correcto; falta lo mismo en calendario.
- Horarios: solo lectura está bien para v1, pero el aviso debe hablar de producto ("Pídele a Ricardo cambiarlos"), no de endpoints.
- Wizard no ofrece los "Temas sugeridos" del dashboard como punto de partida.
- Aviso dev "Modo desarrollo: el link se imprime en el log de la API" visible en login dev (correcto que sea solo dev).

## Preguntas provocadoras

- ¿El dashboard debería SER la bandeja de aprobación (una sola cosa bien) y el resto vivir en Calendario?
- Si "Aprobar" publica, ¿debería llamarse "Aprobar" o "Programar publicación"?
- ¿Qué pasaría si Estilos solo mostrara 3 controles (colores + tipografía) y el resto viviera con Ricardo?
