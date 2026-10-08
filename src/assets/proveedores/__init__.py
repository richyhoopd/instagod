"""Registro de proveedores de assets. El plan 5 agrega `ig_seguidos` aquí."""
from __future__ import annotations

from src.assets.proveedores.base import Proveedor
from src.assets.proveedores.carpeta import Carpeta
from src.assets.proveedores.coverr import Coverr
from src.assets.proveedores.giphy import Giphy
from src.assets.proveedores.openverse import Openverse
from src.assets.proveedores.pexels import Pexels
from src.assets.proveedores.pixabay import Pixabay
from src.assets.proveedores.unsplash import Unsplash

_TODOS = (Carpeta, Unsplash, Pexels, Pixabay, Openverse, Coverr, Giphy)
PROVEEDORES: dict[str, type[Proveedor]] = {c.nombre: c for c in _TODOS}
