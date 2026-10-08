import { type Capa, type Escena, idLibre } from "@/lib/escena";

export interface Candidata {
  proveedor: string;
  id_origen: string;
  tipo: "imagen" | "video";
  url: string;
  preview_url: string;
  ancho: number | null;
  alto: number | null;
  autor: string | null;
  licencia: string | null;
  url_origen: string | null;
  ig_handle?: string | null;
  source_post_id?: string | null;
}

// Fila de brand_assets más `src` (api/routers/assets.py:_con_src). El cliente
// nunca arma rutas de disco: la URL sale de `src`.
export interface Asset {
  id: number;
  tipo: "imagen" | "video";
  archivo: string;
  recorte_archivo: string | null;
  proveedor: string;
  autor: string | null;
  licencia: string | null;
  url_origen: string | null;
  ig_handle: string | null;
  ancho: number | null;
  alto: number | null;
  src: string;
}

/** URL que el navegador puede pedir: el backend vive bajo /api. */
export function urlVisible(slug: string, url: string): string {
  if (url.startsWith("assets/")) return `/api/brands/${slug}/files/${url}`;
  if (url.startsWith("/")) return `/api${url}`;
  return url;
}

export function capaDesdeAsset(
  asset: Asset,
  escena: Escena,
  opts: { recorte?: boolean } = {},
): Capa {
  const { w: W, h: H } = escena.lienzo;
  const aw = asset.ancho ?? W;
  const ah = asset.alto ?? H;
  const escala = Math.min((0.6 * W) / aw, (0.6 * H) / ah);
  const w = Math.round(aw * escala);
  const h = Math.round(ah * escala);
  const zMax = escena.capas.reduce((m, c) => Math.max(m, c.z ?? 0), 0);
  const recorte = !!opts.recorte && !!asset.recorte_archivo;
  const archivo = recorte ? asset.recorte_archivo! : asset.archivo;
  const nombre = asset.autor ? `foto ${asset.autor}` : "foto";
  const capa = {
    id: idLibre(escena, nombre),
    nombre,
    tipo: asset.tipo === "video" ? "video" : "image",
    x: Math.round((W - w) / 2),
    y: Math.round((H - h) / 2),
    w,
    h,
    rot: 0,
    opacity: 1,
    z: zMax + 1,
    bloqueada: false,
    oculta: false,
    anclaje: "center",
    src: `assets/${archivo}`,
    recorte: null,
    ajuste: recorte ? "contain" : "cover",
    mascara: "none",
    estilo: {},
    fuente_asset: {
      proveedor: asset.proveedor,
      autor: asset.autor,
      licencia: asset.licencia,
      url: asset.url_origen,
      ig_handle: asset.ig_handle,
    },
  };
  return capa as unknown as Capa;
}
