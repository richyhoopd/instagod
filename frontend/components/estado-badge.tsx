import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { ESTADO_CLASSES, ESTADO_LABELS, esEstado } from "@/lib/estados";

export function EstadoBadge({ estado, className }: { estado: string; className?: string }) {
  const clase = esEstado(estado) ? ESTADO_CLASSES[estado] : ESTADO_CLASSES.borrador;
  const label = esEstado(estado) ? ESTADO_LABELS[estado] : estado;
  return (
    <Badge variant="outline" className={cn("border-transparent font-normal", clase, className)}>
      {label}
    </Badge>
  );
}
