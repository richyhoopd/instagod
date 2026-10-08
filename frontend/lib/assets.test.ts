import { describe, expect, it } from "vitest";
import type { Escena } from "@/lib/escena";
import { capaDesdeAsset, urlVisible, type Asset } from "@/lib/assets";

const escena = {
  v: 2,
  lienzo: { w: 1080, h: 1350, formato: "4x5", fondo: "#ffffff" },
  tokens: {},
  capas: [
    { id: "foto_ana", nombre: "foto", tipo: "image", x: 0, y: 0, w: 10, h: 10, rot: 0,
      opacity: 1, z: 3, bloqueada: false, oculta: false, src: "assets/a.jpg",
      ajuste: "cover", mascara: "none", estilo: {} },
  ],
} as unknown as Escena;

const asset: Asset = {
  id: 9, tipo: "imagen", archivo: "ab12.jpg", recorte_archivo: "ab12-recorte.png",
  proveedor: "unsplash", autor: "Ana", licencia: "Unsplash License",
  url_origen: "https://unsplash.com/p", ig_handle: null, ancho: 2000, alto: 1000,
  src: "assets/ab12.jpg",
};

describe("assets", () => {
  it("urlVisible antepone /api a rutas del backend y deja pasar URLs externas", () => {
    expect(urlVisible("m1", "/brands/m1/files/assets/a.jpg")).toBe("/api/brands/m1/files/assets/a.jpg");
    expect(urlVisible("m1", "https://images.pexels.com/x.jpg")).toBe("https://images.pexels.com/x.jpg");
    expect(urlVisible("m1", "assets/a.jpg")).toBe("/api/brands/m1/files/assets/a.jpg");
  });

  it("capaDesdeAsset escala a 60% del lienzo, centra, queda arriba y no choca de id", () => {
    const c = capaDesdeAsset(asset, escena) as unknown as Record<string, unknown>;
    expect(c.id).toBe("foto_ana_2");
    expect(c.tipo).toBe("image");
    expect(c.src).toBe("assets/ab12.jpg");
    expect(c.w).toBe(648);
    expect(c.h).toBe(324);
    expect(c.x).toBe(216);
    expect(c.y).toBe(513);
    expect(c.z).toBe(4);
    expect(c.anclaje).toBe("center");
    expect(c.fuente_asset).toEqual({ proveedor: "unsplash", autor: "Ana",
      licencia: "Unsplash License", url: "https://unsplash.com/p", ig_handle: null });
    const r = capaDesdeAsset(asset, escena, { recorte: true }) as unknown as Record<string, unknown>;
    expect(r.src).toBe("assets/ab12-recorte.png");
    expect(r.ajuste).toBe("contain");
  });

  it("un asset de video produce capa de video", () => {
    const v = capaDesdeAsset({ ...asset, tipo: "video", archivo: "v.mp4" }, escena);
    expect(v.tipo).toBe("video");
  });
});
