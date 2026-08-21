// content_queue.imagen_url guarda una URL simple o, para carruseles, un
// array JSON de URLs (slideshow_json las genera; ver src/cola.py).
function parseArray(url: string): string[] | null {
  try {
    const parsed: unknown = JSON.parse(url);
    if (Array.isArray(parsed)) return parsed.filter((v): v is string => typeof v === "string");
    return null;
  } catch {
    return null;
  }
}

export function primeraImagen(url: string | null | undefined): string | null {
  if (!url) return null;
  const v = url.trim();
  if (v.startsWith("[")) {
    const arr = parseArray(v);
    return arr && arr.length > 0 ? arr[0] : null;
  }
  return v || null;
}

export function contarImagenes(url: string | null | undefined): number {
  if (!url) return 0;
  const v = url.trim();
  if (v.startsWith("[")) {
    const arr = parseArray(v);
    return arr ? arr.length : 0;
  }
  return 1;
}
