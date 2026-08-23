"use client";

import type { CSSProperties } from "react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { CalendarDays, LayoutDashboard, Library, Settings, Sparkles } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { BrandAvatar } from "@/components/brand-avatar";
import { cn } from "@/lib/utils";
import { useBrand } from "@/hooks/use-brands";

const NAV = [
  { segment: "", label: "Resumen", icon: LayoutDashboard, soloManager: false },
  { segment: "calendar", label: "Calendario", icon: CalendarDays, soloManager: false },
  { segment: "create", label: "Crear", icon: Sparkles, soloManager: false },
  { segment: "library", label: "Biblioteca", icon: Library, soloManager: false },
  { segment: "settings", label: "Ajustes", icon: Settings, soloManager: true },
] as const;

export default function BrandLayout({ children }: { children: React.ReactNode }) {
  const { slug } = useParams<{ slug: string }>();
  const pathname = usePathname();
  const { data: marca, isLoading, isError } = useBrand(slug);

  if (isError) {
    return (
      <div className="space-y-3 py-16 text-center">
        <p className="text-muted-foreground">No se encontró la marca o no tienes acceso.</p>
        <Link href="/brands" className="text-sm underline underline-offset-4">
          Volver a marcas
        </Link>
      </div>
    );
  }

  const puedeVerAjustes = marca ? marca.rol !== "editor" : false;
  const style = marca ? ({ "--brand": marca.color_marca } as CSSProperties) : undefined;

  return (
    <div style={style} className="flex flex-col gap-6 py-6 md:flex-row md:gap-8">
      <aside className="shrink-0 md:sticky md:top-6 md:w-56 md:self-start">
        <div className="mb-4 flex items-center gap-2">
          {isLoading || !marca ? (
            <>
              <Skeleton className="size-9 rounded-full" />
              <Skeleton className="h-4 w-24" />
            </>
          ) : (
            <>
              <BrandAvatar
                slug={slug}
                nombre={marca.nombre}
                colorMarca={marca.color_marca}
                logoPath={marca.logo_path}
              />
              <p className="truncate font-medium">{marca.nombre}</p>
            </>
          )}
        </div>
        <nav className="flex gap-1 overflow-x-auto md:flex-col md:overflow-visible">
          {NAV.filter((item) => !item.soloManager || puedeVerAjustes).map((item) => {
            const href = `/b/${slug}${item.segment ? `/${item.segment}` : ""}`;
            const activo = pathname === href;
            const Icon = item.icon;
            return (
              <Link
                key={item.segment}
                href={href}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-2 text-sm whitespace-nowrap transition-colors",
                  activo
                    ? "bg-(--brand)/10 font-medium text-(--brand)"
                    : "text-muted-foreground hover:bg-muted"
                )}
              >
                <Icon className="size-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
