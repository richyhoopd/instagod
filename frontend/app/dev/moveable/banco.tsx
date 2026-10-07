"use client";

import { useRef, useState } from "react";
import Moveable from "react-moveable";
import Selecto from "react-selecto";

const INICIAL = [
  { id: "a", x: 40, y: 40 },
  { id: "b", x: 400, y: 40 },
  { id: "c", x: 40, y: 400 },
];
const ESCALA = 0.5;

// Banco mínimo: el mismo acomodo que el editor (escenario escalado,
// Moveable como hermano y Selecto sobre el marco). Solo para el smoke test.
export function Banco() {
  const [cajas, setCajas] = useState(INICIAL);
  const [sel, setSel] = useState<string[]>([]);
  const [ultimo, setUltimo] = useState<number[] | null>(null);
  const [marco, setMarco] = useState<HTMLDivElement | null>(null);
  const moveableRef = useRef<Moveable>(null);
  const traslado = useRef<number[] | null>(null);

  return (
    <div style={{ padding: 40 }}>
      <div id="marco" ref={setMarco} style={{ position: "relative", width: 600, height: 600, background: "#eee" }}>
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            width: 1200,
            height: 1200,
            transform: `scale(${ESCALA})`,
            transformOrigin: "0 0",
          }}
        >
          {cajas.map((c) => (
            <div
              key={c.id}
              data-id={c.id}
              className="capa"
              style={{
                position: "absolute",
                left: c.x,
                top: c.y,
                width: 200,
                height: 200,
                background: sel.includes(c.id) ? "#f90" : "#09f",
              }}
            />
          ))}
        </div>
        <Moveable
          ref={moveableRef}
          target={sel.map((id) => `[data-id="${id}"]`)}
          draggable
          onDragStart={() => {
            traslado.current = null;
          }}
          onDrag={(e) => {
            e.target.style.transform = e.transform;
            traslado.current = e.beforeTranslate;
          }}
          onDragEnd={(e) => {
            const t = traslado.current;
            (e.target as HTMLElement).style.transform = "";
            if (!t) return;
            const id = e.target.getAttribute("data-id");
            setUltimo(t);
            setCajas((cs) => cs.map((c) => (c.id === id ? { ...c, x: Math.round(c.x + t[0]), y: Math.round(c.y + t[1]) } : c)));
          }}
        />
      </div>
      {marco && (
        <Selecto
          dragContainer={marco}
          selectableTargets={[".capa"]}
          hitRate={0}
          selectByClick
          selectFromInside={false}
          toggleContinueSelect={["shift"]}
          onDragStart={(e) => {
            const t = e.inputEvent.target as Element;
            if (moveableRef.current?.isMoveableElement(t) || sel.some((id) => t.closest(`[data-id="${id}"]`))) e.stop();
          }}
          onSelectEnd={(e) => {
            setSel(e.selected.map((el) => el.getAttribute("data-id")!));
            if (e.isDragStart) {
              e.inputEvent.preventDefault();
              moveableRef.current?.waitToChangeTarget().then(() => moveableRef.current?.dragStart(e.inputEvent));
            }
          }}
        />
      )}
      <pre data-testid="estado">{JSON.stringify({ sel, cajas, ultimo })}</pre>
    </div>
  );
}
