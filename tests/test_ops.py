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


@pytest.mark.parametrize("malas", [[{"op": "del"}], [{"op": "mover", "capa": "t"}],
                                   [{"op": "add", "capa": {"id": "n", "tipo": "shape"},
                                     "indice": "0"}]])
def test_solo_python(malas):
    with pytest.raises(ops.OpInvalida):
        ops.aplicar({"v": 2, "capas": [{"id": "t", "tipo": "text"}]}, malas)


def _esc():
    return {"v": 2, "capas": [{"id": "t", "tipo": "text", "estilo": {"color": "#000"}},
                              {"id": "g", "tipo": "group", "hijos": ["t"]}]}


@pytest.mark.parametrize("malas", [
    [{"op": ["set"]}],
    [{"op": {"a": 1}}],
    [{"op": "set", "capa": "t", "ruta": "x"}],
    [{"op": "set", "capa": "g", "ruta": "hijos", "valor": "t"}],
    [{"op": "set", "capa": "g", "ruta": "hijos", "valor": [1]}],
    [{"op": "set", "capa": "g", "ruta": "hijos", "valor": None}],
    [{"op": "add", "capa": {"id": "n", "tipo": "shape"}, "indice": None}],
    [{"op": "add", "capa": {"id": "n", "tipo": "shape"}, "indice": 1.5}],
    [{"op": "add", "capa": {"id": "n", "tipo": "shape"}, "indice": True}],
    [{"op": "del", "capa": ["t"]}],
    [{"op": "set", "capa": ["t"], "ruta": "x", "valor": 1}],
])
def test_malformadas_son_op_invalida(malas):
    esc = _esc()
    with pytest.raises(ops.OpInvalida):
        ops.aplicar(esc, malas)
    assert esc == _esc()


@pytest.mark.parametrize("escena", [{"v": 2}, {"v": 2, "capas": None}, {"v": 2, "capas": {}}])
def test_capas_no_lista(escena):
    with pytest.raises(ops.OpInvalida):
        ops.aplicar(escena, [])


def test_capas_con_elemento_no_dict_es_op_invalida():
    with pytest.raises(ops.OpInvalida):
        ops.aplicar({"v": 2, "capas": ["x"]}, [{"op": "del", "capa": "t"}])


def test_estilo_id_permitido():
    out = ops.aplicar(_esc(), [{"op": "set", "capa": "t", "ruta": "estilo.id", "valor": "z"}])
    assert out["capas"][0]["estilo"]["id"] == "z"


def test_set_hijos_lista_de_str_ok():
    out = ops.aplicar(_esc(), [{"op": "set", "capa": "g", "ruta": "hijos", "valor": []}])
    assert out["capas"][1]["hijos"] == []


def test_add_copia_profunda():
    capa = {"id": "n", "tipo": "shape", "estilo": {"fill": "#fff"}}
    out = ops.aplicar(_esc(), [{"op": "add", "capa": capa}])
    capa["estilo"]["fill"] = "#000"
    assert out["capas"][-1]["estilo"]["fill"] == "#fff"


def test_intermedio_null_se_crea():
    esc = {"v": 2, "capas": [{"id": "t", "tipo": "text", "estilo": None}]}
    out = ops.aplicar(esc, [{"op": "set", "capa": "t", "ruta": "estilo.color", "valor": "#111"}])
    assert out["capas"][0]["estilo"] == {"color": "#111"}


@pytest.mark.parametrize("indice,esperado", [(-3, 0), (0, 0), (1, 1), (99, 2)])
def test_indice_entero_se_acota(indice, esperado):
    out = ops.aplicar(_esc(), [{"op": "add", "capa": {"id": "n", "tipo": "shape"}, "indice": indice}])
    assert [c["id"] for c in out["capas"]].index("n") == esperado
