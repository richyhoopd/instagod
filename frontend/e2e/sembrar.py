"""Base de datos desechable para la e2e del editor.

Crea un usuario manager de gdlscene, su sesión y un diseño borrador v2 con
un texto sin vincular. Escribe lo que la e2e necesita en
e2e/.datos/sembrado.json. Se corre desde la raíz del worktree.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))

from src import db, plantillas, users  # noqa: E402
from src.plantillas.contrato import CAMPOS_BASE  # noqa: E402
from src.plantillas.escena import normalizar  # noqa: E402

DATOS = Path(__file__).resolve().parent / ".datos"


def main() -> None:
    ruta = Path(os.environ["DB_PATH"]).resolve()
    if DATOS not in ruta.parents:
        sys.exit(f"DB_PATH debe vivir en {DATOS}; llegó {ruta}")
    DATOS.mkdir(parents=True, exist_ok=True)
    for sufijo in ("", "-wal", "-shm"):
        Path(f"{ruta}{sufijo}").unlink(missing_ok=True)

    cx = db.connect(str(ruta))
    db.init_db(cx)
    uid = users.crear_usuario(cx, "e2e@instagod.test")
    users.asignar_marca(cx, uid, 1, "manager")
    token = users.crear_sesion(cx, uid)

    escena = normalizar(None, "4:5")
    texto = next((c for c in escena["capas"] if c["tipo"] == "text"), None)
    assert texto is not None, "normalizar(None, '4:5') no trae una capa de texto; ajusta el sembrador"
    texto.update(id="e2e_titulo", texto="Hola e2e", campo=None)
    texto.pop("resaltar", None)

    contrato = {"aspecto": "4:5", "base": list(CAMPOS_BASE), "extras": []}
    tid = plantillas.crear(cx, 1, "E2E", "", contrato, layout=escena)
    cx.commit()

    (DATOS / "sembrado.json").write_text(json.dumps({"token": token, "slug": "gdlscene", "id": tid}))
    print(f"sembrado: diseño {tid} en {ruta}")


if __name__ == "__main__":
    main()
