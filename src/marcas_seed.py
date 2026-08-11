"""Seeds de perfil de marca: gdlscene brandeado + Pensión+ (tulanaya).

Idempotente y respetuoso: solo escribe campos de perfil que estén vacíos —
lo editado a mano (GUI) nunca se pisa. CLI: python -m src.marcas_seed
"""
from __future__ import annotations

import json

from src import db

ESTILOS_GDLSCENE = {
    "gdlscene_clasico": {
        "texto": "blanco", "fondo": "verde", "background_opacity": 0.35,
        "chrome": {"handle": "@gdlscene", "logo": None},
        "roles": {
            "hook": {"font": "Anton-Regular", "font_size": "extra_large",
                     "text_style": "background", "text_vertical_anchor": "center"},
            "punto": {"font": "Tinos-Bold", "font_size": "large",
                      "text_style": "background", "text_vertical_anchor": "center"},
            "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                    "text_style": "background", "text_vertical_anchor": "bottom"},
        },
    },
}

ESTILOS_PENSIONMAS = {
    "pensionmas": {
        "texto": "blanco", "fondo": "navy", "background_opacity": 0.3,
        "chrome": {"handle": "@pensionmas", "logo": None},
        "roles": {
            "hook": {"font": "Erode-Bold", "font_size": "extra_large",
                     "text_style": "background", "text_vertical_anchor": "center"},
            "punto": {"font": "Erode-Semibold", "font_size": "large",
                      "text_style": "background", "text_vertical_anchor": "center"},
            "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                    "text_style": "background", "text_vertical_anchor": "bottom"},
        },
    },
}

VOZ_PENSIONMAS = (
    "Marca: Pensión+ (pensionmas.com.mx) — asesoría y acompañamiento para el "
    "retiro parcial por desempleo de AFORE, cambios y mejora de afore. "
    "Audiencia: personas en México de 40 a 60 años, de ciudad, sin empleo, que "
    "necesitan liquidez; no son expertos financieros y desconfían de gestores. "
    "TONO: confiable, claro, cercano — un asesor serio que habla de frente. "
    "Español mexicano llano ('tu dinero', 'tu trámite'), SIN urgencia "
    "artificial, SIN letras chiquitas. "
    "REGLAS LEGALES OBLIGATORIAS: los montos SIEMPRE se llaman 'estimados'; "
    "NUNCA prometer resultados ni cantidades; el trámite ante la AFORE es "
    "personal y gratuito (nosotros asesoramos y acompañamos); honorarios "
    "visibles, nunca cobros por adelantado. Nada de 'dinero YA', contadores "
    "ni presión. "
    "IMÁGENES: personas reales de 40-60 años de ciudad mexicana, situaciones "
    "cotidianas (hogar, celular, papeles), luz cálida; NUNCA stock corporativo "
    "gringo ni oficinas genéricas."
)

# (campo de accounts, valor a sembrar) — solo se escribe si el campo está vacío.
_PERFIL_PENSIONMAS = {
    "voz": VOZ_PENSIONMAS,
    "fuentes_imagen": json.dumps(["pinterest", "pexels"]),
    "formatos": json.dumps(["libre", "listicle"]),
    "estilos_json": json.dumps(ESTILOS_PENSIONMAS, ensure_ascii=False),
    "posting_slots": "10:00,18:00",
}

_PERFIL_GDLSCENE = {
    "fuentes_imagen": json.dumps(["banco", "covers", "pexels"]),
    "estilos_json": json.dumps(ESTILOS_GDLSCENE, ensure_ascii=False),
}


def _completar(cx, account_id: int, perfil: dict) -> None:
    fila = db.get(cx, "accounts", account_id)
    faltantes = {k: v for k, v in perfil.items() if not (fila.get(k) or "").strip()}
    if faltantes:
        db.update(cx, "accounts", account_id, **faltantes)


def sembrar(cx) -> None:
    filas = db.rows(cx, "SELECT id, slug FROM accounts")
    por_slug = {f["slug"]: f["id"] for f in filas}
    if "gdlscene" in por_slug:
        _completar(cx, por_slug["gdlscene"], _PERFIL_GDLSCENE)
    if "pensionmas" not in por_slug:
        por_slug["pensionmas"] = db.insert(
            cx, "accounts", slug="pensionmas", ig_handle="@pensionmas",
            nombre="Pensión+", ciudad="CDMX", color_marca="#2F52D9", activa=1)
    _completar(cx, por_slug["pensionmas"], _PERFIL_PENSIONMAS)
    print("Seeds de marca aplicados (gdlscene + pensionmas).")


if __name__ == "__main__":
    cx = db.connect()
    try:
        db.init_db(cx)
        sembrar(cx)
    finally:
        cx.close()
