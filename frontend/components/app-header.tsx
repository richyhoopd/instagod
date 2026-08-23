"use client";

import { useState } from "react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { toast } from "sonner";
import { ChevronDown, LogOut, Shield } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { BrandAvatar } from "@/components/brand-avatar";
import { useMe } from "@/hooks/use-me";
import { useBrands } from "@/hooks/use-brands";
import { ApiError, post } from "@/lib/api";

const RUTAS_PUBLICAS = ["/login", "/auth"];

export function AppHeader() {
  const pathname = usePathname();
  const router = useRouter();
  const params = useParams<{ slug?: string }>();
  const [saliendo, setSaliendo] = useState(false);

  const esPublica = RUTAS_PUBLICAS.some(
    (p) => pathname === p || pathname.startsWith(`${p}/`)
  );

  const { data: me, isLoading: cargandoMe } = useMe();
  const { data: marcas } = useBrands();

  // El proxy ya redirige a /login sin cookie; esto evita el parpadeo del
  // header en /login o mientras /me todavía no resuelve en rutas públicas.
  if (esPublica) return null;

  const marcaActual = params?.slug ? marcas?.find((m) => m.slug === params.slug) : undefined;

  async function cerrarSesion() {
    setSaliendo(true);
    try {
      await post("/auth/logout");
    } catch (err) {
      toast.error(err instanceof ApiError ? err.detalle : "No se pudo cerrar la sesión");
    } finally {
      router.push("/login");
      router.refresh();
    }
  }

  return (
    <header className="sticky top-0 z-40 border-b bg-background/95 backdrop-blur supports-backdrop-filter:bg-background/80">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center justify-between gap-3 px-4">
        <div className="flex min-w-0 items-center gap-1">
          <Link href="/brands" className="shrink-0 px-1.5 font-semibold tracking-tight">
            instagod
          </Link>
          {marcas && marcas.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="min-w-0 gap-1.5 px-2">
                  {marcaActual ? (
                    <>
                      <BrandAvatar
                        slug={marcaActual.slug}
                        nombre={marcaActual.nombre}
                        colorMarca={marcaActual.color_marca}
                        logoPath={marcaActual.logo_path}
                        className="size-5"
                      />
                      <span className="max-w-32 truncate sm:max-w-48">{marcaActual.nombre}</span>
                    </>
                  ) : (
                    <span className="text-muted-foreground">Marcas</span>
                  )}
                  <ChevronDown className="size-3.5 text-muted-foreground" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuLabel>Cambiar de marca</DropdownMenuLabel>
                <DropdownMenuSeparator />
                {marcas.map((m) => (
                  <DropdownMenuItem key={m.slug} asChild>
                    <Link href={`/b/${m.slug}`} className="gap-2">
                      <BrandAvatar
                        slug={m.slug}
                        nombre={m.nombre}
                        colorMarca={m.color_marca}
                        logoPath={m.logo_path}
                        className="size-5"
                      />
                      <span className="truncate">{m.nombre}</span>
                    </Link>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem asChild>
                  <Link href="/brands">Ver todas las marcas</Link>
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          {me?.is_admin && (
            <Button variant="ghost" size="sm" className="gap-1.5" asChild>
              <Link href="/admin/users">
                <Shield className="size-4" />
                <span className="hidden sm:inline">Admin</span>
              </Link>
            </Button>
          )}

          {cargandoMe || !me ? (
            <Skeleton className="size-8 rounded-full" />
          ) : (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="rounded-full">
                  <Avatar className="size-8">
                    <AvatarFallback>
                      {(me.nombre || me.email).trim().charAt(0).toUpperCase()}
                    </AvatarFallback>
                  </Avatar>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuLabel className="truncate">
                  {me.nombre || me.email}
                </DropdownMenuLabel>
                <p className="truncate px-1.5 pb-1.5 text-xs text-muted-foreground">{me.email}</p>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={cerrarSesion} disabled={saliendo} variant="destructive">
                  <LogOut className="size-4" />
                  {saliendo ? "Cerrando sesión..." : "Cerrar sesión"}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </div>
    </header>
  );
}
