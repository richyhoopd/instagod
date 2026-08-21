export class ApiError extends Error {
  status: number;
  error: string;
  detalle: string;
  campo: string | null;

  constructor(status: number, body: { error?: string; detalle?: string; campo?: string | null }) {
    super(body.detalle ?? body.error ?? "Error de la API");
    this.name = "ApiError";
    this.status = status;
    this.error = body.error ?? "error";
    this.detalle = body.detalle ?? this.message;
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
