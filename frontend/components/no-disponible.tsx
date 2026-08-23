import { CircleAlert } from "lucide-react";

// Estado de degradación cuando un endpoint de Fase 3 todavía no existe en el
// backend contra el que corre el portal (404). Nunca debe tumbar la página.
export function NoDisponible({ mensaje }: { mensaje?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed py-10 text-center text-sm text-muted-foreground">
      <CircleAlert className="size-5" />
      <p>{mensaje ?? "Esta sección no está disponible todavía en el servidor."}</p>
    </div>
  );
}
