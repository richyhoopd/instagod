// Utilidades de fecha para el calendario (semana lunes-domingo y mes en grilla).
// Todo en hora local del navegador; scheduled_datetime llega en ISO con offset
// de la marca y `new Date(iso)` ya lo interpreta correctamente.

export function inicioDia(fecha: Date): Date {
  const d = new Date(fecha);
  d.setHours(0, 0, 0, 0);
  return d;
}

export function sumarDias(fecha: Date, n: number): Date {
  const d = new Date(fecha);
  d.setDate(d.getDate() + n);
  return d;
}

export function sumarMeses(fecha: Date, n: number): Date {
  const d = new Date(fecha);
  d.setMonth(d.getMonth() + n);
  return d;
}

// Lunes de la semana que contiene `fecha`.
export function inicioSemana(fecha: Date): Date {
  const d = inicioDia(fecha);
  const dow = d.getDay(); // 0=domingo..6=sabado
  const offset = dow === 0 ? -6 : 1 - dow;
  return sumarDias(d, offset);
}

export function diasSemana(fecha: Date): Date[] {
  const lunes = inicioSemana(fecha);
  return Array.from({ length: 7 }, (_, i) => sumarDias(lunes, i));
}

// Grilla de 6 semanas (42 dias) que cubre el mes de `fecha`, empezando en lunes.
export function diasMes(fecha: Date): Date[] {
  const primerDia = new Date(fecha.getFullYear(), fecha.getMonth(), 1);
  const inicio = inicioSemana(primerDia);
  return Array.from({ length: 42 }, (_, i) => sumarDias(inicio, i));
}

export function claveDia(fecha: Date): string {
  const y = fecha.getFullYear();
  const m = String(fecha.getMonth() + 1).padStart(2, "0");
  const d = String(fecha.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function claveDiaIso(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) return null;
  return claveDia(fecha);
}

export function esMismoMes(fecha: Date, referencia: Date): boolean {
  return (
    fecha.getFullYear() === referencia.getFullYear() && fecha.getMonth() === referencia.getMonth()
  );
}

export function esHoy(fecha: Date): boolean {
  return claveDia(fecha) === claveDia(new Date());
}

export function formatHora(iso: string | null | undefined): string {
  if (!iso) return "";
  const fecha = new Date(iso);
  if (Number.isNaN(fecha.getTime())) return "";
  return fecha.toLocaleTimeString("es-MX", { hour: "2-digit", minute: "2-digit" });
}

export function formatDiaCorto(fecha: Date): string {
  return fecha.toLocaleDateString("es-MX", { weekday: "short", day: "numeric" });
}

export function formatDiaLargo(fecha: Date): string {
  return fecha.toLocaleDateString("es-MX", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
}

export function formatRangoSemana(fecha: Date): string {
  const dias = diasSemana(fecha);
  const primero = dias[0];
  const ultimo = dias[6];
  const mismoMes = primero.getMonth() === ultimo.getMonth();
  const opcionesInicio: Intl.DateTimeFormatOptions = mismoMes
    ? { day: "numeric" }
    : { day: "numeric", month: "short" };
  return `${primero.toLocaleDateString("es-MX", opcionesInicio)} – ${ultimo.toLocaleDateString("es-MX", { day: "numeric", month: "short", year: "numeric" })}`;
}

export function formatMesAno(fecha: Date): string {
  const txt = fecha.toLocaleDateString("es-MX", { month: "long", year: "numeric" });
  return txt.charAt(0).toUpperCase() + txt.slice(1);
}
