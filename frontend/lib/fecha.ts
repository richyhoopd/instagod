export function formatearFecha(iso: string | null | undefined): string {
  if (!iso) return "";
  const normalizada = iso.includes("T") ? iso : iso.replace(" ", "T");
  const fecha = new Date(normalizada);
  if (Number.isNaN(fecha.getTime())) return iso;
  return fecha.toLocaleString("es-MX", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
