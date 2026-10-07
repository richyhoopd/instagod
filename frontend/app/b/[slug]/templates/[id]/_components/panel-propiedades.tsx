"use client";

import { useState, type ReactNode } from "react";
import { Label } from "@/components/ui/label";
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

export function CampoNumero({
  etiqueta,
  valor,
  onCommit,
  min,
  max,
  deshabilitado = false,
}: {
  etiqueta: string;
  valor: number;
  onCommit: (n: number) => void;
  min?: number;
  max?: number;
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
    let v = n;
    if (min !== undefined) v = Math.max(min, v);
    if (max !== undefined) v = Math.min(max, v);
    setTexto(String(v));
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
        }}
      />
    </label>
  );
}

export function CampoColor({
  etiqueta,
  valor,
  tokens,
  colorMarca,
  onCommit,
}: {
  etiqueta: string;
  valor: string;
  tokens: Tokens;
  colorMarca: string;
  onCommit: (v: string) => void;
}) {
  const nombres = Object.keys(tokens.colores);
  if (!nombres.includes("marca")) nombres.push("marca");
  const esToken = valor.startsWith("token:");
  const resuelto = resolverColor(valor, tokens, colorMarca);
  const [propio, setPropio] = useState(HEX.test(resuelto) ? resuelto : "#000000");

  return (
    <div className="flex flex-col gap-1">
      <Label className="text-xs text-muted-foreground">
        {etiqueta}
        <select
          aria-label={etiqueta}
          className={SELECT}
          value={esToken ? valor : "propio"}
          onChange={(ev) => onCommit(ev.target.value === "propio" ? propio : ev.target.value)}
        >
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
          value={HEX.test(valor) ? valor : propio}
          className="h-8 w-full cursor-pointer rounded-md border"
          onChange={(ev) => setPropio(ev.target.value)}
          onBlur={() => propio !== valor && onCommit(propio)}
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
  opciones,
  onCambio,
}: {
  etiqueta: string;
  valor: T;
  opciones: { valor: T; nombre: string }[];
  onCambio: (v: T) => void;
}) {
  return (
    <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
      {etiqueta}
      <select
        aria-label={etiqueta}
        className={SELECT}
        value={String(valor)}
        onChange={(ev) => {
          const o = opciones.find((x) => String(x.valor) === ev.target.value);
          if (o) onCambio(o.valor);
        }}
      >
        {opciones.map((o) => (
          <option key={String(o.valor)} value={String(o.valor)}>
            {o.nombre}
          </option>
        ))}
      </select>
    </Label>
  );
}

export function PanelPropiedades({ colorMarca }: { colorMarca: string }) {
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

  return (
    <div key={c.id}>
      <Seccion titulo={c.nombre}>
        <div className="grid grid-cols-2 gap-2">
          <CampoNumero etiqueta="X" valor={c.x} onCommit={(n) => st().mover(Math.round(n) - c.x, 0)} />
          <CampoNumero etiqueta="Y" valor={c.y} onCommit={(n) => st().mover(0, Math.round(n) - c.y)} />
          <CampoNumero etiqueta="Ancho" valor={c.w} min={1} deshabilitado={grupo} onCommit={(n) => set("w", Math.round(n))} />
          <CampoNumero etiqueta="Alto" valor={c.h} min={1} deshabilitado={grupo} onCommit={(n) => set("h", Math.round(n))} />
          <CampoNumero etiqueta="Rotación" valor={c.rot} deshabilitado={grupo} onCommit={(n) => set("rot", n)} />
          <CampoNumero
            etiqueta="Opacidad"
            valor={Math.round(c.opacity * 100)}
            min={0}
            max={100}
            onCommit={(n) => set("opacity", n / 100)}
          />
        </div>
      </Seccion>
      <PropiedadesDeTipo capa={c} tokens={tokens} colorMarca={colorMarca} set={set} />
    </div>
  );
}

function PropiedadesDeTipo({
  capa: c,
  tokens,
  colorMarca,
  set,
}: {
  capa: Capa;
  tokens: Tokens;
  colorMarca: string;
  set: (ruta: string, valor: unknown, etiqueta?: string) => void;
}) {
  if (c.tipo === "text") {
    const e = c.estilo;
    return (
      <Seccion titulo="Texto">
        <Label className="flex flex-col items-stretch gap-1 text-xs text-muted-foreground">
          Fuente
          <input
            aria-label="Fuente"
            defaultValue={e.fontFamily}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground"
            onBlur={(ev) => {
              const v = ev.target.value.trim();
              if (v && v !== e.fontFamily) set("estilo.fontFamily", v);
            }}
          />
        </Label>
        <div className="grid grid-cols-2 gap-2">
          <CampoNumero etiqueta="Tamaño" valor={e.fontSize} min={6} max={400} onCommit={(n) => set("estilo.fontSize", n)} />
          <Selector
            etiqueta="Peso"
            valor={e.fontWeight}
            opciones={PESOS.map((p) => ({ valor: p, nombre: String(p) }))}
            onCambio={(p) => set("estilo.fontWeight", p)}
          />
          <CampoNumero
            etiqueta="Interlineado"
            valor={e.lineHeight}
            min={0.5}
            max={3}
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
            onCambio={(v) => set("estilo.textAlign", v)}
          />
        </div>
        <CampoColor
          etiqueta="Color"
          valor={e.color}
          tokens={tokens}
          colorMarca={colorMarca}
          onCommit={(v) => set("estilo.color", v)}
        />
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
          onCommit={(v) => set("estilo.fill", v)}
        />
        <CampoNumero etiqueta="Radio" valor={c.estilo.radius ?? 0} min={0} onCommit={(n) => set("estilo.radius", n)} />
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
          onCambio={(v) => set("ajuste", v)}
        />
      </Seccion>
    );
  }
  return null;
}
