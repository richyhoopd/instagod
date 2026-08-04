"""Siembra única del catálogo de foros.

Orden deliberado, de lo barato y seguro a lo caro e incierto:

1. Los foros y eventos que Ricardo YA sigue (`bands` tipo foro/evento) entran
   como venues con su nombre y su handle de alias. Es el catálogo gratis.
2. Los `events.lugar` distintos se agrupan con `venues.normalizar`, que colapsa
   mayúsculas, arrobas, paréntesis y prefijos sin ayuda de nadie.
3. Solo lo que sigue ambiguo va al LLM, en UNA llamada.
4. Lo que el LLM no agrupa queda huérfano para curación en la GUI.

Idempotente y respetuoso de lo curado: un alias con origen='manual' (curación a
mano) o 'semilla' (cuenta que Ricardo ya sigue) no lo pisa el batch — ambos son
igual de confiables, ninguno es una adivinanza del LLM ni del OCR.
"""
from __future__ import annotations

from typing import Any, Callable

import config
from src import db, venues

_TIPOS_VENUE = ("foro", "evento")

# Orígenes que el batch NUNCA pisa: los tres salen de una decisión humana o de
# una cuenta que Ricardo ya sigue, ninguno es una adivinanza del LLM ni del OCR.
# 'no_es_lugar' incluido: sin él, la siembra revivía lo descartado y lo ligaba a
# un foro real, fusionando en la agenda dos eventos que no tienen que ver.
_PROTEGIDOS = ("manual", "semilla", "no_es_lugar")

_PROMPT = """Eres un asistente que ordena nombres de foros y venues de la escena
musical de Guadalajara. Te doy una lista de textos crudos extraídos por OCR de
carteles de conciertos. Agrupa los que se refieran al MISMO lugar y dale a cada
grupo un nombre canónico limpio.

Reglas:
- Salas distintas del mismo edificio son lugares DISTINTOS (C3 Stage y C3
  Rooftop van separados).
- Si un texto no es un lugar (nombre de banda, dirección suelta, basura de OCR),
  NO lo incluyas en ningún grupo.
- Un texto que no puedas asignar con confianza, déjalo fuera.

Devuelve SOLO un objeto JSON con esta forma exacta (la lista SIEMPRE va dentro
de la clave "grupos", nunca suelta en la raíz):
{"grupos": [{"canonico": "Nombre Limpio", "alias": ["texto1", "texto2"]}]}

Textos:
"""


def _asignar_alias_semilla(cx, venue_id: int, texto: str) -> None:
    """Liga un texto a un foro con origen='semilla' (cuenta que ya se sigue).

    No usa `venues.asignar_alias`: ese es el contrato de curación MANUAL (un
    humano decidiendo en la GUI, que pisa cualquier cosa). Este alias es
    automático, así que va con su propio origen y respeta lo curado a mano.
    """
    venues.upsert_alias(cx, venue_id, texto, origen="semilla",
                        protegidos=("manual", "no_es_lugar"))


def sembrar_desde_bands(cx) -> int:
    """Crea venues desde las cuentas de tipo foro/evento. Devuelve cuántos creó."""
    creados = 0
    marcas = ",".join("?" * len(_TIPOS_VENUE))
    for b in db.rows(cx, f"""
        SELECT nombre, ig_handle, ciudad FROM bands
         WHERE tipo IN ({marcas}) AND activa = 1 ORDER BY id
    """, _TIPOS_VENUE):
        if venues.resolver(cx, b["nombre"]) is not None:
            continue
        vid = db.insert(cx, "venues", nombre=b["nombre"], ciudad=b["ciudad"],
                        ig_handle=b["ig_handle"])
        creados += 1
        for texto in (b["nombre"], b["ig_handle"]):
            if texto and venues.normalizar(texto):
                _asignar_alias_semilla(cx, vid, texto)
    return creados


def lugares_distintos(cx) -> list[str]:
    """Textos crudos distintos de `events.lugar`, en orden estable."""
    return [r["lugar"] for r in db.rows(cx, """
        SELECT DISTINCT lugar FROM events
         WHERE lugar IS NOT NULL AND trim(lugar) != ''
         ORDER BY lugar
    """)]


def agrupar_mecanico(lugares: list[str]) -> dict[str, list[str]]:
    """Clave normalizada → textos crudos que caen en ella. PURA."""
    grupos: dict[str, list[str]] = {}
    for texto in lugares:
        clave = venues.normalizar(texto)
        if clave:
            grupos.setdefault(clave, []).append(texto)
    return grupos


def _llm_agrupar(pendientes: list[str]) -> list[dict[str, Any]]:
    """UNA llamada a DeepSeek con todos los textos ambiguos.

    El prompt pide un OBJETO `{"grupos": [...]}`, no un array suelto: el único
    parser del proyecto es `parse_events.extraer_json`, que busca `\\{.*\\}` y
    exige un dict. Un array de N objetos lo parsea como basura (`{...},{...}`
    sin corchetes → None) y uno de un solo objeto pierde todos los grupos menos
    el primero. Pedir el array haría que esta función devolviera [] SIEMPRE, en
    silencio, indistinguible de "el LLM no agrupó nada".

    Por eso también avisa a gritos si no obtiene grupos habiendo pendientes: un
    cero silencioso aquí es un feature muerto que nadie nota.
    """
    if not pendientes:
        return []
    from openai import OpenAI

    from src.parse_events import extraer_json
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[{"role": "user", "content": _PROMPT + "\n".join(pendientes)}],
        response_format={"type": "json_object"},
        temperature=0,  # agrupación determinista, nada de creatividad
        # ~50 grupos de salida: un truncamiento rompe el JSON y cae en el mismo
        # agujero silencioso que este arreglo cierra.
        max_tokens=4000,
    )
    crudo = resp.choices[0].message.content or ""
    data = extraer_json(crudo)
    grupos = data.get("grupos") if isinstance(data, dict) else None
    if not isinstance(grupos, list):
        print(f"venues_seed: ADVERTENCIA — la respuesta del LLM no trae 'grupos' "
              f"parseables; {len(pendientes)} texto(s) se quedan sin agrupar. "
              f"Respuesta cruda: {crudo[:300]!r}")
        return []
    if not grupos:
        print(f"venues_seed: ADVERTENCIA — el LLM no agrupó ninguno de los "
              f"{len(pendientes)} texto(s) pendientes.")
    return grupos


def _grupo_valido(grupo: Any) -> tuple[str, list[str]] | None:
    """Valida la forma de una propuesta del LLM. None si está mal formada.

    El LLM no siempre respeta el formato pedido en el prompt. Tres formas
    rotas que sí llegan en la práctica:

    - El grupo no es un objeto (el LLM devolvió una lista de strings suelta).
    - 'canonico' no es texto (lista, dict, número).
    - 'alias' es una cadena suelta en vez de una lista — "alias": "REY" en
      vez de ["REY"]. Este es el peligroso: iterar una cadena carácter por
      carácter produce alias de una sola letra ('r', 'e', 'y') que se
      insertarían como reales y fusionarían cualquier lugar cuyo nombre
      normalice a una sola letra con el venue equivocado. Descartamos el
      grupo ENTERO en vez de envolver la cadena en una lista de un elemento:
      no hay forma de distinguir "el LLM quiso un solo alias" de "el LLM
      olvidó los corchetes y esa cadena en realidad son varios alias
      pegados" — perder el grupo (queda pendiente para curación manual en la
      GUI) es más honesto que adivinar la intención.
    """
    if not isinstance(grupo, dict):
        return None
    canonico = grupo.get("canonico")
    if not isinstance(canonico, str) or not canonico.strip():
        return None
    alias_raw = grupo.get("alias")
    if not isinstance(alias_raw, list):
        return None
    alias = [a.strip() for a in alias_raw if isinstance(a, str) and a.strip()]
    if not alias:
        return None
    return canonico.strip(), alias


def sembrar(cx, *, _llm: Callable[[list[str]], list[dict]] | None = None) -> dict:
    """Siembra completa.

    Devuelve {venues, alias, huerfanos, pendientes_llm, grupos_invalidos}.
    """
    llm = _llm or _llm_agrupar
    db.init_db(cx)
    creados = sembrar_desde_bands(cx)

    grupos = agrupar_mecanico(lugares_distintos(cx))
    # Lo que ya resuelve contra el catálogo no se toca; el resto es "pendiente".
    # Un solo texto representativo por clave normalizada (no las N variantes de
    # escritura que ya fusionó `agrupar_mecanico`): son la misma clave, así que
    # ya son la misma info para el LLM — mandarlas todas sería gastar tokens
    # sin darle nada nuevo con qué decidir.
    # Los alias ya curados (manual/semilla/no_es_lugar) quedan fuera aunque no
    # resuelvan a ningún foro: preguntarle al LLM por algo que un humano ya
    # descartó o desasignó es gastar tokens en una propuesta que el upsert va
    # a rechazar de todos modos.
    pendientes = [textos[0] for clave, textos in grupos.items()
                  if venues.resolver(cx, textos[0]) is None
                  and venues.origen_alias(cx, textos[0]) not in _PROTEGIDOS]

    alias_nuevos = 0
    grupos_invalidos = 0
    for grupo in llm(pendientes):
        valido = _grupo_valido(grupo)
        if valido is None:
            grupos_invalidos += 1
            print(f"venues_seed: grupo del LLM con forma inválida, se descarta: {grupo!r}")
            continue
        canonico, alias = valido
        vid = venues.resolver(cx, canonico)
        if vid is None:
            vid = db.insert(cx, "venues", nombre=canonico)
            creados += 1
        for texto in [canonico, *alias]:
            if venues.upsert_alias(cx, vid, texto, origen="llm",
                                   protegidos=_PROTEGIDOS) is not None:
                alias_nuevos += 1

    # Lo que sigue sin resolver entra a la cola de curación.
    for clave, textos in grupos.items():
        if venues.resolver(cx, textos[0]) is None:
            venues.registrar_desconocido(cx, textos[0])
    cx.commit()
    return {"venues": creados, "alias": alias_nuevos,
            "huerfanos": len(venues.huerfanos(cx)),
            "pendientes_llm": len(pendientes),
            "grupos_invalidos": grupos_invalidos}


def backfill_eventos(cx) -> int:
    """Resuelve `venue_id` de todos los eventos con lugar. Devuelve cuántos.

    Lo que no resuelve entra a la cola de curación: así el catálogo crece con
    lo que de verdad aparece en los carteles, no con lo que alguien imagine.
    """
    resueltos = 0
    for e in db.rows(cx, """
        SELECT id, lugar FROM events
         WHERE lugar IS NOT NULL AND trim(lugar) != ''
    """):
        vid = venues.resolver(cx, e["lugar"])
        if vid is None:
            venues.registrar_desconocido(cx, e["lugar"])
            continue
        db.update(cx, "events", e["id"], venue_id=vid)
        resueltos += 1
    cx.commit()
    return resueltos


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Siembra del catálogo de foros")
    parser.add_argument("--solo-backfill", action="store_true",
                        help="no siembra: solo resuelve venue_id de los eventos")
    args = parser.parse_args()
    cx = db.connect()
    try:
        db.init_db(cx)
        if not args.solo_backfill:
            res = sembrar(cx)
            print(f"Siembra: {res['venues']} foro(s), {res['alias']} alias, "
                  f"{res['pendientes_llm']} al LLM")
        n = backfill_eventos(cx)
        print(f"Backfill: {n} evento(s) con foro resuelto · "
              f"{len(venues.huerfanos(cx))} alias por curar en /venues")
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido.")
    finally:
        cx.close()
