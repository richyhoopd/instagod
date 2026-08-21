"use client";

import Link from "next/link";
import { AlertTriangle, Clock } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BrandAvatar } from "@/components/brand-avatar";
import { useQueue } from "@/hooks/use-queue";
import type { Brand } from "@/hooks/use-brands";

export function BrandCard({ marca }: { marca: Brand }) {
  const pendientes = useQueue(marca.slug, "pendiente");
  const conteoPendientes = pendientes.data?.length ?? 0;

  return (
    <Link href={`/b/${marca.slug}`} className="block">
      <Card className="h-full transition-shadow hover:shadow-md">
        <CardHeader className="flex-row items-center gap-3">
          <BrandAvatar
            slug={marca.slug}
            nombre={marca.nombre}
            colorMarca={marca.color_marca}
            logoPath={marca.logo_path}
            className="size-10"
          />
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium">{marca.nombre}</p>
            <p className="truncate text-sm text-muted-foreground">{marca.ig_handle}</p>
          </div>
          {!marca.activa && (
            <Badge variant="secondary" className="shrink-0">
              Inactiva
            </Badge>
          )}
        </CardHeader>
        <CardContent className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-muted-foreground">{marca.ciudad}</p>
          {conteoPendientes > 0 && (
            <Badge variant="outline" className="gap-1 border-amber-300 text-amber-700 dark:text-amber-400">
              <Clock className="size-3" />
              {conteoPendientes} pendiente{conteoPendientes === 1 ? "" : "s"}
            </Badge>
          )}
          {marca.creds_faltantes.map((clave) => (
            <Badge
              key={clave}
              variant="outline"
              className="gap-1 border-red-300 text-red-700 dark:text-red-400"
            >
              <AlertTriangle className="size-3" />
              {clave}
            </Badge>
          ))}
        </CardContent>
      </Card>
    </Link>
  );
}
