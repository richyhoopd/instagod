"""Ops sobre escenas v2. Misma semántica que `aplicarOps` en frontend/lib/escena.ts (plan 2).

El fixture `frontend/lib/__fixtures__/ops-casos.json` corre en pytest y en vitest:
si cambias algo aquí, cámbialo allá y agrega el caso al fixture en el mismo commit.
"""
from __future__ import annotations

import copy
from typing import Any

_INTOCABLES = {"id", "tipo"}
_PELIGROSAS = {"__proto__", "prototype", "constructor"}


class OpInvalida(ValueError):
    pass


def _capa(capas: list[dict], cid: Any) -> dict:
    for c in capas:
        if c.get("id") == cid:
            return c
    raise OpInvalida(f"no existe la capa {cid!r}")


def _set(capas: list[dict], op: dict) -> None:
    obj = _capa(capas, op.get("capa"))
    ruta = op.get("ruta")
    if not isinstance(ruta, str):
        raise OpInvalida("set necesita ruta")
    partes = ruta.split(".")
    if any(p == "" or p in _PELIGROSAS for p in partes):
        raise OpInvalida(f"ruta inválida: {ruta!r}")
    if len(partes) == 1 and partes[0] in _INTOCABLES:
        raise OpInvalida(f"{ruta!r} no se puede cambiar")
    for p in partes[:-1]:
        sig = obj.get(p)
        if sig is None:
            sig = obj[p] = {}
        elif not isinstance(sig, dict):
            raise OpInvalida(f"{p!r} no es un objeto en la capa {op.get('capa')!r}")
        obj = sig
    if "valor" not in op:
        raise OpInvalida("set necesita valor (usa null para asignar null)")
    valor = op["valor"]
    if ruta == "hijos" and not (isinstance(valor, list) and all(isinstance(h, str) for h in valor)):
        raise OpInvalida("hijos debe ser una lista de ids (str)")
    obj[partes[-1]] = copy.deepcopy(valor)


def _add(capas: list[dict], op: dict) -> None:
    capa = op.get("capa")
    if not isinstance(capa, dict):
        raise OpInvalida("add necesita una capa")
    if any(c.get("id") == capa.get("id") for c in capas):
        raise OpInvalida(f"ya existe la capa {capa.get('id')!r}")
    n = len(capas)
    if "indice" not in op:
        i = n
    else:
        indice = op["indice"]
        if isinstance(indice, bool) or not isinstance(indice, int):
            raise OpInvalida("indice debe ser un entero")
        i = min(max(indice, 0), n)
    capas.insert(i, copy.deepcopy(capa))


def _descendientes(capas: list[dict], cid: Any) -> set:
    por_id = {c.get("id"): c for c in capas}
    vistos: set = set()
    pila = [cid]
    while pila:
        c = por_id.get(pila.pop())
        if not c or c.get("tipo") != "group":
            continue
        for h in c.get("hijos") or []:
            if h in vistos or h == cid:
                continue
            vistos.add(h)
            pila.append(h)
    return vistos


def _del(capas: list[dict], op: dict) -> None:
    cid = op.get("capa")
    _capa(capas, cid)
    borrar = {cid} | _descendientes(capas, cid)
    cambio = True
    while cambio:  # un grupo sin hijos se borra también (el validador prohíbe hijos vacíos)
        cambio = False
        for c in capas:
            hijos = c.get("hijos") or []
            if (c.get("tipo") == "group" and c.get("id") not in borrar and hijos
                    and all(h in borrar for h in hijos)):
                borrar.add(c.get("id"))
                cambio = True
    capas[:] = [c for c in capas if c.get("id") not in borrar]
    for c in capas:
        if c.get("tipo") == "group":
            c["hijos"] = [h for h in c.get("hijos") or [] if h not in borrar]


_OPS = {"set": _set, "add": _add, "del": _del}


def aplicar(escena: dict, ops: list[dict]) -> dict:
    """Copia de `escena` con `ops` aplicadas. Atómica: la entrada nunca se muta."""
    if not isinstance(ops, list):
        raise OpInvalida("ops debe ser una lista")
    nueva = copy.deepcopy(escena)
    capas = nueva.get("capas") if isinstance(nueva, dict) else None
    if not isinstance(capas, list):
        raise OpInvalida("capas debe ser una lista")
    for op in ops:
        if not isinstance(op, dict) or not isinstance(op.get("op"), str) or op["op"] not in _OPS:
            raise OpInvalida(f"op desconocida: {op!r:.80}")
        try:
            _OPS[op["op"]](capas, op)
        except (TypeError, KeyError, AttributeError) as e:
            raise OpInvalida(f"op mal formada ({type(e).__name__}): {e}") from e
    return nueva
