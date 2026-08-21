"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ShieldAlert } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { useMe } from "@/hooks/use-me";

const NAV = [
  { href: "/admin/users", label: "Usuarios" },
  { href: "/admin/system", label: "Sistema" },
] as const;

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const { data: me, isLoading } = useMe();
  const pathname = usePathname();
  const router = useRouter();

  const negado = !isLoading && me && !me.is_admin;

  useEffect(() => {
    if (negado) router.replace("/brands");
  }, [negado, router]);

  if (isLoading) {
    return (
      <div className="space-y-4 py-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!me || !me.is_admin) {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center text-sm text-muted-foreground">
        <ShieldAlert className="size-6" />
        <p>Esta sección es solo para administradores.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 py-6">
      <div>
        <h1 className="text-2xl font-semibold">Administración</h1>
        <nav className="mt-3 flex gap-1 border-b">
          {NAV.map((item) => {
            const activo = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "border-b-2 px-3 py-2 text-sm font-medium transition-colors",
                  activo
                    ? "border-primary text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground"
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
      {children}
    </div>
  );
}
