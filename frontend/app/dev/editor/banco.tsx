"use client";

import { useEffect } from "react";
import { Lienzo } from "@/app/b/[slug]/templates/[id]/_components/lienzo";
import datos from "@/lib/__fixtures__/ops-casos.json";
import type { Escena } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

// Banco del lienzo con la escena del fixture: zoom 0.5, pan (32, 32), sin imán.
// El estado se expone en <pre data-testid="estado"> para la e2e.
export function Banco() {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  const pasado = useEditor((s) => s.pasado.length);
  const editando = useEditor((s) => s.editandoTexto);

  useEffect(() => {
    const st = useEditor.getState();
    const e = structuredClone(datos.base) as unknown as Escena;
    e.guias = { cols: 0, filas: 0, iman: false };
    st.cargar(e);
    st.setZoom(0.5);
    return () => useEditor.getState().vaciar();
  }, []);

  const capas = (escena?.capas ?? []).map((c) => ({
    id: c.id,
    x: c.x,
    y: c.y,
    w: c.w,
    h: c.h,
    rot: c.rot,
    ...(c.tipo === "text" ? { texto: c.texto } : {}),
  }));

  return (
    <div style={{ padding: 24 }}>
      <button type="button" onClick={() => useEditor.getState().deshacer()}>
        Deshacer
      </button>
      <div style={{ width: 800, height: 800, marginTop: 8 }}>
        <Lienzo slug="e2e" colorMarca="#ff3366" ajustarAlCargar={false} />
      </div>
      <pre data-testid="estado">{JSON.stringify({ sel: seleccion, pasado, editando, capas })}</pre>
    </div>
  );
}
