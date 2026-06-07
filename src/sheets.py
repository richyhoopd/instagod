"""Cliente de Google Sheets: la hoja es a la vez cola y panel de control.

Una fila por meme. El esquema de columnas vive en `COLUMNS` y refleja la
sección 3 del blueprint. Toda escritura es por `id` (idempotente), nunca por
índice de fila.
"""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any

import gspread
import pytz

import config

# Solo spreadsheets: abrimos la hoja por ID (open_by_key), no listamos archivos,
# así evitamos el scope "restricted" de Drive y simplificamos la verificación.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# Orden y nombres EXACTOS de los encabezados en la fila 1 del Sheet.
COLUMNS = [
    "id",
    "fecha_captura",
    "banda",
    "integrante",
    "rol",
    "foto_url",
    "foto_inset_url",
    "tema_semilla",
    "caption_generado",
    "caption_final",
    "imagen_compuesta_url",
    "status",
    "scheduled_datetime",
    "ig_post_id",
    "notas",
    # Crosspost (al final: la hoja real ya existía con las columnas de arriba).
    "tw_post_id",
    "fb_post_id",
]

# Estados válidos del campo `status`.
STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_PUBLISHED = "published"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"


def _credentials():
    """Resuelve credenciales de Google.

    Orden de preferencia:
      1. Service account JSON (si existe; por si la política de la org se levanta).
      2. OAuth de usuario: token guardado (authorized-user.json), refrescándolo.
      3. OAuth de usuario: primer login interactivo con el cliente Desktop
         (oauth-client.json) → abre el navegador y guarda el token.
    """
    sa_path = config.resolve_sa_path()
    if sa_path.exists():
        from google.oauth2.service_account import Credentials as SACredentials
        return SACredentials.from_service_account_file(str(sa_path), scopes=SCOPES)

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials as UserCredentials

    user_path = config.resolve_authorized_user_path()
    if user_path.exists():
        creds = UserCredentials.from_authorized_user_file(str(user_path), SCOPES)
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            user_path.write_text(creds.to_json())
        return creds

    client_path = config.resolve_oauth_client_path()
    if client_path.exists():
        from google_auth_oauthlib.flow import InstalledAppFlow
        flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
        creds = flow.run_local_server(port=0)
        user_path.parent.mkdir(parents=True, exist_ok=True)
        user_path.write_text(creds.to_json())
        return creds

    raise RuntimeError(
        "No hay credenciales de Google. Coloca el cliente OAuth en "
        f"{client_path} y corre la autorización (o un service account en {sa_path})."
    )


@lru_cache(maxsize=1)
def _worksheet() -> gspread.Worksheet:
    client = gspread.authorize(_credentials())
    return client.open_by_key(config.SHEET_ID).sheet1


def ensure_headers() -> None:
    """Escribe la fila de encabezados si la hoja está vacía. Útil al inicializar."""
    ws = _worksheet()
    first_row = ws.row_values(1)
    if not first_row:
        ws.update("A1", [COLUMNS])


def _records() -> list[dict[str, Any]]:
    """Todas las filas como dicts {columna: valor}, en orden de hoja.

    Adjunta `_row` (índice 1-based en la hoja) para localizar la celda al escribir.
    """
    ws = _worksheet()
    records = ws.get_all_records(expected_headers=COLUMNS)
    for i, rec in enumerate(records, start=2):  # fila 1 = encabezados
        rec["_row"] = i
    return records


def get_pending_rows() -> list[dict[str, Any]]:
    """Filas por procesar: status == pending, o status vacío en una fila con datos.

    Tratar el status vacío como pending evita que tengas que escribir "pending" a
    mano: basta con llenar los datos de la fila. Se exige que tenga `foto_url`
    (señal de que la fila tiene contenido real, no está en blanco).
    """
    out = []
    for r in _records():
        status = str(r.get("status", "")).strip().lower()
        has_content = bool(str(r.get("foto_url", "")).strip())
        if status == STATUS_PENDING or (status == "" and has_content):
            out.append(r)
    return out


def get_due_rows(now: datetime | None = None) -> list[dict[str, Any]]:
    """Filas approved cuyo scheduled_datetime ya venció (lo que el worker publica)."""
    tz = pytz.timezone(config.TIMEZONE)
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = tz.localize(now)

    due: list[dict[str, Any]] = []
    for r in _records():
        if str(r.get("status", "")).strip() != STATUS_APPROVED:
            continue
        sched = _parse_dt(r.get("scheduled_datetime"), tz)
        if sched is not None and sched <= now:
            due.append(r)
    return due


def append_row(**fields: Any) -> int:
    """Crea una fila nueva con id auto-incremental. Devuelve el id asignado."""
    ws = _worksheet()
    ids = [int(r["id"]) for r in _records() if str(r.get("id", "")).strip().isdigit()]
    new_id = (max(ids) + 1) if ids else 1
    fields.setdefault("id", new_id)
    for key in fields:
        if key not in COLUMNS:
            raise KeyError(f"Columna desconocida: {key}")
    row = [fields.get(col, "") for col in COLUMNS]
    ws.append_row(row, value_input_option="USER_ENTERED")
    return new_id


def update_row(row_id: int | str, **fields: Any) -> None:
    """Escribe `fields` en la fila cuyo `id` coincide. Idempotente por id."""
    ws = _worksheet()
    target = next((r for r in _records() if str(r.get("id")) == str(row_id)), None)
    if target is None:
        raise ValueError(f"No existe una fila con id={row_id}")

    row_idx = target["_row"]
    updates = []
    for key, value in fields.items():
        if key not in COLUMNS:
            raise KeyError(f"Columna desconocida: {key}")
        col_idx = COLUMNS.index(key) + 1
        updates.append({
            "range": gspread.utils.rowcol_to_a1(row_idx, col_idx),
            "values": [[value]],
        })
    if updates:
        ws.batch_update(updates)


def _parse_dt(raw: Any, tz: "pytz.BaseTzInfo") -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).strip())
    except ValueError:
        return None
    return tz.localize(dt) if dt.tzinfo is None else dt
