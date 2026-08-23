import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { cn } from "@/lib/utils";

interface BrandAvatarProps {
  slug: string;
  nombre: string;
  colorMarca?: string | null;
  logoPath?: string | null;
  className?: string;
}

export function BrandAvatar({ slug, nombre, colorMarca, logoPath, className }: BrandAvatarProps) {
  const inicial = nombre.trim().charAt(0).toUpperCase() || "?";
  const color = colorMarca || "#1b5e3f";
  return (
    <Avatar className={cn("border", className)}>
      {logoPath && <AvatarImage src={`/api/brands/${slug}/files/${logoPath}`} alt={nombre} />}
      <AvatarFallback style={{ backgroundColor: color, color: "#fff" }}>{inicial}</AvatarFallback>
    </Avatar>
  );
}
