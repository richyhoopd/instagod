"use client";

import { applyPatches, enablePatches, produceWithPatches, type Draft, type Patch } from "immer";
import { create } from "zustand";
import {
  aplicarEnBorrador,
  descendientes,
  padreDe,
  reformatear,
  type Capa,
  type Escena,
  type Formato,
  type Op,
} from "@/lib/escena";
import {
  conCajasDeGrupo,
  opsAgrupar,
  opsAlinear,
  opsDesagrupar,
  opsDistribuir,
  opsDuplicar,
  opsMover,
  opsPegar,
  opsZ,
  type ModoAlinear,
  type ModoZ,
} from "@/lib/edicion";

enablePatches();

export type Paso = { etiqueta: string; adelante: Patch[]; atras: Patch[] };
export const LIMITE_HISTORIA = 200;

export type EstadoEditor = {
  escena: Escena | null;
  seleccion: string[];
  sucio: boolean;
  pasado: Paso[];
  futuro: Paso[];
  revision: number;
  zoom: number;
  editandoTexto: string | null;
  portapapeles: Capa[];
  cargar(escena: Escena): void;
  aplicar(ops: Op[], etiqueta?: string): void;
  agregarCapa(capa: Capa): void;
  seleccionar(ids: string[]): void;
  deshacer(): void;
  rehacer(): void;
  editarEscena(receta: (d: Draft<Escena>) => void, etiqueta?: string): void;
  cambiarFormato(formato: Formato): void;
  setZoom(zoom: number): void;
  editarTexto(id: string | null): void;
  copiar(): void;
  pegar(): void;
  duplicar(): void;
  borrar(): void;
  mover(dx: number, dy: number): void;
  agrupar(): void;
  desagrupar(): void;
  ordenarZ(modo: ModoZ): void;
  alinear(modo: ModoAlinear): void;
  distribuir(eje: "h" | "v"): void;
  marcarGuardado(revision: number): void;
  vaciar(): void;
};

type Receta = (d: Draft<Escena>) => void | Escena;

const existentes = (escena: Escena, ids: string[]) => {
  const hay = new Set(escena.capas.map((c) => c.id));
  return [...new Set(ids)].filter((id) => hay.has(id));
};

// Quita de la selección las capas que ya van dentro de un grupo seleccionado.
function raicesDeSeleccion(escena: Escena, ids: string[]): string[] {
  const sel = new Set(ids);
  return ids.filter((id) => {
    for (let p = padreDe(escena, id); p; p = padreDe(escena, p)) if (sel.has(p)) return false;
    return true;
  });
}

export const useEditor = create<EstadoEditor>()((set, get) => {
  // Un paso de deshacer = un juego de parches de immer. Toda acción que cambia
  // la escena pasa por aquí.
  function registrar(receta: Receta, etiqueta: string) {
    const { escena, pasado, revision, seleccion } = get();
    if (!escena) return;
    const [nueva, adelante, atras] = produceWithPatches(escena, receta);
    if (adelante.length === 0) return;
    set({
      escena: nueva,
      pasado: [...pasado, { etiqueta, adelante, atras }].slice(-LIMITE_HISTORIA),
      futuro: [],
      revision: revision + 1,
      sucio: true,
      seleccion: existentes(nueva, seleccion),
    });
  }

  function viajar(desde: "pasado" | "futuro") {
    const s = get();
    const pila = s[desde];
    const paso = pila.at(-1);
    if (!s.escena || !paso) return;
    const atras = desde === "pasado";
    const escena = applyPatches(s.escena, atras ? paso.atras : paso.adelante);
    set({
      escena,
      pasado: atras ? s.pasado.slice(0, -1) : [...s.pasado, paso],
      futuro: atras ? [...s.futuro, paso] : s.futuro.slice(0, -1),
      revision: s.revision + 1,
      sucio: true,
      seleccion: existentes(escena, s.seleccion),
      editandoTexto: null,
    });
  }

  return {
    escena: null,
    seleccion: [],
    sucio: false,
    pasado: [],
    futuro: [],
    revision: 0,
    zoom: 1,
    editandoTexto: null,
    portapapeles: [],

    cargar: (escena) =>
      set({ escena, seleccion: [], sucio: false, pasado: [], futuro: [], revision: 0, editandoTexto: null }),

    aplicar: (ops, etiqueta = "Editar") => {
      const { escena } = get();
      if (!escena || ops.length === 0) return;
      // conCajasDeGrupo corre aplicarOps: si una op es inválida lanza aquí,
      // antes de registrar nada.
      const todas = conCajasDeGrupo(escena, ops);
      registrar((d) => {
        for (const op of todas) aplicarEnBorrador(d, op);
      }, etiqueta);
    },

    agregarCapa: (capa) => {
      get().aplicar([{ op: "add", capa }], "Agregar capa");
      set({ seleccion: [capa.id] });
    },

    seleccionar: (ids) => {
      const { escena } = get();
      set({ seleccion: escena ? existentes(escena, ids) : [] });
    },

    deshacer: () => viajar("pasado"),
    rehacer: () => viajar("futuro"),

    editarEscena: (receta, etiqueta = "Editar lienzo") => registrar(receta, etiqueta),

    cambiarFormato: (formato) => {
      const { escena } = get();
      if (!escena || escena.lienzo.formato === formato) return;
      registrar(() => reformatear(escena, formato), "Cambiar formato");
    },

    setZoom: (zoom) => set({ zoom: Math.min(4, Math.max(0.1, zoom)) }),
    editarTexto: (id) => set({ editandoTexto: id }),

    copiar: () => {
      const { escena, seleccion } = get();
      if (!escena || seleccion.length === 0) return;
      const ids = new Set(raicesDeSeleccion(escena, seleccion).flatMap((id) => [id, ...descendientes(escena, id)]));
      set({ portapapeles: structuredClone(escena.capas.filter((c) => ids.has(c.id))) });
    },

    pegar: () => {
      const { escena, portapapeles } = get();
      if (!escena || portapapeles.length === 0) return;
      const { ops, nuevos } = opsPegar(escena, portapapeles);
      get().aplicar(ops, "Pegar");
      set({ seleccion: nuevos });
    },

    duplicar: () => {
      const { escena, seleccion } = get();
      if (!escena || seleccion.length === 0) return;
      const { ops, nuevos } = opsDuplicar(escena, raicesDeSeleccion(escena, seleccion));
      get().aplicar(ops, "Duplicar");
      set({ seleccion: nuevos });
    },

    borrar: () => {
      const { escena, seleccion } = get();
      if (!escena) return;
      const porId = new Map(escena.capas.map((c) => [c.id, c]));
      const ops: Op[] = raicesDeSeleccion(escena, seleccion)
        .filter((id) => !porId.get(id)?.bloqueada)
        .map((id) => ({ op: "del", capa: id }));
      get().aplicar(ops, "Borrar");
    },

    mover: (dx, dy) => {
      const { escena, seleccion } = get();
      if (!escena || (dx === 0 && dy === 0)) return;
      get().aplicar(opsMover(escena, seleccion, dx, dy), "Mover");
    },

    agrupar: () => {
      const { escena, seleccion } = get();
      if (!escena) return;
      const r = opsAgrupar(escena, raicesDeSeleccion(escena, seleccion));
      if (!r) return;
      get().aplicar(r.ops, "Agrupar");
      set({ seleccion: [r.id] });
    },

    desagrupar: () => {
      const { escena, seleccion } = get();
      if (!escena || seleccion.length !== 1) return;
      const r = opsDesagrupar(escena, seleccion[0]);
      if (!r) return;
      get().aplicar(r.ops, "Desagrupar");
      set({ seleccion: r.hijos });
    },

    ordenarZ: (modo) => {
      const { escena, seleccion } = get();
      if (escena) get().aplicar(opsZ(escena, seleccion, modo), "Orden");
    },

    alinear: (modo) => {
      const { escena, seleccion } = get();
      if (escena) get().aplicar(opsAlinear(escena, seleccion, modo), "Alinear");
    },

    distribuir: (eje) => {
      const { escena, seleccion } = get();
      if (escena) get().aplicar(opsDistribuir(escena, seleccion, eje), "Distribuir");
    },

    marcarGuardado: (revision) => set({ sucio: get().revision !== revision }),

    vaciar: () => set(useEditor.getInitialState(), true),
  };
});
