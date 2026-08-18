"""Límite de eventos por clave en memoria (suficiente para 1 proceso de API)."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class Limitador:
    def __init__(self, max_eventos: int, ventana_seg: int):
        self.max, self.ventana = max_eventos, ventana_seg
        self._eventos: dict[str, deque[float]] = defaultdict(deque)

    def permitir(self, clave: str, ahora: float | None = None) -> bool:
        t = time.monotonic() if ahora is None else ahora
        cola = self._eventos[clave]
        while cola and t - cola[0] > self.ventana:
            cola.popleft()
        if len(cola) >= self.max:
            return False
        cola.append(t)
        return True
