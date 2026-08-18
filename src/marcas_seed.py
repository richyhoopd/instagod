"""Seeds de perfil de marca: gdlscene brandeado + Pensión+ (tulanaya) +
Melaque West Coast Real Estate (@melaquecapital, MWRS/brand).

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

ESTILOS_MELAQUECAPITAL = {
    "melaquecapital": {
        # El verde ocupa la superficie; el latón es el único acento; nunca
        # negro sobre foto (caja y overlay en olivo). Marcellus tiene un solo
        # peso: la jerarquía la hace el tamaño.
        "texto": "hueso", "fondo": "olivo", "background_opacity": 0.45,
        "caja": "olivo", "overlay": "olivo",
        "chrome": {"handle": "@melaquecapital",
                   "logo": "data/brands/melaquecapital/mark.svg",
                   "font": "Archivo"},
        "roles": {
            "hook": {"font": "Marcellus", "font_size": "extra_large",
                     "text_style": "background", "text_vertical_anchor": "center"},
            "punto": {"font": "Marcellus", "font_size": "large",
                      "text_style": "background", "text_vertical_anchor": "center"},
            "cta": {"font": "Archivo", "font_size": "medium",
                    "text_style": "background", "text_vertical_anchor": "bottom"},
        },
    },
}

VOZ_MELAQUECAPITAL = (
    "Marca: Melaque West Coast Real Estate (@melaquecapital, "
    "melaquewcrealestate.com) — bienes raíces en Melaque, Barra de Navidad, "
    "Cuastecomate y la Costalegre de Jalisco; también lotes en Sayula (Los "
    "Olivos). Lo que se vende es TRANQUILIDAD LEGAL en una zona donde comprar "
    "mal es fácil. "
    "Audiencia: mayores de 55, mexicanos y extranjeros (muchos leen en inglés), "
    "que buscan casa de playa o inversión con certeza jurídica. "
    "TONO: informativo y concreto. Frases cortas, cifras exactas. Di el "
    "régimen legal cuando lo sepas (ejido, escriturada, fideicomiso): es la "
    "información que nadie más publica. "
    "PROHIBIDO: 'paraíso', 'oportunidad única', 'el sueño de tu vida', emojis "
    "de fuego, cuentas regresivas falsas, urgencia artificial. "
    "PRECIOS: casas en USD, lotes en pesos, SIEMPRE con la moneda escrita; "
    "no inventes cifras — si no hay precio confirmado en el contexto, no lo "
    "menciones. Una sola acción por pieza (WhatsApp o el sitio, no ambos). "
    "IDIOMA: español en la imagen; si el pie va bilingüe, inglés en el pie, "
    "nunca dos lenguas apiladas en el mismo slide. "
    "IMÁGENES: playa, bahía, pangas, muelle, casas y lotes de la costa de "
    "Jalisco a sangre, recorte vertical, luz natural; SIN gente reconocible "
    "(nada de personas de stock), sin turquesa decorativo ni fondos crema."
)

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

_PERFIL_MELAQUECAPITAL = {
    "voz": VOZ_MELAQUECAPITAL,
    # carpeta = data/brands/melaquecapital/fotos (symlink a MWRS/public/img):
    # banco propio primero, stock solo de respaldo.
    "fuentes_imagen": json.dumps(["carpeta", "pexels", "pinterest"]),
    "formatos": json.dumps(["listicle", "libre"]),
    "estilos_json": json.dumps(ESTILOS_MELAQUECAPITAL, ensure_ascii=False),
    "logo_path": "data/brands/melaquecapital/mark.svg",
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
    if "melaquecapital" not in por_slug:
        por_slug["melaquecapital"] = db.insert(
            cx, "accounts", slug="melaquecapital", ig_handle="@melaquecapital",
            nombre="Melaque West Coast Real Estate", ciudad="Melaque",
            color_marca="#223124", activa=1)
    _completar(cx, por_slug["melaquecapital"], _PERFIL_MELAQUECAPITAL)
    print("Seeds de marca aplicados (gdlscene + pensionmas + melaquecapital).")


if __name__ == "__main__":
    cx = db.connect()
    try:
        db.init_db(cx)
        sembrar(cx)
    finally:
        cx.close()
