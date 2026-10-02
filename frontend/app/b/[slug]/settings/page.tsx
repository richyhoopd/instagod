"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useBrand } from "@/hooks/use-brands";
import { TabPerfil } from "./_components/tab-perfil";
import { TabVoz } from "./_components/tab-voz";
import { TabEstilos } from "./_components/tab-estilos";
import { TabFuentes } from "./_components/tab-fuentes";
import { TabConexiones } from "./_components/tab-conexiones";
import { TabHorarios } from "./_components/tab-horarios";
import { TabVideo } from "./_components/tab-video";

const TABS = ["perfil", "voz", "estilos", "fuentes", "conexiones", "horarios", "video"];

function Ajustes() {
  const { slug } = useParams<{ slug: string }>();
  const { data: marca, isLoading } = useBrand(slug);
  // ?tab=video: el wizard de reels enlaza directo aquí cuando falta el preset.
  const tabParam = useSearchParams().get("tab");
  const tabInicial = tabParam && TABS.includes(tabParam) ? tabParam : "perfil";

  if (isLoading || !marca) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-64 w-full max-w-2xl" />
      </div>
    );
  }

  // El layout ya oculta el link de Ajustes para editor, pero si llega por
  // URL directa la página se muestra igual: cada tab se renderiza en modo
  // lectura (inputs deshabilitados, botones de mutación ocultos).
  const puedeEditar = marca.rol !== "editor";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Ajustes de la marca</h1>
        {!puedeEditar && (
          <p className="text-sm text-muted-foreground">
            Tu rol es editor: puedes ver la configuración pero no modificarla.
          </p>
        )}
      </div>

      <Tabs defaultValue={tabInicial}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="perfil">Perfil</TabsTrigger>
          <TabsTrigger value="voz">Voz</TabsTrigger>
          <TabsTrigger value="estilos">Estilos</TabsTrigger>
          <TabsTrigger value="fuentes">Fuentes</TabsTrigger>
          <TabsTrigger value="conexiones">Conexiones</TabsTrigger>
          <TabsTrigger value="horarios">Horarios</TabsTrigger>
          <TabsTrigger value="video">Video</TabsTrigger>
        </TabsList>

        <TabsContent value="perfil">
          <TabPerfil key={marca.slug} slug={slug} marca={marca} puedeEditar={puedeEditar} />
        </TabsContent>
        <TabsContent value="voz">
          <TabVoz key={marca.slug} slug={slug} marca={marca} puedeEditar={puedeEditar} />
        </TabsContent>
        <TabsContent value="estilos">
          <TabEstilos slug={slug} puedeEditar={puedeEditar} />
        </TabsContent>
        <TabsContent value="fuentes">
          <TabFuentes slug={slug} puedeEditar={puedeEditar} />
        </TabsContent>
        <TabsContent value="conexiones">
          <TabConexiones slug={slug} puedeEditar={puedeEditar} />
        </TabsContent>
        <TabsContent value="horarios">
          <TabHorarios marca={marca} />
        </TabsContent>
        <TabsContent value="video">
          <TabVideo slug={slug} puedeEditar={puedeEditar} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64 w-full max-w-2xl" />}>
      <Ajustes />
    </Suspense>
  );
}
