"""Registro de proveedores de assets. El plan 5 agrega `ig_seguidos` aquí."""
from __future__ import annotations

from src.assets.proveedores.base import Proveedor
from src.assets.proveedores.carpeta import Carpeta
from src.assets.proveedores.unsplash import Unsplash

PROVEEDORES: dict[str, type[Proveedor]] = {c.nombre: c for c in (Carpeta, Unsplash)}
