"use client";

import { useState, type ReactNode } from "react";
import { Label } from "@/components/ui/label";
import type { ContratoPlantilla } from "@/hooks/use-disenos";
import { resolverColor, type Capa, type Formato, type Op, type Tokens } from "@/lib/escena";
import { useEditor } from "@/stores/editor";

const SELECT =
  "h-8 w-full rounded-md border border-input bg-background px-2 text-sm shadow-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50";
const HEX = /^#[0-9a-f]{6}$/i;

const FORMATOS: { valor: Formato; nombre: string }[] = [
  { valor: "4x5", nombre: "Cuadrada alta (4:5)" },
  { valor: "1x1", nombre: "Cuadrada (1:1)" },
  { valor: "9x16", nombre: "Vertical (9:16)" },
];
const PESOS = [300, 400, 500, 600, 700, 800, 900];

type Campos = { texto: string[]; imagen: string[] };

const CAMPOS_IMAGEN_BASE = ["imagen", "logo"];
const NO_ES_TEXTO = new Set([...CAMPOS_IMAGEN_BASE, "color_marca"]);

// Qué dato del contrato puede llenar cada tipo de capa.
export function camposDeContrato(contrato: ContratoPlantilla): Campos {
  return {
    texto: [
      ...contrato.base.filter((c) => !NO_ES_TEXTO.has(c)),
      ...contrato.extras.filter((x) => x.tipo !== "imagen").map((x) => x.id),
    ],
    imagen: [
      ...contrato.base.filter((c) => CAMPOS_IMAGEN_BASE.includes(c)),
      ...contrato.extras.filter((x) => x.tipo === "imagen").map((x) => x.id),
    ],
  };
}

// D16: sombra como preset sobre `filter`. Un valor fuera de la lista se
// respeta y se muestra como «Personalizada».
const SOMBRAS = [
  { valor: "none", nombre: "Ninguna" },
  { valor: "drop-shadow(0 8px 16px rgba(0,0,0,.25))", nombre: "Suave" },
  { valor: "drop-shadow(0 16px 32px rgba(0,0,0,.3))", nombre: "Media" },
  { valor: "drop-shadow(0 24px 48px rgba(0,0,0,.4))", nombre: "Fuerte" },
];
const MEZCLAS = [
  { valor: "normal", nombre: "Normal" },
  { valor: "multiply", nombre: "Multiplicar" },
  { valor: "screen", nombre: "Pantalla" },
  { valor: "overlay", nombre: "Superponer" },
  { valor: "darken", nombre: "Oscurecer" },
  { valor: "lighten", nombre: "Aclarar" },
  { valor: "soft-light", nombre: "Luz suave" },
  { valor: "difference", nombre: "Diferencia" },
];

export function CampoNumero({
  etiqueta,
  valor,
  onCommit,
  min,
  max,
  entero = false,
  deshabilitado = false,
}: {
  etiqueta: string;
  valor: number;
  onCommit: (n: number) => void;
  min?: number;
  max?: number;
  entero?: boolean;
  deshabilitado?: boolean;
}) {
  const [texto, setTexto] = useState(String(valor));
  const [previo, setPrevio] = useState(valor);
  // Si el store cambia (deshacer, arrastre), el campo lo sigue. Patrón de
  // «estado derivado de props» de React: se ajusta durante el render.
  if (previo !== valor) {
    setPrevio(valor);
    setTexto(String(valor));
  }

  const confirmar = () => {
    const n = Number(texto);
    if (texto.trim() === "" || !Number.isFinite(n)) return setTexto(String(valor));
    let v = entero ? Math.round(n) : n;
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    // Tras commitear, el campo muestra el valor REAL del store: si el store
    // lo acota o lo ignora (capa bloqueada) la prop no cambia y esto lo deja
    // en `valor`; si cambia, el estado derivado de arriba lo sigue.
    setTexto(String(valor));
    if (v !== valor) onCommit(v);
  };

  return (
    <label className="flex flex-col gap-1 text-xs text-muted-foreground">
      {etiqueta}
      <input
        type="number"
        aria-label={etiqueta}
        value={texto}
        disabled={deshabilitado}
        className="h-8 w-full rounded-md border border-input bg-background px-2 text-sm text-foreground tabular-nums disabled:opacity-50"
        onChange={(ev) => setTexto(ev.target.value)}
        onBlur={confirmar}
        onKeyDown={(ev) => {
          if (ev.key === "Enter") confirmar();
          if (ev.key === "Escape") setTexto(String(valor));
        }}
      />
    </label>
  );
}

const FUENTE_INVALIDA = /['"\\]/;
// Misma regex que _TRACKING en src/plantillas/escena.py.
const TRACKING_VALIDO = /^-?\d{1,3}(\.\d{1,3})?(em|px)$/;

function CampoTracking({ valor, deshabilitado, onCommit }: { valor: string; deshabilitado: boolean; onCommit: (v: string | undefined) => void }) {
  const [texto, setTexto] = useState(valor);
  const [previo, setPrevio] = useState(valor);
  if (previo !== valor) {
    setPrevio(valor);
    setTexto(valor);
  }
  const confirmar = () => {
    const v = texto.trim();
    if (v !== "" && !TRACKING_VALIDO.test(v)) return setTexto(valor);
    setTexto(v);
    if (v !== valor) onCommit(v || undefined);
  };
  return (
    <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
      Tracking
      <input
        aria-label="Tracking"
        value={texto}
        placeholder="-0.02em"
        disabled={deshabilitado}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground disabled:opacity-50"
        onChange={(ev) => setTexto(ev.target.value)}
        onBlur={confirmar}
        onKeyDown={(ev) => {
          if (ev.key === "Enter") confirmar();
          if (ev.key === "Escape") setTexto(valor);
        }}
      />
    </Label>
  );
}

function CampoFuente({ valor, deshabilitado, onCommit }: { valor: string; deshabilitado: boolean; onCommit: (v: string) => void }) {
  const [texto, setTexto] = useState(valor);
  const [previo, setPrevio] = useState(valor);
  if (previo !== valor) {
    setPrevio(valor);
    setTexto(valor);
  }
  const confirmar = () => {
    const v = texto.trim();
    if (!v || FUENTE_INVALIDA.test(v)) return setTexto(valor);
    setTexto(v);
    if (v !== valor) onCommit(v);
  };
  return (
    <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
      Fuente
      <input
        aria-label="Fuente"
        value={texto}
        disabled={deshabilitado}
        className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground disabled:opacity-50"
        onChange={(ev) => setTexto(ev.target.value)}
        onBlur={confirmar}
        onKeyDown={(ev) => {
          if (ev.key === "Enter") confirmar();
          if (ev.key === "Escape") setTexto(valor);
        }}
      />
    </Label>
  );
}

export function CampoColor({
  etiqueta,
  valor,
  tokens,
  colorMarca,
  onCommit,
  deshabilitado = false,
}: {
  etiqueta: string;
  valor: string;
  tokens: Tokens;
  colorMarca: string;
  onCommit: (v: string) => void;
  deshabilitado?: boolean;
}) {
  const nombres = Object.keys(tokens.colores);
  if (!nombres.includes("marca")) nombres.push("marca");
  const esToken = valor.startsWith("token:");
  const resuelto = resolverColor(valor, tokens, colorMarca);
  const hexActual = HEX.test(resuelto) ? resuelto : null;
  const [propio, setPropio] = useState<string | null>(hexActual);
  const [hayCambio, setHayCambio] = useState(false);
  const [previo, setPrevio] = useState(valor);
  // Si el valor cambia por fuera (deshacer), «propio» lo sigue.
  if (previo !== valor) {
    setPrevio(valor);
    setPropio(hexActual);
    setHayCambio(false);
  }

  return (
    <div className="flex flex-col gap-1">
      <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
        {etiqueta}
        <select
          aria-label={etiqueta}
          className={SELECT}
          value={esToken ? valor : "propio"}
          disabled={deshabilitado}
          onChange={(ev) => {
            if (ev.target.value !== "propio") return onCommit(ev.target.value);
            if (propio) onCommit(propio);
          }}
        >
          {esToken && !nombres.includes(valor.slice(6)) && <option value={valor}>{valor.slice(6)}</option>}
          {nombres.map((k) => (
            <option key={k} value={`token:${k}`}>
              {k}
            </option>
          ))}
          <option value="propio">Color propio</option>
        </select>
      </Label>
      {!esToken && (
        <input
          type="color"
          aria-label={`${etiqueta} propio`}
          value={HEX.test(valor) ? valor : (propio ?? "#000000")}
          disabled={deshabilitado}
          className="h-8 w-full cursor-pointer rounded-md border disabled:opacity-50"
          onChange={(ev) => {
            setPropio(ev.target.value);
            setHayCambio(true);
          }}
          onBlur={() => {
            if (hayCambio && propio && propio !== valor) onCommit(propio);
            setHayCambio(false);
          }}
        />
      )}
    </div>
  );
}

function Seccion({ titulo, children }: { titulo: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2 border-b p-3">
      <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{titulo}</h3>
      {children}
    </section>
  );
}

function Selector<T extends string | number>({
  etiqueta,
  valor,
  opciones: opcionesBase,
  onCambio,
  deshabilitado = false,
}: {
  etiqueta: string;
  valor: T;
  opciones: { valor: T; nombre: string; deshabilitada?: string }[];
  onCambio: (v: T) => void;
  deshabilitado?: boolean;
}) {
  const opciones = opcionesBase.some((o) => o.valor === valor)
    ? opcionesBase
    : [{ valor, nombre: String(valor) }, ...opcionesBase];
  return (
    <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
      {etiqueta}
      <select
        aria-label={etiqueta}
        className={SELECT}
        value={String(valor)}
        disabled={deshabilitado}
        onChange={(ev) => {
          const o = opciones.find((x) => String(x.valor) === ev.target.value);
          if (o) onCambio(o.valor);
        }}
      >
        {opciones.map((o) => (
          <option key={String(o.valor)} value={String(o.valor)} disabled={!!o.deshabilitada} title={o.deshabilitada}>
            {o.nombre}
          </option>
        ))}
      </select>
    </Label>
  );
}

export function PanelPropiedades({ colorMarca, campos }: { colorMarca: string; campos?: Campos }) {
  const escena = useEditor((s) => s.escena);
  const seleccion = useEditor((s) => s.seleccion);
  if (!escena) return null;
  const st = useEditor.getState;
  const tokens = escena.tokens;

  if (seleccion.length === 0) {
    const fondo = escena.lienzo.fondo;
    return (
      <Seccion titulo="Lienzo">
        <Selector
          etiqueta="Formato"
          valor={escena.lienzo.formato}
          opciones={FORMATOS}
          onCambio={(f) => st().cambiarFormato(f)}
        />
        {fondo.tipo === "color" ? (
          <CampoColor
            etiqueta="Fondo"
            valor={fondo.valor}
            tokens={tokens}
            colorMarca={colorMarca}
            onCommit={(v) =>
              st().editarEscena((d) => {
                d.lienzo.fondo = { tipo: "color", valor: v };
              }, "Fondo")
            }
          />
        ) : (
          <p className="text-xs text-muted-foreground">El fondo es {fondo.tipo === "imagen" ? "una imagen" : "un degradado"}.</p>
        )}
      </Seccion>
    );
  }

  if (seleccion.length > 1) {
    return (
      <Seccion titulo="Selección">
        <p className="text-sm">{seleccion.length} capas seleccionadas</p>
      </Seccion>
    );
  }

  const c = escena.capas.find((x) => x.id === seleccion[0]);
  if (!c) return null;
  const set = (ruta: string, valor: unknown, etiqueta = "Propiedades") =>
    st().aplicar([{ op: "set", capa: c.id, ruta, valor } satisfies Op], etiqueta);
  const grupo = c.tipo === "group";
  const bloq = c.bloqueada;

  return (
    <div key={c.id}>
      <Seccion titulo={c.nombre}>
        <div className="grid grid-cols-2 gap-2">
          <CampoNumero etiqueta="X" valor={c.x} entero deshabilitado={bloq} onCommit={(n) => st().mover(n - c.x, 0)} />
          <CampoNumero etiqueta="Y" valor={c.y} entero deshabilitado={bloq} onCommit={(n) => st().mover(0, n - c.y)} />
          <CampoNumero etiqueta="Ancho" valor={c.w} min={1} entero deshabilitado={grupo || bloq} onCommit={(n) => set("w", n)} />
          <CampoNumero etiqueta="Alto" valor={c.h} min={1} entero deshabilitado={grupo || bloq} onCommit={(n) => set("h", n)} />
          <CampoNumero etiqueta="Rotación" valor={c.rot} deshabilitado={grupo || bloq} onCommit={(n) => set("rot", n)} />
          <CampoNumero
            etiqueta="Opacidad"
            valor={Math.round(c.opacity * 100)}
            min={0}
            max={100}
            entero
            deshabilitado={bloq}
            onCommit={(n) => set("opacity", n / 100)}
          />
        </div>
      </Seccion>
      <PropiedadesDeTipo capa={c} tokens={tokens} colorMarca={colorMarca} set={set} bloq={bloq} />
      {campos && <Dato capa={c} campos={campos} bloq={bloq} />}
      <Efectos capa={c} set={set} bloq={bloq} />
    </div>
  );
}

function PropiedadesDeTipo({
  capa: c,
  tokens,
  colorMarca,
  set,
  bloq,
}: {
  bloq: boolean;
  capa: Capa;
  tokens: Tokens;
  colorMarca: string;
  set: (ruta: string, valor: unknown, etiqueta?: string) => void;
}) {
  if (c.tipo === "text") {
    const e = c.estilo;
    return (
      <Seccion titulo="Texto">
        <CampoFuente valor={e.fontFamily} deshabilitado={bloq} onCommit={(v) => set("estilo.fontFamily", v)} />
        <div className="grid grid-cols-2 gap-2">
          <CampoNumero etiqueta="Tamaño" valor={e.fontSize} min={6} max={400} deshabilitado={bloq} onCommit={(n) => set("estilo.fontSize", n)} />
          <Selector
            etiqueta="Peso"
            valor={e.fontWeight}
            opciones={PESOS.map((p) => ({ valor: p, nombre: String(p) }))}
            deshabilitado={bloq}
            onCambio={(p) => set("estilo.fontWeight", p)}
          />
          <CampoNumero
            etiqueta="Interlineado"
            valor={e.lineHeight}
            min={0.5}
            max={3}
            deshabilitado={bloq}
            onCommit={(n) => set("estilo.lineHeight", n)}
          />
          <Selector
            etiqueta="Alineación"
            valor={e.textAlign}
            opciones={[
              { valor: "left", nombre: "Izquierda" },
              { valor: "center", nombre: "Centro" },
              { valor: "right", nombre: "Derecha" },
              { valor: "justify", nombre: "Justificado" },
            ]}
            deshabilitado={bloq}
            onCambio={(v) => set("estilo.textAlign", v)}
          />
        </div>
        <CampoColor
          etiqueta="Color"
          valor={e.color}
          tokens={tokens}
          colorMarca={colorMarca}
          deshabilitado={bloq}
          onCommit={(v) => set("estilo.color", v)}
        />
        <CampoTracking valor={e.letterSpacing ?? ""} deshabilitado={bloq} onCommit={(v) => set("estilo.letterSpacing", v)} />
      </Seccion>
    );
  }
  if (c.tipo === "shape") {
    return (
      <Seccion titulo="Forma">
        <CampoColor
          etiqueta="Relleno"
          valor={c.estilo.fill}
          tokens={tokens}
          colorMarca={colorMarca}
          deshabilitado={bloq}
          onCommit={(v) => set("estilo.fill", v)}
        />
        <CampoNumero etiqueta="Radio" valor={c.estilo.radius ?? 0} min={0} deshabilitado={bloq} onCommit={(n) => set("estilo.radius", n)} />
        <CampoNumero
          etiqueta="Borde"
          valor={c.estilo.borderWidth ?? 0}
          min={0}
          max={200}
          deshabilitado={bloq}
          onCommit={(n) => set("estilo.borderWidth", n)}
        />
        <CampoColor
          etiqueta="Color de borde"
          valor={c.estilo.borderColor ?? "#000000"}
          tokens={tokens}
          colorMarca={colorMarca}
          deshabilitado={bloq}
          onCommit={(v) => set("estilo.borderColor", v)}
        />
      </Seccion>
    );
  }
  if (c.tipo === "image" || c.tipo === "video" || c.tipo === "svg") {
    return (
      <Seccion titulo={c.tipo === "video" ? "Video" : "Imagen"}>
        <Selector
          etiqueta="Ajuste"
          valor={c.ajuste}
          opciones={[
            { valor: "cover", nombre: "Llenar" },
            { valor: "contain", nombre: "Contener" },
          ]}
          deshabilitado={bloq}
          onCambio={(v) => set("ajuste", v)}
        />
      </Seccion>
    );
  }
  return null;
}

function Dato({ capa: c, campos, bloq }: { capa: Capa; campos: Campos; bloq: boolean }) {
  if (c.tipo !== "text" && c.tipo !== "image" && c.tipo !== "video") return null;
  const lista = c.tipo === "text" ? campos.texto : campos.imagen;
  const actual = c.campo ?? "";
  const sinSrc = (c.tipo === "image" || c.tipo === "video") && !c.src;
  // Un campo que ya no está en el contrato se sigue mostrando para no perderlo.
  const opciones = [
    {
      valor: "",
      nombre: "Ninguno",
      // El backend exige src cuando la capa no tiene campo: sin src, desvincular la deja inválida.
      deshabilitada: sinSrc ? "Esta capa no tiene src propio: elige un dato o súbele una imagen primero." : undefined,
    },
    ...lista.map((x) => ({ valor: x, nombre: x })),
    ...(actual && !lista.includes(actual) ? [{ valor: actual, nombre: `${actual} (no está en el contrato)` }] : []),
  ];

  function cambiar(v: string) {
    const ops: Op[] = [{ op: "set", capa: c.id, ruta: "campo", valor: v || null }];
    if (c.tipo === "text" && v && (c.estilo.spans?.length ?? 0) > 0) {
      ops.push({ op: "set", capa: c.id, ruta: "estilo.spans", valor: [] });
    }
    if (c.tipo === "text" && !v && c.resaltar) {
      ops.push({ op: "set", capa: c.id, ruta: "resaltar", valor: false });
    }
    useEditor.getState().aplicar(ops, "Dato");
  }

  return (
    <Seccion titulo="Dato">
      <Selector etiqueta="Dato" valor={actual} opciones={opciones} deshabilitado={bloq} onCambio={cambiar} />
    </Seccion>
  );
}

function Efectos({
  capa: c,
  set,
  bloq,
}: {
  capa: Capa;
  set: (ruta: string, valor: unknown, etiqueta?: string) => void;
  bloq: boolean;
}) {
  if (c.tipo !== "image" && c.tipo !== "video" && c.tipo !== "svg" && c.tipo !== "shape") return null;
  const filtro = c.estilo.filter ?? "none";
  const sombras = SOMBRAS.some((s) => s.valor === filtro) ? SOMBRAS : [...SOMBRAS, { valor: filtro, nombre: "Personalizada" }];
  return (
    <Seccion titulo="Efectos">
      <Selector
        etiqueta="Mezcla"
        valor={c.estilo.mixBlendMode ?? "normal"}
        opciones={MEZCLAS}
        deshabilitado={bloq}
        onCambio={(v) => set("estilo.mixBlendMode", v, "Mezcla")}
      />
      <Selector
        etiqueta="Sombra"
        valor={filtro}
        opciones={sombras}
        deshabilitado={bloq}
        onCambio={(v) => set("estilo.filter", v, "Sombra")}
      />
    </Seccion>
  );
}
