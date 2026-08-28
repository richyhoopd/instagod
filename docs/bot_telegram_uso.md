# Bot de Telegram — generar memes manualmente

Le mandas una **foto** al bot con los datos en la **descripción (caption)** de la foto. Todos los campos son opcionales.

## Sintaxis del caption

```
[plantilla:] banda, integrante, rol, tema  [@handles]
```

Los campos son **posicionales, separados por comas**. Puedes dejar uno vacío con coma doble (`,,`) o simplemente omitir los del final.

| Posición | Campo | Qué hace |
|---|---|---|
| prefijo `xxx:` | plantilla | Fuerza la plantilla del meme. Si no la pones, se elige al azar con pesos (clásica casi siempre). |
| 1 | banda | Nombre de la banda/artista |
| 2 | integrante | Nombre de la persona del meme |
| 3 | rol | Rol/instrumento (ej. "baterista", "vocalista") |
| 4 | tema | Semilla del chiste — guía al LLM sobre de qué va el headline |
| en cualquier parte | `@handle` | Menciones de IG: se quitan del texto del meme y se agregan al caption del post para etiquetar al artista. Puede haber varias. |

### Plantillas (prefijo)

| Escribes | Plantilla |
|---|---|
| `clasica:` / `clásica:` / `classic:` / `normal:` / `1:` | clásica |
| `verde:` / `green:` / `2:` | verde |
| `onion:` / `the onion:` / `3:` | onion |

## Ejemplos

```
Sgt. Papers, Memo, baterista
verde: Tropa Mágica, Beto, vocalista, se le olvidó la letra
onion: Clubz, , , tocaron 3 horas tarde @clubzmusic
2: Margaritas Podridas, Carolina, bajista @margaritaspodridas
, , , el público no llegó
```

- Caption vacío también funciona: el bot genera todo solo.
- `Clubz, , , tocaron tarde` → banda + tema, sin integrante ni rol.

## Álbum de 2 fotos (circulito)

Manda un **álbum de 2 fotos**: la foto **con caption** es la principal y la otra va al **inset redondo** (circulito) de la plantilla. Fotos extra se ignoran.

## Después de generar — botones

| Botón | Efecto |
|---|---|
| ✅ Aprobar | Sube a Cloudinary, agenda horario y escribe la fila en el Sheet |
| ❌ Rechazar | Descarta el meme |
| 🔄 Regenerar | Nuevo texto con el LLM (recuerda los rechazados para no repetirlos) |
| 🎨 Plantilla | Cicla la plantilla (clásica→verde→onion) **sin** regenerar el texto |

## Comandos por reply

Respondiendo (reply) a la foto que mandó el bot:

| Escribes | Efecto |
|---|---|
| `texto: <tu texto exacto>` | Usa ese texto tal cual como caption del meme, **sin LLM**, y recompone la imagen |
| `feedback: <guía>` | Regenera el texto con el LLM siguiendo tu indicación (ej. `feedback: más corto y sin nombrar la ciudad`) |

Referencias: `bot.py:97` (parse_caption), `bot.py:90` (alias), `bot.py:62` (replies), `bot.py:49` (álbum), `src/compose.py:46` (ciclo de plantillas).
