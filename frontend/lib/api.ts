// Mensajes genéricos por status para cuando la API no manda un detalle
// legible (o manda uno técnico en inglés que no debe llegar al usuario).
const MENSAJES_STATUS: Record<number, string> = {
  400: "La solicitud no es válida. Revisa los datos e intenta de nuevo.",
  401: "Tu sesión expiró. Vuelve a iniciar sesión.",
  403: "No tienes permiso para hacer esto en esta marca.",
  404: "No encontramos lo que buscabas.",
  409: "Alguien más hizo un cambio que choca con este. Recarga e intenta de nuevo.",
  413: "El archivo es demasiado grande.",
  422: "Hay un dato que no se ve bien. Revísalo e intenta de nuevo.",
  429: "Demasiados intentos seguidos. Espera un momento y vuelve a intentar.",
};

// Detalles conocidos que el backend regresa en inglés (validación Pydantic).
const TRADUCCIONES: [RegExp, string][] = [
  [/not a valid email address/i, "Ese correo no parece válido. Revísalo e intenta de nuevo."],
  [/field required|missing/i, "Falta un dato obligatorio."],
  [/value error/i, "Hay un dato que no se ve bien. Revísalo e intenta de nuevo."],
];

function humanizarDetalle(status: number, detalle: string | undefined): string {
  if (detalle) {
    for (const [patron, mensaje] of TRADUCCIONES) {
      if (patron.test(detalle)) return mensaje;
    }
    // Un detalle con pinta de traceback o inglés técnico no ayuda a nadie.
    if (/traceback|exception|assert/i.test(detalle)) {
      return MENSAJES_STATUS[status] ?? "Algo salió mal. Intenta de nuevo.";
    }
    return detalle;
  }
  if (status >= 500) return "Algo falló de nuestro lado. Intenta de nuevo en un momento.";
  return MENSAJES_STATUS[status] ?? "Algo salió mal. Intenta de nuevo.";
}

export class ApiError extends Error {
  status: number;
  error: string;
  detalle: string;
  campo: string | null;

  constructor(status: number, body: { error?: string; detalle?: string; campo?: string | null }) {
    const detalle = humanizarDetalle(status, body.detalle);
    super(detalle);
    this.name = "ApiError";
    this.status = status;
    this.error = body.error ?? "error";
    this.detalle = detalle;
    this.campo = body.campo ?? null;
  }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
    credentials: "include",
  });

  if (!res.ok) {
    let body: { error?: string; detalle?: string; campo?: string | null } = {};
    try {
      body = await res.json();
    } catch {
      // respuesta sin cuerpo JSON (p.ej. 502 de un proxy)
    }
    throw new ApiError(res.status, body);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

function get<T>(path: string, init?: RequestInit): Promise<T> {
  return api<T>(path, { ...init, method: "GET" });
}

function post<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return api<T>(path, {
    ...init,
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function patch<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return api<T>(path, {
    ...init,
    method: "PATCH",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function put<T>(path: string, body?: unknown, init?: RequestInit): Promise<T> {
  return api<T>(path, {
    ...init,
    method: "PUT",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function del<T>(path: string, init?: RequestInit): Promise<T> {
  return api<T>(path, { ...init, method: "DELETE" });
}

// Subida de archivos: sin Content-Type propio, el navegador arma el
// boundary de multipart/form-data solo.
async function postForm<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method: "POST",
    body: form,
    credentials: "include",
  });

  if (!res.ok) {
    let body: { error?: string; detalle?: string; campo?: string | null } = {};
    try {
      body = await res.json();
    } catch {
      // respuesta sin cuerpo JSON
    }
    throw new ApiError(res.status, body);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

export { api, get, post, patch, put, del, postForm };
