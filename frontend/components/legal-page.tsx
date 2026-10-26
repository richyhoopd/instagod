import Link from "next/link";

export const CONTACTO_EMAIL = "terryt33mple@gmail.com";
export const ULTIMA_ACTUALIZACION = "October 25, 2026";

type Seccion = { titulo: string; contenido: React.ReactNode };

export function LegalPage({ titulo, secciones }: { titulo: string; secciones: Seccion[] }) {
  return (
    <main className="mx-auto max-w-2xl py-12 text-sm leading-relaxed">
      <p className="mb-8 text-lg font-semibold tracking-tight">instagod</p>
      <h1 className="text-2xl font-semibold tracking-tight">{titulo}</h1>
      <p className="mt-1 text-muted-foreground">Last updated: {ULTIMA_ACTUALIZACION}</p>
      {secciones.map((s) => (
        <section key={s.titulo} className="mt-8 space-y-3">
          <h2 className="text-base font-semibold">{s.titulo}</h2>
          {s.contenido}
        </section>
      ))}
      <footer className="mt-12 flex gap-4 border-t pt-6 text-muted-foreground">
        <Link href="/terms" className="hover:underline">
          Terms of Service
        </Link>
        <Link href="/privacy" className="hover:underline">
          Privacy Policy
        </Link>
      </footer>
    </main>
  );
}
