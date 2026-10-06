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
    # postal: la foto manda, texto sin caja; solido: navy casi pleno.
    "pension_postal": {
        "texto": "blanco", "fondo": "navy", "background_opacity": 0.3,
        "overlay": "navy",
        "chrome": {"handle": "@pensionmas", "logo": None},
        "roles": {
            "hook": {"font": "Erode-Bold", "font_size": "extra_large",
                     "text_style": "text", "text_vertical_anchor": "top",
                     "text_align": "left", "text_anchor": "left"},
            "punto": {"font": "Erode-Semibold", "font_size": "large",
                      "text_style": "text", "text_vertical_anchor": "center",
                      "text_align": "left", "text_anchor": "left"},
            "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                    "color": "oro", "text_style": "text",
                    "text_vertical_anchor": "bottom"},
        },
    },
    "pension_solido": {
        "texto": "blanco", "fondo": "navy", "background_opacity": 0.85,
        "overlay": "navy",
        "chrome": {"handle": "@pensionmas", "logo": None},
        "roles": {
            "hook": {"font": "Erode-Bold", "font_size": "extra_large",
                     "text_style": "text", "text_vertical_anchor": "center"},
            "punto": {"font": "Erode-Semibold", "font_size": "large",
                      "text_style": "text", "text_vertical_anchor": "center"},
            "cta": {"font": "Poppins-SemiBold", "font_size": "medium",
                    "color": "oro", "text_style": "text",
                    "text_vertical_anchor": "bottom"},
        },
    },
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
    # postal: portada de carrusel (foto a sangre, hook arriba-izq, CTA latón);
    # solido: el slide "de texto" de la guía, olivo casi pleno.
    "melaque_postal": {
        "texto": "hueso", "fondo": "olivo", "background_opacity": 0.3,
        "overlay": "olivo",
        "chrome": {"handle": "@melaquecapital",
                   "logo": "data/brands/melaquecapital/mark.svg",
                   "font": "Archivo"},
        "roles": {
            "hook": {"font": "Marcellus", "font_size": "extra_large",
                     "text_style": "text", "text_vertical_anchor": "top",
                     "text_align": "left", "text_anchor": "left"},
            "punto": {"font": "Marcellus", "font_size": "large",
                      "text_style": "text", "text_vertical_anchor": "center",
                      "text_align": "left", "text_anchor": "left"},
            "cta": {"font": "Archivo", "font_size": "medium", "color": "laton",
                    "text_style": "text", "text_vertical_anchor": "bottom"},
        },
    },
    "melaque_solido": {
        "texto": "hueso", "fondo": "olivo", "background_opacity": 0.85,
        "overlay": "olivo",
        "chrome": {"handle": "@melaquecapital",
                   "logo": "data/brands/melaquecapital/mark.svg",
                   "font": "Archivo"},
        "roles": {
            "hook": {"font": "Marcellus", "font_size": "extra_large",
                     "text_style": "text", "text_vertical_anchor": "center"},
            "punto": {"font": "Marcellus", "font_size": "large",
                      "text_style": "text", "text_vertical_anchor": "center"},
            "cta": {"font": "Archivo", "font_size": "medium", "color": "laton",
                    "text_style": "text", "text_vertical_anchor": "bottom"},
        },
    },
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

VOZ_SHITBOOK = (
    "Marca: shit.book (@shit.book) — historias reales de internet narradas en "
    "video vertical, con un pájaro de dientes humanos como narrador. "
    "Audiencia: 18-30, México, consumo de reels en loop. "
    "TONO: primera persona, frases cortas, sin preámbulo. El gancho va en los "
    "primeros tres segundos o no hay video. Humor seco e incomodidad, nunca "
    "moraleja ni 'reflexión final'. "
    "PROHIBIDO: 'les cuento', 'no van a creer lo que pasó', llamados a seguir "
    "al inicio, lenguaje de locutor, hashtags dentro de la narración. "
    "NO inventes hechos de la historia original: se puede recortar y reordenar, "
    "nunca cambiar el desenlace."
)

# Preset del motor de video de la marca (accounts.video_json → VideoPreset).
# Es el look que ya estaba validado en el prototipo: narrador rebotando,
# subtítulos de 3 palabras con la activa en amarillo, fondos del personaje.
VIDEO_SHITBOOK = {
    "voz": "es-MX-JorgeNeural",
    "rate": "+22%",
    "pitch": "-8Hz",
    "personaje_path": "data/brands/shitbook/personaje.png",
    "etiqueta_tarjeta": "r/historias",
    "autor_tarjeta": "anónimo · hace 3 h",
    "cta_texto": "sigue la historia",
    "cta_marca": "@shit.book",
    "color_acento": "#FFE600",
    "color_fondo": "#3B2414",
    "palabras_subtitulo": 3,
    # ~65 s de narración: medido, 170 palabras a rate +22% ≈ 65 s.
    "palabras_min": 90,
    "palabras_max": 170,
    "max_duracion_s": 90.0,
}

_PERFIL_SHITBOOK = {
    "voz": VOZ_SHITBOOK,
    # Marca de solo video: no hay carruseles ni banco de imágenes que curar.
    "formatos": json.dumps(["video"]),
    "video_json": json.dumps(VIDEO_SHITBOOK, ensure_ascii=False),
    "posting_slots": "14:00,21:00",
}

# Subreddits de historias narrables. Rutas (no URLs): el host lo fija
# `topics.fetch_reddit`. `t=week` para que la bandeja rote sola.
FUENTES_SHITBOOK = [
    "/r/HistoriasDeReddit/top/.rss?t=week",
    "/r/RelatosDeNoche/top/.rss?t=week",
    "/r/nosleep/top/.rss?t=week",
]


def _sembrar_fuentes_shitbook(cx, account_id: int) -> None:
    """Registra la fuente `reddit` de la marca si todavía no tiene ninguna.

    Idempotente y respetuoso igual que `_completar`: si ya hay una fuente
    reddit (aunque esté editada con otros subreddits) no se toca.
    """
    from src import fuentes as fuentes_mod

    ya = db.rows(cx, "SELECT id FROM brand_sources "
                     "WHERE account_id = ? AND provider = 'reddit'", (account_id,))
    if ya:
        return
    fuentes_mod.crear(cx, account_id, "info", "reddit",
                      {"rutas": FUENTES_SHITBOOK, "min_palabras": 60,
                       "cada_horas": 12})


def _fusionar_estilos(cx, account_id: int, semilla: dict) -> None:
    """Agrega presets NUEVOS a un estilos_json ya poblado sin tocar los que
    existen (editados a mano incluidos). Con el campo vacío no hace nada:
    _completar ya lo siembra entero."""
    fila = db.get(cx, "accounts", account_id)
    crudo = (fila.get("estilos_json") or "").strip()
    if not crudo:
        return
    try:
        actuales = json.loads(crudo)
    except ValueError:
        return  # malformado: no adivinamos, marcas._json_o ya avisa en runtime
    nuevos = {k: v for k, v in semilla.items() if k not in actuales}
    if nuevos:
        db.update(cx, "accounts", account_id,
                  estilos_json=json.dumps({**actuales, **nuevos}, ensure_ascii=False))


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
    if "shitbook" not in por_slug:
        por_slug["shitbook"] = db.insert(
            cx, "accounts", slug="shitbook", ig_handle="@shit.book",
            nombre="shit.book", ciudad="Guadalajara",
            color_marca="#FFE600", activa=1)
    _completar(cx, por_slug["shitbook"], _PERFIL_SHITBOOK)
    _sembrar_fuentes_shitbook(cx, por_slug["shitbook"])
    _fusionar_estilos(cx, por_slug["pensionmas"], ESTILOS_PENSIONMAS)
    _fusionar_estilos(cx, por_slug["melaquecapital"], ESTILOS_MELAQUECAPITAL)
    from src import recetas
    recetas.sembrar(cx, por_slug["melaquecapital"], recetas.SEMILLA_MELAQUECAPITAL)
    print("Seeds de marca aplicados "
          "(gdlscene + pensionmas + melaquecapital + shitbook).")


if __name__ == "__main__":
    cx = db.connect()
    try:
        db.init_db(cx)
        sembrar(cx)
    finally:
        cx.close()
