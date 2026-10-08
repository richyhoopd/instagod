"""ops.aplicar contra el MISMO fixture que aplicarOps (plan 2, frontend/lib/__fixtures__)."""
import copy
import json
from pathlib import Path

import pytest

from src.plantillas import ops

FIXTURE = json.loads((Path(__file__).resolve().parents[1]
                      / "frontend/lib/__fixtures__/ops-casos.json").read_text())
BASE = FIXTURE["base"]


@pytest.mark.parametrize("caso", FIXTURE["casos"], ids=[c["nombre"] for c in FIXTURE["casos"]])
def test_casos_compartidos(caso):
    base = copy.deepcopy(BASE)
    if caso.get("error"):
        with pytest.raises(ops.OpInvalida):
            ops.aplicar(base, caso["ops"])
        assert base == BASE
        return
    out = ops.aplicar(base, caso["ops"])
    assert base == BASE
    assert [c["id"] for c in out["capas"]] == caso["ids"]
    cambiadas = caso.get("cambiadas") or {}
    previas = {c["id"]: c for c in BASE["capas"]}
    for c in out["capas"]:
        assert c == cambiadas.get(c["id"], previas.get(c["id"]))


def test_set_null_asigna_null_como_ts():
    out = ops.aplicar({"v": 2, "capas": [{"id": "t", "tipo": "text", "estilo": {"color": "#000"}}]},
                      [{"op": "set", "capa": "t", "ruta": "estilo.color", "valor": None}])
    assert out["capas"][0]["estilo"] == {"color": None}


def test_valor_se_copia():
    valor = {"a": [1]}
    out = ops.aplicar({"v": 2, "capas": [{"id": "t", "tipo": "text"}]},
                      [{"op": "set", "capa": "t", "ruta": "x", "valor": valor}])
    valor["a"].append(2)
    assert out["capas"][0]["x"] == {"a": [1]}


@pytest.mark.parametrize("malas", [{"op": "del"}, [{"op": "mover", "capa": "t"}],
                                   [{"op": "add", "capa": {"id": "n", "tipo": "shape"},
                                     "indice": "0"}]])
def test_solo_python(malas):
    with pytest.raises(ops.OpInvalida):
        ops.aplicar({"v": 2, "capas": [{"id": "t", "tipo": "text"}]}, malas)
