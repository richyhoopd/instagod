"""Genera un post simple real de dos marcas distintas, sin publicar.

Uso:
    cp ~/Work/personal/instagod/data/gdlscene.db /tmp/h2.db
    .venv/bin/python scripts/verificar_h2.py /tmp/h2.db

Llama al LLM de verdad y renderiza con Chromium de verdad. NO sube a
Instagram, NO sube a Cloudinary y NO toca la cola de publicación: las piezas
quedan en 'borrador'/'pendiente', listas para revisar y aprobar a mano en el
portal. Rechaza correr contra cualquier ruta bajo un directorio `data/`
(incluida la DB real del proyecto): solo trabaja sobre la copia que le pasas.

Es el criterio de aceptación del hito H2, tal como lo fija el spec: si esto
solo funciona para gdlscene, el hito no sirve. Por eso corre dos veces, una
para gdlscene (música) y otra para melaquecapital (inmobiliaria) — y si
alguna de las dos no tiene todavía una plantilla activa en la copia, este
script se la arma antes de generar, y lo dice en la salida.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from src import cola, db, marcas, plantillas, posts  # noqa: E402
from src.plantillas import contrato as _contrato  # noqa: E402
from src.seeds import plantillas_gdlscene  # noqa: E402

# Foto de muestra ya versionada en el repo: evita depender de la red (Pexels,
# Unsplash, etc.) para resolver una imagen. Es intencional pasarla como
# `imagen_manual`: esta verificación prueba el post simple, no la cascada de
# fuentes de imagen (eso ya tiene su propia cobertura en tests/test_posts.py).
IMG_MUESTRA = ROOT / "tests" / "fixtures" / "caras" / "dos_personas.jpg"

# Una sola marca musical de sobra en el catálogo (gdlscene); la prueba real
# del hito es que esto también funcione para algo que no tiene nada que ver
# con música.
_MARCAS_A_VERIFICAR = (
    ("gdlscene", "Line-up sorpresa de bandas emergentes en el foro de siempre"),
    ("melaquecapital", "Lote nuevo con escritura limpia en Barra de Navidad"),
)

_HTML_GENERICO = (
    "<!doctype html><html><head><style>\n"
    "  body { margin:0; }\n"
    "  .card { width:1080px; height:1350px; box-sizing:border-box; padding:96px;\n"
    "          background:{{ color_marca }}; color:#fff; font-family:sans-serif;\n"
    "          display:flex; flex-direction:column; justify-content:center; gap:40px; }\n"
    "  .card h1 { font-size:76px; line-height:1.15; margin:0; }\n"
    "  .card .handle { font-size:36px; opacity:.85; }\n"
    "</style></head><body>\n"
    "  <div class=\"card\">\n"
    "    <h1>{{ titular }}</h1>\n"
    "    <div class=\"handle\">{{ handle }}</div>\n"
    "  </div>\n"
    "  <script>window.__captionFitted = true;</script>\n"
    "</body></html>"
)


def _contrato_generico() -> dict[str, Any]:
    """Contrato mínimo: solo el núcleo base, sin extras. Vale para cualquier marca."""
    return {"aspecto": "4:5", "base": list(_contrato.CAMPOS_BASE), "extras": []}


def _rechazar_ruta_prod(ruta: Path) -> None:
    """Nunca sobre la DB real: solo copias fuera de cualquier carpeta `data/`."""
    resuelta = ruta.expanduser().resolve()
    partes = {p.lower() for p in resuelta.parts}
    if "data" in partes or str(resuelta).startswith("/opt/instagod"):
        print(f"🔴 Ruta rechazada: {resuelta}")
        print("   Este script nunca corre contra data/ ni contra /opt/instagod/.")
        print("   Copia la DB a /tmp y pasa esa ruta, ej.:")
        print("   cp ~/Work/personal/instagod/data/gdlscene.db /tmp/h2.db")
        raise SystemExit(1)


def _asegurar_plantilla(cx, marca) -> tuple[dict[str, Any], str | None]:
    """Primera plantilla activa de la marca. Si no hay ninguna, la arma.

    gdlscene: corre el seed de H1 (plantillas_gdlscene.sembrar), que migra
    las cuatro plantillas HTML reales del repo. Cualquier otra marca sin
    plantillas: se le crea una plantilla mínima genérica ahí mismo — esa es
    justo la prueba de que el sistema sirve para una marca nueva.
    """
    activas = plantillas.listar(cx, marca.id, estado="activa")
    if activas:
        return activas[0], None

    if marca.slug == "gdlscene":
        r = plantillas_gdlscene.sembrar(cx, marca.id)
        activas = plantillas.listar(cx, marca.id, estado="activa")
        if not activas:
            raise RuntimeError(
                "gdlscene sigue sin plantillas activas tras correr el seed de H1")
        nota = (f"gdlscene no tenía plantillas activas en esta copia de la DB: se "
                f"corrió plantillas_gdlscene.sembrar() (seed de H1), {r['creadas']} "
                f"nuevas / {r['existentes']} ya existentes.")
        return activas[0], nota

    tid = plantillas.crear(
        cx, marca.id, f"Genérica — {marca.nombre}", _HTML_GENERICO,
        _contrato_generico(),
        descripcion="Plantilla mínima creada por verificar_h2.py: prueba de que el "
                    "sistema sirve para una marca nueva sin nada preparado.",
        origen="manual",
    )
    plantillas.activar(cx, tid)
    nota = (f"{marca.slug} no tenía NINGUNA plantilla: se creó una plantilla mínima "
            "genérica (contrato = solo el núcleo CAMPOS_BASE, sin extras) para esta "
            "verificación. Es la prueba de que el sistema sirve para una marca nueva.")
    return plantillas.obtener(cx, tid), nota


def _verificar_fila(slug: str, fila: dict[str, Any], estado: str) -> list[str]:
    fallas = []
    if fila.get("tipo") != "post":
        fallas.append(f"{slug}: tipo={fila.get('tipo')!r}, se esperaba 'post'")
    if fila.get("origen") != "api":
        fallas.append(f"{slug}: origen={fila.get('origen')!r}, se esperaba 'api'")
    if fila.get("aprobacion") != "pendiente":
        fallas.append(
            f"{slug}: aprobacion={fila.get('aprobacion')!r}, se esperaba 'pendiente'")
    if fila.get("status") != "borrador":
        fallas.append(f"{slug}: status={fila.get('status')!r}, se esperaba 'borrador'")
    if estado != "pendiente":
        fallas.append(
            f"{slug}: cola.estado_de -> {estado!r}, se esperaba 'pendiente' "
            "(editable y aprobable desde el portal)")
    return fallas


def main(ruta: str) -> int:
    db_path = Path(ruta)
    _rechazar_ruta_prod(db_path)

    cx = db.connect(db_path)
    db.init_db(cx)

    # Nunca se sube nada de verdad (ni Cloudinary ni, por lo tanto, Instagram):
    # se captura la ruta local del PNG que YA renderizó Chromium para medirla
    # con PIL, y se devuelve una URL falsa que jamás sale a la red.
    capturado: dict[str, Path] = {}

    def _upload_falso(ruta_img: str, public_id: str | None = None) -> str:
        capturado["png"] = Path(ruta_img)
        return "https://verificacion-h2.local/no-se-sube-de-verdad.jpg"

    posts.host.upload = _upload_falso

    fallas: list[str] = []

    for slug, tema in _MARCAS_A_VERIFICAR:
        print(f"\n=== {slug} ===")
        try:
            marca = marcas.cargar(cx, slug)
        except Exception as exc:
            fallas.append(f"{slug}: no se pudo cargar la marca ({exc})")
            continue

        try:
            tpl, nota = _asegurar_plantilla(cx, marca)
        except Exception as exc:
            fallas.append(f"{slug}: no se pudo asegurar una plantilla ({exc})")
            continue

        if nota:
            print(f"  ⚠️  {nota}")
        print(f"  plantilla usada ...... #{tpl['id']} «{tpl['nombre']}» "
              f"(slug={tpl['slug']!r}, origen={tpl['origen']!r})")

        try:
            qid = posts.crear_post(
                cx, marca, template_id=tpl["id"], tema=tema,
                imagen_manual=str(IMG_MUESTRA),
            )
        except RuntimeError as exc:
            if "DEEPSEEK_API_KEY" in str(exc):
                print(f"🔴 {exc}")
                print("   Sin API key de DeepSeek no se puede verificar el generador "
                      "de campos. Configúrala en .env y vuelve a correr.")
                return 1
            fallas.append(f"{slug}: posts.crear_post falló: {exc}")
            continue
        except Exception as exc:
            fallas.append(f"{slug}: posts.crear_post falló: {exc}")
            continue

        png = capturado.get("png")
        dims = None
        if png is not None and png.exists():
            with Image.open(png) as im:
                dims = im.size

        fila = db.get(cx, "content_queue", qid)
        estado = cola.estado_de(fila)
        campos = json.loads(fila.get("campos_json") or "{}")

        print(f"  queue_id ............. {qid}")
        print(f"  PNG .................. {png}")
        print(f"  dimensiones (PIL) .... {dims}")
        print(f"  titular .............. {campos.get('titular')!r}")
        print(f"  tipo/origen/status ... {fila.get('tipo')}/{fila.get('origen')}/"
              f"{fila.get('status')}")
        print(f"  aprobacion ........... {fila.get('aprobacion')!r}")
        print(f"  cola.estado_de ....... {estado!r}")

        if png is None or not png.exists():
            fallas.append(f"{slug}: no se encontró el PNG renderizado (capturado={png})")
        elif dims is None or dims[0] < 100 or dims[1] < 100:
            fallas.append(f"{slug}: dimensiones sospechosas del PNG: {dims}")

        fallas += _verificar_fila(slug, fila, estado)

    if fallas:
        print("\n🔴 FALLAS:")
        for f in fallas:
            print(f"  - {f}")
        return 1

    print("\n🟢 H2 end-to-end: gdlscene y una marca no musical generaron un post "
          "válido, en 'borrador'/'pendiente', editable y aprobable desde el portal.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
