"""Política del banco: qué fotos se conservan por banda.

PURO y sin IO — recibe fotos con sus caras ya agrupadas y devuelve qué ids
entran. Vive aparte porque es la pieza que se va a ajustar con el tiempo y debe
poder probarse sin imágenes ni base de datos.

El cupo es POR PERSONA, no por banda: un tope por banda puede llenarse con
diez fotos del vocalista y dejar al baterista fuera, que es exactamente el
problema que este banco resuelve.

⚠️ DOS ESCRITORES DE `usable_meme` — ORDEN OBLIGATORIO: classify PRIMERO, banco
DESPUÉS. `src.classify` escribe la misma columna con otra política ("la foto es
apta"), este módulo la re-escribe con la suya ("además ganó el cupo"). La última
corrida gana. Corolario operativo: `python -m src.classify --redo` (el checkbox
"re-hacer todas" de la GUI) INVALIDA la decisión de cupo de esa banda y obliga a
re-correr `python -m src.banco <handle>` para recuperarla. Una corrida normal de
classify (sin `--redo`) no la toca: filtra por `faces_count IS NULL` y el banco
siempre escribe `faces_count`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

import config
from src import db, dedup_fotos, faces, imghash


def puntuar(foto: dict[str, Any]) -> float:
    """Qué tan buena es como retrato: nitidez × confianza × tamaño de la cara.

    Sin caras cae a la nitidez sola. El factor de tamaño evita que gane una
    foto nitidísima donde la persona sale de 20 píxeles al fondo.
    """
    nitidez = float(foto.get("nitidez") or 0.0)
    caras = foto.get("caras") or []
    if not caras:
        return nitidez
    mejor = max(caras, key=lambda c: c.get("frac_area", 0.0))
    return nitidez * float(mejor.get("det_score", 0.0)) * float(mejor.get("frac_area", 0.0))


def aplicar_cupo(fotos: list[dict[str, Any]], por_persona: int, grupales: int,
                 minimo_sin_caras: int, *, admite_sin_caras: bool = False,
                 cupo_sin_caras: int | None = None) -> set[int]:
    """Ids que entran al banco.

    Tres cubetas: una por persona (fotos de una sola cara), una de grupales
    (2+ caras) y una sin caras. Qué significa la tercera depende del actor:

    - `admite_sin_caras=False` (banda, solista): una foto sin cara no sirve de
      meme, así que la cubeta es DEGRADACIÓN de último recurso — solo se llena,
      hasta `minimo_sin_caras`, si ninguna foto con cara entró.
    - `admite_sin_caras=True` (los tipos de `config.TIPOS_SIN_CARA`: foro,
      evento, colectivo): ahí lo que vale es el lugar, el ambiente, el público
      — la foto sin cara es el material PRINCIPAL. La cubeta tiene cupo propio
      (`cupo_sin_caras`, default `config.FOTOS_SIN_CARAS`) y se llena SIEMPRE,
      igual que las de individuales y grupales.

    Por qué el cupo propio y no `minimo_sin_caras`: `FOTOS_MINIMO_SIN_CARAS` es
    4 porque es una degradación. Aplicárselo a un foro con 200 fotos del lugar
    tira el 98% del acervo por una sola foto con cara que se colara. Un foro no
    tiene "integrantes" entre los que repartir, así que su banco debe parecerse
    al de una BANDA ENTERA: 3-4 integrantes × `por_persona` + `grupales` ≈ 18-23
    fotos. De ahí el default de 20 (ver `config.FOTOS_SIN_CARAS`).
    """
    ordenadas = sorted(fotos, key=puntuar, reverse=True)
    individuales = [f for f in ordenadas if len(f.get("caras") or []) == 1]
    de_grupo = [f for f in ordenadas if len(f.get("caras") or []) >= 2]
    sin_caras = [f for f in ordenadas if not (f.get("caras") or [])]

    dentro: set[int] = set()
    usado: dict[int, int] = {}
    for f in individuales:
        idx = f["caras"][0]["persona_idx"]
        if usado.get(idx, 0) < por_persona:
            usado[idx] = usado.get(idx, 0) + 1
            dentro.add(f["id"])

    dentro.update(f["id"] for f in de_grupo[:grupales])

    if admite_sin_caras:
        cupo = config.FOTOS_SIN_CARAS if cupo_sin_caras is None else cupo_sin_caras
        dentro.update(f["id"] for f in sin_caras[:cupo])
    elif not dentro:
        # Degradación: solo si la banda no dio material con caras.
        dentro.update(f["id"] for f in sin_caras[:minimo_sin_caras])
    return dentro


def _centroide(vecs: list["np.ndarray"]) -> "np.ndarray":
    """Vector medio L2-normalizado de un grupo de firmas."""
    media = np.mean(np.stack(vecs), axis=0).astype(np.float32)
    norma = float(np.linalg.norm(media))
    return media / norma if norma else media


def _etiqueta(i: int) -> str:
    """Índice 0-based → A, B, ..., Z, AA, AB, ... (bijective base-26, sin tope)."""
    i += 1
    letras = ""
    while i > 0:
        i, r = divmod(i - 1, 26)
        letras = chr(65 + r) + letras
    return letras


def _centroides_nombrados(cx, band_id: int) -> list[tuple[int, "np.ndarray"]]:
    """(member_id, centroide) de las personas de la banda que ya tienen nombre.

    Lee el centroide de `personas.centroide` (persiste aunque sus firmas
    desaparezcan). Si viene NULL — filas de antes de que existiera la columna—
    se calcula desde las firmas vivas como respaldo.
    """
    filas = db.rows(cx, """
        SELECT id, member_id, centroide FROM personas
         WHERE band_id = ? AND member_id IS NOT NULL
    """, (band_id,))
    salida: list[tuple[int, "np.ndarray"]] = []
    for fila in filas:
        if fila["centroide"] is not None:
            salida.append((fila["member_id"],
                           np.frombuffer(fila["centroide"], dtype=np.float32)))
            continue
        vecs = [np.frombuffer(f["embedding"], dtype=np.float32) for f in db.rows(
            cx, "SELECT embedding FROM face_signatures WHERE persona_id = ?", (fila["id"],))]
        if vecs:
            salida.append((fila["member_id"], _centroide(vecs)))
    return salida


def _asignar_members(nombradas: list[tuple[int, "np.ndarray"]],
                     centroides_grupo: list["np.ndarray"],
                     umbral: float) -> dict[int, int]:
    """grupo_idx -> member_id, asignación 1-a-1 greedy por similitud descendente.

    Un member_id nombrado no puede reclamar dos grupos (ni viceversa): si sus
    caras se partieron en dos grupos, solo el más parecido se queda con el
    nombre — evita que el cupo le dé el doble de fotos al mismo integrante.
    Empates se desempatan por índice de grupo ascendente (determinista).
    """
    pares = [(faces.similitud(cg, cm), gi, member_id)
             for gi, cg in enumerate(centroides_grupo)
             for member_id, cm in nombradas
             if faces.similitud(cg, cm) >= umbral]
    pares.sort(key=lambda p: (-p[0], p[1]))
    asignado: dict[int, int] = {}
    usados: set[int] = set()
    for _, gi, member_id in pares:
        if gi in asignado or member_id in usados:
            continue
        asignado[gi] = member_id
        usados.add(member_id)
    return asignado


def _analizar_real(path: Path):
    """(hash, nitidez, [(bbox, det_score, frac_area, firma)]) de una foto en disco."""
    import cv2

    from src import classify
    img = cv2.imread(str(path))
    if img is None:
        return None, 0.0, []
    gris = classify.cargar_normalizada(path)
    nitidez = classify.medir_nitidez(gris) if gris is not None else 0.0
    detectadas = [(c.bbox, c.det_score, c.frac_area, faces.firma(img, c))
                  for c in faces.detectar(img)]
    return imghash.phash(path), nitidez, detectadas


def _limpiar_banda(cx, band_id: int) -> None:
    """Borra firmas/personas de la banda y desasocia sus fotos. Sin commit:
    quien llama decide cuándo es seguro persistir."""
    cx.execute("DELETE FROM face_signatures WHERE photo_id IN "
               "(SELECT id FROM photos WHERE band_id = ?)", (band_id,))
    cx.execute("DELETE FROM personas WHERE band_id = ?", (band_id,))
    cx.execute("UPDATE photos SET persona_id = NULL WHERE band_id = ?", (band_id,))


def procesar_banda(cx, band_id: int, *, limite: int = 40, _analizador=None) -> dict:
    """Deduplica, agrupa caras, aplica cupo y persiste. Idempotente.

    El batch nunca pisa un nombre capturado a mano (misma regla que
    `generos_fuente`): antes de recrear `personas`/`face_signatures` se
    guarda el centroide de cada persona ya nombrada, y tras reagrupar se le
    reasigna a la persona del grupo nuevo más parecida. Si ninguna calza —
    la cara desapareció por dedup o la foto se marcó `descartada` — la
    persona nombrada se vuelve a crear igual, sin firmas ni fotos, para que
    el nombre sobreviva y pueda volver a casar en el siguiente reproceso.

    `limite` es el perezoso a propósito: solo se analizan las `limite`
    fotos con mejor `nitidez` ya guardada en DB. Analizar el acervo completo
    es gastar CPU en fotos que de todos modos van a perder el cupo. Debe ser
    positivo: en SQLite un `LIMIT` negativo significa "sin límite", así que
    un valor negativo anularía en silencio esta protección. Consecuencia a
    propósito: las fotos que quedan fuera del límite NO se reanalizan, y
    como la limpieza pone `persona_id = NULL` para toda la banda, quedan con
    `persona_id` NULL hasta que una corrida con `limite` mayor las alcance
    — es preferible a dejar ids colgando (el bug que resolvió la Task 6).

    El análisis (lo que puede tronar por una imagen corrupta) corre ANTES de
    tocar la base: si `analizar` lanza, esta banda no queda con DELETE/UPDATE
    a medias — no se mutó nada suyo todavía.

    Los flyers quedan fuera de la selección (mismo `NOT EXISTS` que el planner):
    no se analizan, no compiten por el cupo y su `usable_meme` no se toca.

    `bands.tipo` decide si la cubeta sin caras tiene cupo propio: ver
    `aplicar_cupo` y `config.TIPOS_SIN_CARA`.
    """
    if limite <= 0:
        raise ValueError(f"limite debe ser positivo, recibido {limite!r}")

    analizar = _analizador or _analizar_real
    banda = db.get(cx, "bands", band_id) or {}
    admite_sin_caras = (banda.get("tipo") or "banda") in config.TIPOS_SIN_CARA
    nombradas = _centroides_nombrados(cx, band_id)
    filas = db.rows(cx, """
        SELECT p.id, p.path FROM photos p
         WHERE p.band_id = ? AND p.descartada = 0
           -- Los flyers NO son memes (el planner ya los filtra en
           -- `seleccionar`/`pick_replacement` y `generate_relleno.candidatas`):
           -- si compitieran aquí se llevarían cupo —son nitidísimos, entran
           -- primero al LIMIT— para no llegar nunca a un post.
           AND NOT EXISTS (SELECT 1 FROM events e
                           WHERE e.tipo = 'flyer'
                             AND e.source_post_id = p.source_post_id)
         ORDER BY p.nitidez DESC
         LIMIT ?
    """, (band_id, limite))

    if not filas:
        # Sin fotos que analizar no hay nada que pueda tronar: limpiar y
        # recrear nombradas de una vez es seguro.
        _limpiar_banda(cx, band_id)
        for indice, (member_id, centroide) in enumerate(nombradas):
            db.insert(cx, "personas", band_id=band_id, member_id=member_id,
                      etiqueta_auto=f"persona {_etiqueta(indice)}",
                      centroide=centroide.tobytes())
        cx.commit()
        return {"personas": 0, "fotos_dentro": 0, "fotos_fuera": 0, "duplicadas": 0}

    analizadas: list[dict] = []
    for fila in filas:
        p = Path(fila["path"])
        if not p.is_absolute():
            p = config.BASE_DIR / p
        h, nitidez, caras = analizar(p)
        analizadas.append({"id": fila["id"], "hash": h, "nitidez": nitidez,
                           "caras_raw": caras})

    # Limpieza + preservación de lo manual: recién AHORA que el análisis
    # completo sin tronar, se borra y reconstruye. Si algo de arriba lanza,
    # esta banda no quedó mutada — la excepción sube intacta a `procesar`.
    _limpiar_banda(cx, band_id)

    # 1. Dedup: solo el representante de cada grupo compite por el cupo.
    grupos_dup = dedup_fotos.agrupar_duplicadas(analizadas, config.DEDUP_HAMMING_MAX)
    representantes = [g[0] for g in grupos_dup]
    duplicadas = sum(len(g) - 1 for g in grupos_dup)

    # 2. Agrupar TODAS las caras de la banda en personas.
    plano: list[tuple[int, tuple, float, float, "np.ndarray"]] = []
    for foto in representantes:
        for bbox, score, frac, vec in foto["caras_raw"]:
            plano.append((foto["id"], bbox, score, frac, vec))
    grupos_persona = faces.agrupar([p[4] for p in plano], config.FACE_COS_MISMA_PERSONA)
    idx_de_cara = {}
    for i, grupo in enumerate(grupos_persona):
        for j in grupo:
            idx_de_cara[j] = i

    # 3. Persistir personas: asignación 1-a-1 (un member no puede quedar en dos
    #    grupos) y, al final, recrear sin firmas a las nombradas que no calzaron
    #    con ningún grupo — el nombre nunca se pierde.
    centroides_grupo = [_centroide([plano[j][4] for j in grupo]) for grupo in grupos_persona]
    asignado = _asignar_members(nombradas, centroides_grupo, config.FACE_COS_MISMA_PERSONA)

    ids_persona: list[int] = []
    indice = 0
    for i, centroide in enumerate(centroides_grupo):
        ids_persona.append(db.insert(cx, "personas", band_id=band_id,
                                     member_id=asignado.get(i),
                                     etiqueta_auto=f"persona {_etiqueta(indice)}",
                                     centroide=centroide.tobytes()))
        indice += 1
    usados = set(asignado.values())
    for member_id, centroide in nombradas:
        if member_id in usados:
            continue
        db.insert(cx, "personas", band_id=band_id, member_id=member_id,
                  etiqueta_auto=f"persona {_etiqueta(indice)}",
                  centroide=centroide.tobytes())
        indice += 1

    for j, (photo_id, bbox, score, frac, vec) in enumerate(plano):
        db.insert(cx, "face_signatures", photo_id=photo_id,
                  persona_id=ids_persona[idx_de_cara[j]],
                  bbox=json.dumps(list(bbox)), det_score=score,
                  embedding=np.asarray(vec, dtype=np.float32).tobytes())

    # 4. Cupo. Reusa el mismo índice cara->foto que la marcación (paso 5).
    caras_por_foto: dict[int, list[int]] = {}
    for j, p in enumerate(plano):
        caras_por_foto.setdefault(p[0], []).append(j)

    para_cupo = []
    for foto in representantes:
        caras = [{"persona_idx": idx_de_cara[j], "det_score": plano[j][2], "frac_area": plano[j][3]}
                 for j in caras_por_foto.get(foto["id"], [])]
        para_cupo.append({"id": foto["id"], "nitidez": foto["nitidez"], "caras": caras})
    dentro = aplicar_cupo(para_cupo, config.FOTOS_POR_PERSONA, config.FOTOS_GRUPALES,
                          config.FOTOS_MINIMO_SIN_CARAS,
                          admite_sin_caras=admite_sin_caras,
                          cupo_sin_caras=config.FOTOS_SIN_CARAS)

    # 5. Marcar. NUNCA se borra ni se marca `descartada`: solo sale del banco.
    for foto in analizadas:
        entra = foto["id"] in dentro
        indices = caras_por_foto.get(foto["id"], [])
        # La persona de la foto es la de la cara MÁS GRANDE (la protagonista).
        persona_id = None
        if indices:
            dominante = max(indices, key=lambda j: plano[j][3])
            persona_id = ids_persona[idx_de_cara[dominante]]
        db.update(cx, "photos", foto["id"],
                  usable_meme=1 if entra else 0,
                  es_grupal=1 if len(indices) >= 2 else 0,
                  faces_count=len(indices),
                  nitidez=round(foto["nitidez"], 1),
                  persona_id=persona_id)
    cx.commit()
    return {"personas": len(grupos_persona), "fotos_dentro": len(dentro),
            "fotos_fuera": len(analizadas) - len(dentro), "duplicadas": duplicadas}


def procesar(handles: list[str] | None = None, *, limite_por_banda: int = 40,
             _cx=None, _analizador=None) -> dict:
    """Corre el banco sobre las bandas activas. Una caída aislada no tumba el lote."""
    if limite_por_banda <= 0:
        raise ValueError(f"limite_por_banda debe ser positivo, recibido {limite_por_banda!r}")
    propia = _cx is None
    cx = _cx or db.connect()
    resumen = {"bandas": 0, "personas": 0, "fotos_dentro": 0,
               "duplicadas": 0, "fallidas": []}
    try:
        if propia:
            db.init_db(cx)
        q = "SELECT id, nombre, ig_handle FROM bands WHERE activa = 1"
        params: tuple = ()
        if handles:
            marcas = ",".join("?" * len(handles))
            q += f" AND lower(ig_handle) IN ({marcas})"
            params = tuple(h.lstrip("@").lower() for h in handles)
        for banda in db.rows(cx, q + " ORDER BY prioridad, id", params):
            print(f"▶ @{banda['ig_handle']} ({banda['nombre']})")
            try:
                r = procesar_banda(cx, banda["id"], limite=limite_por_banda,
                                   _analizador=_analizador)
            except Exception as exc:  # noqa: BLE001 — banda rota no tumba la corrida
                cx.rollback()  # cinturón: cualquier mutación a medias de esta banda no persiste
                print(f"   ❌ {exc}")
                resumen["fallidas"].append(banda["ig_handle"])
                continue
            resumen["bandas"] += 1
            resumen["personas"] += r["personas"]
            resumen["fotos_dentro"] += r["fotos_dentro"]
            resumen["duplicadas"] += r["duplicadas"]
            print(f"   ✅ {r['personas']} persona(s) · {r['fotos_dentro']} al banco "
                  f"· {r['duplicadas']} duplicada(s)")
        return resumen
    finally:
        if propia:
            cx.close()


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Banco de fotos por persona")
    parser.add_argument("handles", nargs="*", help="handles específicos (vacío = todas)")
    parser.add_argument("--limite", type=int, default=40,
                        help="fotos por banda a analizar (default 40)")
    args = parser.parse_args()
    try:
        res = procesar(args.handles or None, limite_por_banda=args.limite)
    except KeyboardInterrupt:
        sys.exit("\nInterrumpido.")
    print(f"\nResumen: {res['bandas']} banda(s) · {res['personas']} persona(s) · "
          f"{res['fotos_dentro']} foto(s) al banco · {res['duplicadas']} duplicada(s)"
          + (f" · fallidas: {', '.join(res['fallidas'])}" if res["fallidas"] else ""))
