"""Política del banco: qué fotos se conservan por banda.

PURO y sin IO — recibe fotos con sus caras ya agrupadas y devuelve qué ids
entran. Vive aparte porque es la pieza que se va a ajustar con el tiempo y debe
poder probarse sin imágenes ni base de datos.

El cupo es POR PERSONA, no por banda: un tope por banda puede llenarse con
diez fotos del vocalista y dejar al baterista fuera, que es exactamente el
problema que este banco resuelve.
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
                 minimo_sin_caras: int) -> set[int]:
    """Ids que entran al banco.

    Tres cubetas independientes: una por persona (fotos de una sola cara), una
    de grupales (2+ caras), y la degradación sin caras para foros y paisajes.
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

    # Degradación: solo si la banda no dio material con caras.
    if not dentro:
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


def procesar_banda(cx, band_id: int, *, _analizador=None) -> dict:
    """Deduplica, agrupa caras, aplica cupo y persiste. Idempotente.

    El batch nunca pisa un nombre capturado a mano (misma regla que
    `generos_fuente`): antes de recrear `personas`/`face_signatures` se
    guarda el centroide de cada persona ya nombrada, y tras reagrupar se le
    reasigna a la persona del grupo nuevo más parecida. Si ninguna calza —
    la cara desapareció por dedup o la foto se marcó `descartada` — la
    persona nombrada se vuelve a crear igual, sin firmas ni fotos, para que
    el nombre sobreviva y pueda volver a casar en el siguiente reproceso.
    """
    analizar = _analizador or _analizar_real
    filas = db.rows(cx, "SELECT id, path FROM photos WHERE band_id = ? AND descartada = 0",
                    (band_id,))

    # Limpieza + preservación de lo manual ANTES de cualquier early-return: el
    # estado en DB debe ser el mismo invariante con fotos o sin ellas (nunca
    # deja personas/firmas huérfanas de una corrida anterior).
    nombradas = _centroides_nombrados(cx, band_id)
    cx.execute("DELETE FROM face_signatures WHERE photo_id IN "
               "(SELECT id FROM photos WHERE band_id = ?)", (band_id,))
    cx.execute("DELETE FROM personas WHERE band_id = ?", (band_id,))
    cx.execute("UPDATE photos SET persona_id = NULL WHERE band_id = ?", (band_id,))

    if not filas:
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
                          config.FOTOS_MINIMO_SIN_CARAS)

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
