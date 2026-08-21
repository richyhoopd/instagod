"use client";

import { useParams } from "next/navigation";
import { ProximasPanel } from "./_components/proximas-panel";
import { PendientesPanel } from "./_components/pendientes-panel";
import { SaludPanel } from "./_components/salud-panel";
import { TemasPanel } from "./_components/temas-panel";

export default function BrandDashboardPage() {
  const { slug } = useParams<{ slug: string }>();

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Resumen</h1>
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ProximasPanel slug={slug} />
        <PendientesPanel slug={slug} />
        <SaludPanel slug={slug} />
        <TemasPanel slug={slug} />
      </div>
    </div>
  );
}
