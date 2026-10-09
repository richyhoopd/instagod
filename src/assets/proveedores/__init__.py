"""Registro de proveedores de assets. Incluye `ig_seguidos` (plan 5)."""
from __future__ import annotations

from src.assets.proveedores.base import Proveedor
from src.assets.proveedores.carpeta import Carpeta
from src.assets.proveedores.coverr import Coverr
from src.assets.proveedores.giphy import Giphy
from src.assets.proveedores.ia_imagen import IaImagen
from src.assets.proveedores.ig_seguidos import IgSeguidosProvider
from src.assets.proveedores.openverse import Openverse
from src.assets.proveedores.pexels import Pexels
from src.assets.proveedores.pixabay import Pixabay
from src.assets.proveedores.unsplash import Unsplash

_TODOS = (Carpeta, Unsplash, Pexels, Pixabay, Openverse, Coverr, Giphy, IaImagen,
          IgSeguidosProvider)
PROVEEDORES: dict[str, type[Proveedor]] = {c.nombre: c for c in _TODOS}
