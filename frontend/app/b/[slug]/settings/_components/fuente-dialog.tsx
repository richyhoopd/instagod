"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ApiError } from "@/lib/api";
import { useCrearSource, type SourceKind } from "@/hooks/use-sources";

interface CampoConfig {
  key: string;
  label: string;
  placeholder?: string;
}

// Campos por provider: no hay un esquema publicado en constraints.md para
// `config`, así que se infiere de src/image_sources.py / src/news_sources.py
// (nombre de los parámetros más comunes). Si el backend espera otras claves,
// ajustar aquí — el resto de la UI (lista, orden, activar, correr) no
// depende de esta forma.
const PROVIDERS: Record<SourceKind, { value: string; label: string; campos: CampoConfig[] }[]> = {
  imagen: [
    { value: "pexels", label: "Pexels", campos: [{ key: "query", label: "Búsqueda" }] },
    {
      value: "pinterest",
      label: "Pinterest",
      campos: [
        { key: "query", label: "Búsqueda" },
        { key: "tablero", label: "Tablero (opcional)" },
      ],
    },
    { value: "banco", label: "Banco de fotos", campos: [] },
    { value: "covers", label: "Covers", campos: [{ key: "query", label: "Búsqueda (opcional)" }] },
    { value: "carpeta", label: "Carpeta local", campos: [{ key: "ruta", label: "Ruta" }] },
    { value: "manual", label: "Manual", campos: [] },
  ],
  info: [
    { value: "rss", label: "RSS", campos: [{ key: "url", label: "URL del feed" }] },
    {
      value: "newsapi",
      label: "NewsAPI",
      campos: [
        { key: "query", label: "Búsqueda" },
        { key: "pais", label: "País (opcional)" },
      ],
    },
    {
      value: "ig_accounts",
      label: "Cuentas de Instagram",
      campos: [{ key: "cuentas", label: "Handles, separados por coma" }],
    },
  ],
};

export function FuenteDialog({ slug, kind }: { slug: string; kind: SourceKind }) {
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState(PROVIDERS[kind][0]?.value ?? "");
  const [nombre, setNombre] = useState("");
  const [valores, setValores] = useState<Record<string, string>>({});
  const crear = useCrearSource(slug);

  const opciones = PROVIDERS[kind];
  const actual = opciones.find((o) => o.value === provider);

  function resetear() {
    setProvider(opciones[0]?.value ?? "");
    setNombre("");
    setValores({});
  }

  async function guardar() {
    if (!nombre.trim()) {
      toast.error("Ponle un nombre a la fuente");
      return;
    }
    try {
      await crear.mutateAsync({
        kind,
        provider,
        nombre: nombre.trim(),
        config: Object.fromEntries(Object.entries(valores).filter(([, v]) => v.trim() !== "")),
      });
      toast.success("Fuente agregada");
      setOpen(false);
      resetear();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo agregar la fuente");
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(v) => {
        setOpen(v);
        if (!v) resetear();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant="outline">
          <Plus className="size-4" />
          Agregar
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Nueva fuente de {kind === "imagen" ? "imagen" : "información"}</DialogTitle>
          <DialogDescription>Elige el proveedor y completa su configuración.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Proveedor</Label>
            <Select
              value={provider}
              onValueChange={(v) => {
                setProvider(v);
                setValores({});
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {opciones.map((o) => (
                  <SelectItem key={o.value} value={o.value}>
                    {o.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="fuente-nombre">Nombre</Label>
            <Input id="fuente-nombre" value={nombre} onChange={(e) => setNombre(e.target.value)} />
          </div>
          {actual?.campos.map((campo) => (
            <div key={campo.key} className="space-y-2">
              <Label htmlFor={`fuente-${campo.key}`}>{campo.label}</Label>
              <Input
                id={`fuente-${campo.key}`}
                placeholder={campo.placeholder}
                value={valores[campo.key] ?? ""}
                onChange={(e) => setValores((prev) => ({ ...prev, [campo.key]: e.target.value }))}
              />
            </div>
          ))}
        </div>
        <DialogFooter>
          <Button onClick={guardar} disabled={crear.isPending}>
            {crear.isPending ? "Agregando..." : "Agregar"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
