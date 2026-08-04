"""Catálogo de foros canónicos: resuelve el texto libre de `events.lugar`.

`events.lugar` lo extrae un LLM del OCR y del caption, así que el mismo foro
llega escrito de media docena de formas: "Staditche", "@staditche",
"Staditche (Espacio Cultural)", "HAKE AL REY", "REY". Sin una identidad estable,
dos flyers del mismo evento salen como dos slides distintos en la agenda.

El diseño separa dos cosas a propósito:

- `normalizar()` barre lo MECÁNICO (mayúsculas, arrobas, paréntesis, acentos,
  prefijos y sufijos de tipo de local). Es pura y determinista.
- La tabla `venue_alias` captura lo que la normalización NO puede: "REY" es un
  OCR truncado de "Hake Al Rey" y ninguna regla de texto razonable las une sin
  unir también cosas que no debe. Eso se resuelve UNA vez por alias, a mano o
  con el LLM de la siembra, y queda resuelto para siempre.

La resolución en caliente es una búsqueda exacta: sin LLM, sin fuzzy, mismo
resultado siempre y auditable.
"""
from __future__ import annotations

import difflib
import re
import unicodedata

from src import db

# Palabras de "tipo de local" que no distinguen un foro de otro. Se quita como
# máximo UNA al inicio y UNA al final: "Foro Sala Diana" es "sala diana", no
# "diana" — encadenar borrados fusionaría lugares distintos.
_GENERICOS = (
    "centro cultural", "espacio cultural", "concert room", "concert hall",
    "el foro", "foro", "salon", "sala", "bar", "pub",
)

# Artículos españoles. Si después de podar genéricos queda solo un artículo,
# conservamos el texto original: "El Foro" → "el foro", no "el".
_ARTICULOS = ("el", "la", "los", "las")


def normalizar(s: str | None) -> str:
    """Clave de comparación de un lugar. PURA.

    Cadena vacía significa "no hay lugar" — nunca "lugar irreconocible".
    """
    if not s:
        return ""
    # Paréntesis y su contenido: "Staditche (Espacio Cultural)" → "Staditche".
    s = re.sub(r"\([^)]*\)", " ", s)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return ""

    completo = s  # antes de podar genéricos, por si el lugar ES un genérico
    for pref in _GENERICOS:  # como máximo UN prefijo
        if s.startswith(pref + " "):
            s = s[len(pref) + 1:].strip()
            break
    for suf in _GENERICOS:  # como máximo UN sufijo
        if s.endswith(" " + suf):
            s = s[: -(len(suf) + 1)].strip()
            break
    # Si el lugar era SOLO una palabra genérica ("Foro"), conservamos el texto:
    # "" está reservado para "no hay lugar" y confundir ambos casos haría que
    # todos los eventos sin lugar se fusionaran entre sí.
    # También si el resultado es solo un artículo ("El Foro" → "el"), conservamos.
    return s if s and s not in _ARTICULOS else completo


def sugerencias(texto: str, candidatos: list[tuple[int, str]],
                tope: int = 3) -> list[tuple[int, str, float]]:
    """(venue_id, nombre, score) de los foros más parecidos. PURA.

    Para la cola de curación de la GUI. `difflib` en vez de LLM: es instantáneo,
    gratis y determinista, y aquí solo necesitamos ORDENAR candidatos para que
    Ricardo elija — no acertar solo.
    """
    clave = normalizar(texto)
    puntuadas = [
        (vid, nombre, difflib.SequenceMatcher(None, clave, normalizar(nombre)).ratio())
        for vid, nombre in candidatos
    ]
    puntuadas.sort(key=lambda t: (-t[2], t[0]))
    return puntuadas[:tope]


def resolver(cx, lugar: str | None) -> int | None:
    """venue_id del lugar, o None si no hay alias registrado. SOLO LECTURA.

    Separada de `registrar_desconocido` a propósito: una función que consulta
    no debe escribir, y quien llama decide si quiere dejar rastro del fallo.
    """
    clave = normalizar(lugar)
    if not clave:
        return None
    filas = db.rows(cx, "SELECT venue_id FROM venue_alias WHERE alias_norm = ?", (clave,))
    return filas[0]["venue_id"] if filas else None


def registrar_desconocido(cx, lugar: str) -> int | None:
    """Deja el alias en la cola de curación. Devuelve su id (None si vacío).

    Idempotente: si el alias ya existe —resuelto, huérfano o marcado basura—
    devuelve el id existente sin tocarlo. Eso evita que un lugar descartado
    como 'no es un lugar' reaparezca en la cola cada vez que pasa un flyer.

    origen='visto': el DEFAULT de la columna. No es 'llm' porque este alias
    solo apareció en un flyer y nadie lo ha curado — 'llm' queda reservado
    para lo que proponga la siembra automática.
    """
    clave = normalizar(lugar)
    if not clave:
        return None
    filas = db.rows(cx, "SELECT id FROM venue_alias WHERE alias_norm = ?", (clave,))
    if filas:
        return int(filas[0]["id"])
    return db.insert(cx, "venue_alias", venue_id=None, alias_norm=clave,
                     alias_visto=lugar, origen="visto")


def origen_alias(cx, texto: str | None) -> str | None:
    """Origen del alias registrado para ese texto, o None si no hay alias.

    Para que quien vaya a escribir pueda preguntar ANTES si el alias está
    curado (y no gastar tokens del LLM en algo ya decidido).
    """
    clave = normalizar(texto)
    if not clave:
        return None
    filas = db.rows(cx, "SELECT origen FROM venue_alias WHERE alias_norm = ?", (clave,))
    return filas[0]["origen"] if filas else None


def upsert_alias(cx, venue_id: int | None, texto: str, *, origen: str,
                 protegidos: tuple[str, ...] = ()) -> int | None:
    """ÚNICO upsert de `venue_alias`. Devuelve el id, o None si no escribió.

    Antes había tres copias de este upsert con tres políticas distintas de
    "a quién no piso" (ninguna en la curación manual, solo 'manual' en la
    siembra desde bands, 'manual'+'semilla' en la siembra del LLM). Esa
    divergencia era el bug: 'no_es_lugar' no estaba en ninguna lista, así que
    el batch revivía lo que Ricardo ya había descartado y lo ligaba a un foro
    real — dos eventos distintos fusionados en la agenda, uno desaparecido.

    La política va explícita en `protegidos` en vez de estar hardcodeada, para
    que agregar un origen curado sea una línea en el llamador y no otra copia.
    """
    clave = normalizar(texto)
    if not clave:
        return None
    filas = db.rows(cx, "SELECT id, origen FROM venue_alias WHERE alias_norm = ?", (clave,))
    if filas:
        if filas[0]["origen"] in protegidos:
            return None
        aid = int(filas[0]["id"])
        db.update(cx, "venue_alias", aid, venue_id=venue_id, origen=origen)
        return aid
    return db.insert(cx, "venue_alias", venue_id=venue_id, alias_norm=clave,
                     alias_visto=texto, origen=origen)


def asignar_alias(cx, venue_id: int, texto: str) -> int | None:
    """Liga un texto a un foro. Curación manual: gana sobre lo que hubiera.

    `protegidos=()` a propósito: un humano decidiendo en la GUI pisa cualquier
    origen, incluido otro 'manual' anterior. None solo si el texto no
    normaliza a nada (no había alias que escribir).
    """
    return upsert_alias(cx, venue_id, texto, origen="manual")


def desasignar_alias(cx, alias_id: int) -> None:
    """Devuelve un alias mal asignado a la cola de huérfanos.

    origen='manual' con venue_id NULL: fue una decisión humana, así que el
    batch tampoco la pisa. Sin esto un error del LLM (p.ej. meter 'C3 Stage' y
    'C3 Rooftop' en el mismo grupo) no tenía arreglo desde la interfaz.
    """
    db.update(cx, "venue_alias", alias_id, venue_id=None, origen="manual")


def marcar_no_es_lugar(cx, alias_id: int) -> None:
    """Basura (nombre de banda, dirección): sale de la cola pero NO se borra,
    para que el mismo texto no vuelva a entrar en la próxima corrida."""
    db.update(cx, "venue_alias", alias_id, venue_id=None, origen="no_es_lugar")


def fusionar(cx, dst_id: int, src_id: int) -> None:
    """Absorbe src en dst: mueve alias y reapunta events antes de borrar.

    Nunca deja `events.venue_id` colgando (no hay FK que lo cuide).
    """
    if dst_id == src_id:
        return
    cx.execute("UPDATE venue_alias SET venue_id = ? WHERE venue_id = ?", (dst_id, src_id))
    cx.execute("UPDATE events SET venue_id = ? WHERE venue_id = ?", (dst_id, src_id))
    cx.execute("DELETE FROM venues WHERE id = ?", (src_id,))
    cx.commit()


def huerfanos(cx) -> list[dict]:
    """Alias pendientes de curar: sin foro y sin marcar como basura."""
    return db.rows(cx, """
        SELECT * FROM venue_alias
         WHERE venue_id IS NULL AND origen != 'no_es_lugar'
         ORDER BY created_at, id
    """)
