"use client";

import { useState } from "react";
import { toast } from "sonner";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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
import { fuenteLabel } from "@/lib/fuentes";
import { useCrearSource, type SourceKind } from "@/hooks/use-sources";

// src/fuentes.py::PROVIDERS_IMAGEN/PROVIDERS_INFO — catálogo real por kind.
// ig_accounts es de kind "imagen" (alimenta la cascada de imágenes vía
// scraping de posts), no "info". "manual" no existe como provider.
const PROVIDERS: Record<SourceKind, string[]> = {
  imagen: ["carpeta", "ig_accounts", "pinterest", "pexels", "unsplash", "banco", "covers"],
  info: ["rss", "newsapi"],
};

// Providers sin esquema de config estricto en el backend (validar_config
// los deja pasar con cualquier dict); se dejan sin campos por ahora, el
// resto (rss/ig_accounts/newsapi) sí se valida server-side y se construye
// a mano abajo.
const SIN_CONFIG_ESTRICTA = new Set(["carpeta", "pinterest", "pexels", "unsplash", "banco", "covers"]);

interface EstadoConfig {
  urls: string; // rss: una URL por línea → config.urls: string[]
  cuentas: string; // ig_accounts: @handles separados por coma/espacio → config.cuentas: string[]
  maxPorCuenta: string;
  cadaHoras: string;
  query: string; // newsapi
  idioma: string;
  pais: string;
}

const VACIO: EstadoConfig = {
  urls: "",
  cuentas: "",
  maxPorCuenta: "",
  cadaHoras: "",
  query: "",
  idioma: "",
  pais: "",
};

function normalizaCuentas(v: string): string[] {
  return v
    .split(/[\s,]+/)
    .map((c) => c.trim())
    .filter(Boolean)
    .map((c) => (c.startsWith("@") ? c : `@${c}`));
}

function construirConfig(provider: string, e: EstadoConfig): Record<string, unknown> | undefined {
  if (provider === "rss") {
    const urls = e.urls.split("\n").map((u) => u.trim()).filter(Boolean);
    return urls.length > 0 ? { urls } : undefined;
  }
  if (provider === "ig_accounts") {
    const cuentas = normalizaCuentas(e.cuentas);
    const config: Record<string, unknown> = {};
    if (cuentas.length > 0) config.cuentas = cuentas;
    if (e.maxPorCuenta.trim()) config.max_por_cuenta = Number(e.maxPorCuenta);
    if (e.cadaHoras.trim()) config.cada_horas = Number(e.cadaHoras);
    return config;
  }
  if (provider === "newsapi") {
    const config: Record<string, unknown> = {};
    if (e.query.trim()) config.query = e.query.trim();
    if (e.idioma.trim()) config.idioma = e.idioma.trim();
    if (e.pais.trim()) config.pais = e.pais.trim();
    return config;
  }
  return undefined;
}

function validar(provider: string, e: EstadoConfig): string | null {
  if (provider === "rss" && !e.urls.split("\n").some((u) => u.trim())) {
    return "Agrega al menos una URL de feed";
  }
  if (provider === "ig_accounts" && normalizaCuentas(e.cuentas).length === 0) {
    return "Agrega al menos una cuenta (@handle)";
  }
  if (provider === "newsapi" && !e.query.trim()) {
    return "La búsqueda es requerida";
  }
  return null;
}

export function FuenteDialog({ slug, kind }: { slug: string; kind: SourceKind }) {
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState(PROVIDERS[kind][0]);
  const [config, setConfig] = useState<EstadoConfig>(VACIO);
  const crear = useCrearSource(slug);

  const opciones = PROVIDERS[kind];

  function resetear() {
    setProvider(opciones[0]);
    setConfig(VACIO);
  }

  async function guardar() {
    const error = validar(provider, config);
    if (error) {
      toast.error(error);
      return;
    }
    try {
      await crear.mutateAsync({ kind, provider, config: construirConfig(provider, config) });
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
                setConfig(VACIO);
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {opciones.map((o) => (
                  <SelectItem key={o} value={o}>
                    {fuenteLabel(o)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {provider === "rss" && (
            <div className="space-y-2">
              <Label htmlFor="fuente-urls">URLs del feed (una por línea)</Label>
              <Textarea
                id="fuente-urls"
                rows={3}
                value={config.urls}
                onChange={(e) => setConfig((prev) => ({ ...prev, urls: e.target.value }))}
                placeholder={"https://ejemplo.com/feed.xml"}
              />
            </div>
          )}

          {provider === "ig_accounts" && (
            <>
              <div className="space-y-2">
                <Label htmlFor="fuente-cuentas">Cuentas (@handle, separadas por coma)</Label>
                <Input
                  id="fuente-cuentas"
                  placeholder="@cuenta1, @cuenta2"
                  value={config.cuentas}
                  onChange={(e) => setConfig((prev) => ({ ...prev, cuentas: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="fuente-max">Máx. por cuenta (≤50, opcional)</Label>
                  <Input
                    id="fuente-max"
                    type="number"
                    min={1}
                    max={50}
                    value={config.maxPorCuenta}
                    onChange={(e) => setConfig((prev) => ({ ...prev, maxPorCuenta: e.target.value }))}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="fuente-horas">Cada horas (≥6, opcional)</Label>
                  <Input
                    id="fuente-horas"
                    type="number"
                    min={6}
                    value={config.cadaHoras}
                    onChange={(e) => setConfig((prev) => ({ ...prev, cadaHoras: e.target.value }))}
                  />
                </div>
              </div>
            </>
          )}

          {provider === "newsapi" && (
            <>
              <div className="space-y-2">
                <Label htmlFor="fuente-query">Búsqueda</Label>
                <Input
                  id="fuente-query"
                  value={config.query}
                  onChange={(e) => setConfig((prev) => ({ ...prev, query: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <Label htmlFor="fuente-idioma">Idioma (opcional)</Label>
                  <Input
                    id="fuente-idioma"
                    placeholder="es"
                    value={config.idioma}
                    onChange={(e) => setConfig((prev) => ({ ...prev, idioma: e.target.value }))}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="fuente-pais">País (opcional)</Label>
                  <Input
                    id="fuente-pais"
                    placeholder="mx"
                    value={config.pais}
                    onChange={(e) => setConfig((prev) => ({ ...prev, pais: e.target.value }))}
                  />
                </div>
              </div>
            </>
          )}

          {SIN_CONFIG_ESTRICTA.has(provider) && (
            <p className="text-sm text-muted-foreground">
              Este proveedor no necesita configuración adicional para darlo de alta.
            </p>
          )}
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
