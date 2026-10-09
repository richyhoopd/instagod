// Última línea NO vacía de un log de job: el worker termina el log con "\n", y
// split("\n").pop() devolvería "" y taparía el mensaje real.
export function ultimaLinea(log: string | null | undefined): string {
  const lineas = (log ?? "").split("\n").map((l) => l.trim()).filter(Boolean);
  return lineas.length ? lineas[lineas.length - 1] : "";
}
