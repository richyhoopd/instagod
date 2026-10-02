import { cn } from "@/lib/utils";

export function WizardSteps({ paso, pasos }: { paso: number; pasos: string[] }) {
  return (
    <ol className="flex flex-wrap gap-2">
      {pasos.map((label, i) => {
        const n = i + 1;
        const activo = n === paso;
        const hecho = n < paso;
        return (
          <li
            key={label}
            className={cn(
              "flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs text-muted-foreground",
              activo && "border-(--brand) bg-(--brand)/10 font-medium text-(--brand)",
              hecho && !activo && "border-transparent"
            )}
          >
            <span>{n}.</span>
            {label}
          </li>
        );
      })}
    </ol>
  );
}
