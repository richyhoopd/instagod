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


def _centroides_nombrados(cx, band_id: int) -> list[tuple[int, "np.ndarray"]]:
    """(member_id, centroide) de las personas de la banda que ya tienen nombre."""
    filas = db.rows(cx, """
        SELECT p.member_id, f.embedding
          FROM personas p JOIN face_signatures f ON f.persona_id = p.id
         WHERE p.band_id = ? AND p.member_id IS NOT NULL
    """, (band_id,))
    por_member: dict[int, list["np.ndarray"]] = {}
    for fila in filas:
        por_member.setdefault(fila["member_id"], []).append(
            np.frombuffer(fila["embedding"], dtype=np.float32))
    return [(mid, _centroide(vs)) for mid, vs in por_member.items()]


def _member_mas_parecido(nombradas: list[tuple[int, "np.ndarray"]],
                         centroide: "np.ndarray") -> int | None:
    """member_id del nombrado más parecido, o None si ninguno alcanza el umbral."""
    mejor, mejor_sim = None, config.FACE_COS_MISMA_PERSONA
    for member_id, c in nombradas:
        sim = faces.similitud(c, centroide)
        if sim >= mejor_sim:
            mejor, mejor_sim = member_id, sim
    return mejor


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
    """Deduplica, agrupa caras, aplica cupo y persiste. Idempotente."""
    analizar = _analizador or _analizar_real
    filas = db.rows(cx, """
        SELECT id, path, nitidez FROM photos
         WHERE band_id = ? AND descartada = 0
    """, (band_id,))
    if not filas:
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

    # 3. Persistir personas. Antes de recrearlas, guardamos el centroide de las
    #    que YA tienen nombre para volver a pegárselo al grupo equivalente: el
    #    batch nunca pisa lo manual (misma regla que `generos_fuente`).
    nombradas = _centroides_nombrados(cx, band_id)
    cx.execute("DELETE FROM face_signatures WHERE photo_id IN "
               "(SELECT id FROM photos WHERE band_id = ?)", (band_id,))
    cx.execute("DELETE FROM personas WHERE band_id = ?", (band_id,))

    ids_persona: list[int] = []
    for i, grupo in enumerate(grupos_persona):
        centroide = _centroide([plano[j][4] for j in grupo])
        member_id = _member_mas_parecido(nombradas, centroide)
        ids_persona.append(db.insert(cx, "personas", band_id=band_id,
                                     member_id=member_id,
                                     etiqueta_auto=f"persona {chr(65 + i)}"))
    for j, (photo_id, bbox, score, frac, vec) in enumerate(plano):
        db.insert(cx, "face_signatures", photo_id=photo_id,
                  persona_id=ids_persona[idx_de_cara[j]],
                  bbox=json.dumps(list(bbox)), det_score=score,
                  embedding=np.asarray(vec, dtype=np.float32).tobytes())

    # 4. Cupo.
    para_cupo = []
    for foto in representantes:
        caras = [{"persona_idx": idx_de_cara[j], "det_score": p[2], "frac_area": p[3]}
                 for j, p in enumerate(plano) if p[0] == foto["id"]]
        para_cupo.append({"id": foto["id"], "nitidez": foto["nitidez"], "caras": caras})
    dentro = aplicar_cupo(para_cupo, config.FOTOS_POR_PERSONA, config.FOTOS_GRUPALES,
                          config.FOTOS_MINIMO_SIN_CARAS)

    # 5. Marcar. NUNCA se borra ni se marca `descartada`: solo sale del banco.
    caras_por_foto: dict[int, list[int]] = {}
    for j, p in enumerate(plano):
        caras_por_foto.setdefault(p[0], []).append(j)
    for foto in analizadas:
        entra = foto["id"] in dentro
        indices = caras_por_foto.get(foto["id"], [])
        # La persona de la foto es la de la cara MÁS GRANDE (la protagonista).
        persona_id = None
        if indices:
            dominante = max(indices, key=lambda j: plano[j][3])
            persona_id = ids_persona[idx_de_cara[dominante]]
        caras_foto = indices
        db.update(cx, "photos", foto["id"],
                  usable_meme=1 if entra else 0,
                  es_grupal=1 if len(caras_foto) >= 2 else 0,
                  faces_count=len(caras_foto),
                  nitidez=round(foto["nitidez"], 1),
                  persona_id=persona_id)
    cx.commit()
    return {"personas": len(grupos_persona), "fotos_dentro": len(dentro),
            "fotos_fuera": len(analizadas) - len(dentro), "duplicadas": duplicadas}
