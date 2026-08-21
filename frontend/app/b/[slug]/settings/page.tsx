"use client";

import { useParams } from "next/navigation";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useBrand } from "@/hooks/use-brands";
import { TabPerfil } from "./_components/tab-perfil";
import { TabVoz } from "./_components/tab-voz";
import { TabEstilos } from "./_components/tab-estilos";
import { TabFuentes } from "./_components/tab-fuentes";
import { TabConexiones } from "./_components/tab-conexiones";
import { TabHorarios } from "./_components/tab-horarios";

export default function SettingsPage() {
  const { slug } = useParams<{ slug: string }>();
  const { data: marca, isLoading } = useBrand(slug);

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

      <Tabs defaultValue="perfil">
        <TabsList className="flex-wrap">
          <TabsTrigger value="perfil">Perfil</TabsTrigger>
          <TabsTrigger value="voz">Voz y prompts</TabsTrigger>
          <TabsTrigger value="estilos">Estilos</TabsTrigger>
          <TabsTrigger value="fuentes">Fuentes</TabsTrigger>
          <TabsTrigger value="conexiones">Conexiones</TabsTrigger>
          <TabsTrigger value="horarios">Horarios</TabsTrigger>
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
      </Tabs>
    </div>
  );
}
