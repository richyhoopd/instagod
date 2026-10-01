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

export function listaImagenes(url: string | null | undefined): string[] {
  if (!url) return [];
  const v = url.trim();
  if (v.startsWith("[")) {
    const arr = parseArray(v);
    return arr ?? [];
  }
  return v ? [v] : [];
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

// Los reels (tipo 'video') guardan el mp4 de Cloudinary en el mismo campo
// imagen_url. Un <img> con un .mp4 queda en blanco: hay que detectarlo para
// pintar un <video> o su poster.
export function esVideo(url: string | null | undefined): boolean {
  const v = primeraImagen(url);
  if (!v) return false;
  return /\.(mp4|mov|webm|m4v)(\?|#|$)/i.test(v) || v.includes("/video/upload/");
}

// Miniatura de un reel de Cloudinary: la misma URL con extensión .jpg devuelve
// un frame. Para cualquier otra cosa, la propia URL sirve de imagen.
export function miniatura(url: string | null | undefined): string | null {
  const v = primeraImagen(url);
  if (!v) return null;
  if (!esVideo(v)) return v;
  if (v.includes("/video/upload/")) {
    return v.replace(/\.(mp4|mov|webm|m4v)(\?.*)?$/i, ".jpg");
  }
  return null;
}
