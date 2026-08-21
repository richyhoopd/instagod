"use client";

import { useState } from "react";
import { toast } from "sonner";
import { CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { NoDisponible } from "@/components/no-disponible";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { ApiError } from "@/lib/api";
import { SECRETO_INFO } from "@/lib/secretos";
import { useSecrets, useGuardarSecret, useBorrarSecret } from "@/hooks/use-secrets";
import { usePrueba, type TipoPrueba } from "@/hooks/use-pruebas";
import { cn } from "@/lib/utils";

const PRUEBAS: { tipo: TipoPrueba; label: string }[] = [
  { tipo: "instagram", label: "Instagram" },
  { tipo: "telegram", label: "Telegram" },
  { tipo: "llm", label: "Textos con IA" },
];

function SecretRow({
  slug,
  secret,
  puedeEditar,
}: {
  slug: string;
  secret: { clave: string; configurada: boolean; ultimos4: string | null; updated_at: string | null };
  puedeEditar: boolean;
}) {
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState("");
  const guardar = useGuardarSecret(slug);
  const borrar = useBorrarSecret(slug);

  async function onGuardar() {
    if (!valor.trim()) {
      toast.error("El valor no puede ir vacío");
      return;
    }
    const info = SECRETO_INFO[secret.clave];
    try {
      await guardar.mutateAsync({ clave: secret.clave, valor: valor.trim() });
      toast.success(`${info?.label ?? secret.clave} actualizada`);
      setEditando(false);
      setValor("");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo guardar");
    }
  }

  async function onBorrar() {
    const info = SECRETO_INFO[secret.clave];
    try {
      await borrar.mutateAsync(secret.clave);
      toast.success(`${info?.label ?? secret.clave} desconectada`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo borrar");
    }
  }

  const info = SECRETO_INFO[secret.clave];

  return (
    <div className="rounded-lg border p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">
            {info?.label ?? secret.clave}
            <span className="ml-2 font-mono text-[10px] text-muted-foreground/60">
              {secret.clave}
            </span>
          </p>
          {info?.ayuda && <p className="text-xs text-muted-foreground">{info.ayuda}</p>}
          <p className="mt-0.5 text-xs text-muted-foreground">
            {secret.configurada ? `Configurada · termina en ${secret.ultimos4 ?? "????"}` : "Sin configurar"}
          </p>
        </div>
        {puedeEditar && !editando && (
          <div className="flex shrink-0 gap-2">
            <Button type="button" size="sm" variant="outline" onClick={() => setEditando(true)}>
              {secret.configurada ? "Reemplazar" : "Configurar"}
            </Button>
            {secret.configurada && (
              <AlertDialog>
                <AlertDialogTrigger asChild>
                  <Button type="button" size="sm" variant="ghost" className="text-destructive">
                    Borrar
                  </Button>
                </AlertDialogTrigger>
                <AlertDialogContent>
                  <AlertDialogHeader>
                    <AlertDialogTitle>
                      ¿Borrar {info?.label ?? secret.clave}?
                    </AlertDialogTitle>
                    <AlertDialogDescription>
                      La marca dejará de usar esta conexión hasta que se configure de nuevo.
                    </AlertDialogDescription>
                  </AlertDialogHeader>
                  <AlertDialogFooter>
                    <AlertDialogCancel>Cancelar</AlertDialogCancel>
                    <AlertDialogAction onClick={onBorrar}>Borrar conexión</AlertDialogAction>
                  </AlertDialogFooter>
                </AlertDialogContent>
              </AlertDialog>
            )}
          </div>
        )}
      </div>
      {puedeEditar && editando && (
        <div className="mt-3 flex gap-2">
          <Input
            type="password"
            autoFocus
            value={valor}
            onChange={(e) => setValor(e.target.value)}
            placeholder="Nuevo valor"
          />
          <Button type="button" size="sm" onClick={onGuardar} disabled={guardar.isPending}>
            {guardar.isPending ? "Guardando..." : "Guardar"}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={() => {
              setEditando(false);
              setValor("");
            }}
          >
            Cancelar
          </Button>
        </div>
      )}
    </div>
  );
}

function PruebaBoton({ slug, tipo, label }: { slug: string; tipo: TipoPrueba; label: string }) {
  const prueba = usePrueba(slug, tipo);

  async function onProbar() {
    try {
      await prueba.mutateAsync();
    } catch {
      // el resultado con ok:false ya se refleja abajo; ApiError también se
      // captura por si la API responde con un error duro en vez de ok:false.
    }
  }

  const resultado = prueba.data;
  const error = prueba.error;

  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={onProbar} disabled={prueba.isPending}>
          {prueba.isPending ? "Probando..." : `Probar ${label}`}
        </Button>
        {resultado && (
          <Badge
            variant="outline"
            className={cn(
              "gap-1 border-transparent font-normal",
              resultado.ok
                ? "bg-green-100 text-green-800 dark:bg-green-500/15 dark:text-green-400"
                : "bg-red-100 text-red-800 dark:bg-red-500/20 dark:text-red-400"
            )}
          >
            {resultado.ok ? <CheckCircle2 className="size-3" /> : <XCircle className="size-3" />}
            {resultado.ok ? "OK" : "Falló"}
          </Badge>
        )}
      </div>
      {resultado && !resultado.ok && resultado.detalle && (
        <p className="text-xs text-destructive">{resultado.detalle}</p>
      )}
      {resultado?.ok && (resultado.username || resultado.model || resultado.respuesta) && (
        <p className="text-xs text-muted-foreground">
          {[resultado.username, resultado.provider, resultado.model, resultado.respuesta]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}
      {error && <p className="text-xs text-destructive">{error.detalle}</p>}
    </div>
  );
}

export function TabConexiones({ slug, puedeEditar }: { slug: string; puedeEditar: boolean }) {
  const secretsQuery = useSecrets(slug);

  return (
    <div className="max-w-xl space-y-6">
      <div className="space-y-3">
        <h3 className="font-medium">Credenciales</h3>
        {secretsQuery.isLoading && <Skeleton className="h-32 w-full" />}
        {secretsQuery.isError &&
          (secretsQuery.error.status === 404 ? (
            <NoDisponible mensaje="La gestión de credenciales todavía no está disponible en este servidor." />
          ) : (
            <NoDisponible mensaje={secretsQuery.error.detalle} />
          ))}
        {secretsQuery.data && (
          <div className="space-y-2">
            {secretsQuery.data.map((s) => (
              <SecretRow key={s.clave} slug={slug} secret={s} puedeEditar={puedeEditar} />
            ))}
            {secretsQuery.data.length === 0 && (
              <p className="text-sm text-muted-foreground">Sin credenciales registradas.</p>
            )}
          </div>
        )}
      </div>

      <div className="space-y-3 border-t pt-6">
        <h3 className="font-medium">Probar conexiones</h3>
        <div className="space-y-3">
          {PRUEBAS.map((p) => (
            <PruebaBoton key={p.tipo} slug={slug} tipo={p.tipo} label={p.label} />
          ))}
        </div>
      </div>
    </div>
  );
}
