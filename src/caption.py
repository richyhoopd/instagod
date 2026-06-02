"""Generación de captions estilo The Onion para la escena musical de Guadalajara.

Diseño agnóstico de proveedor: DeepSeek expone una API compatible con OpenAI,
así que se usa el SDK `openai` apuntando a `base_url=api.deepseek.com`. Para
cambiar a Claude basta poner LLM_PROVIDER=claude en el .env.

El 70% del valor del proyecto vive en este prompt (ver sección 10 del
blueprint): los aprobados se reinyectan como few-shot positivo y los rechazados
como negativo para afinar la voz editorial con el tiempo.
"""
from __future__ import annotations

import config

# Patrón fijo aprendido de los ejemplos reales: [integrante real + banda real] +
# [afirmación mundana/absurda/sin relación] con tono de nota seria/periodística.
FEW_SHOT_POSITIVOS = [
    "El guitarrista de Noisy Room, Carlos Virgen, asegura que preferiría fumar "
    "crack antes que ver Stranger Things.",
    "Autoridades locales de Azerbaiyán investigan por qué los vendedores siguen "
    "citando al guitarrista de Kabala, Cesar, cuando se les pregunta por los "
    "precios de los dulces.",
    "El baterista de Lefnes, Álvaro, cuestiona si las cocinas modernas están "
    "diseñadas para un uso real.",
]

SYSTEM_PROMPT = """\
Eres el redactor de @gdlscene, una cuenta de sátira estilo The Onion sobre la \
escena musical underground de Guadalajara. Escribes titulares falsos —\
evidentemente ficticios— con tono de nota seria/periodística (deadpan).

Patrón base del titular:
  [Sujeto] + [afirmación mundana, absurda o sin relación] redactada con tono de \
  nota seria/periodística.

El [Sujeto] se arma SOLO con los datos que se te den:
- Con integrante + rol + banda: "El {rol} de {banda}, {integrante}, …".
- Sin rol: "{integrante}, de {banda}, …".
- Sin integrante (pero con banda): habla de la banda en colectivo o de "un \
  integrante de {banda}" sin nombrarlo. NUNCA inventes un nombre propio.
- Sin banda ni integrante: hazlo impersonal y ambiguo ("una banda local", "un \
  músico de la escena", "fuentes cercanas a la escena tapatía…") y compensa con \
  un absurdo MÁS extraño e inesperado.

Regla de oro: entre menos datos personales tengas, más impersonal/ambiguo y más \
absurdo debe ser el titular. Jamás rellenes datos faltantes con invenciones \
concretas (ni nombres, ni roles, ni bandas).

Reglas estrictas:
- Español de México.
- Tono periodístico serio; el humor nace del contraste, NO de bromas obvias.
- Sin emojis, sin hashtags, sin comillas alrededor del titular.
- 1 a 3 líneas, una sola afirmación.
- El absurdo debe ser CLARAMENTE ficticio e inofensivo (cocinas, dulces, series, \
  objetos cotidianos). EVITA atribuir a una persona nombrada conductas reales \
  difamatorias graves: delitos, consumo real de drogas duras, violencia o \
  contenido sexual. Mantén el riesgo legal y reputacional en cero.
- Devuelve ÚNICAMENTE el titular, sin preámbulo ni explicación."""


def _clean(value: str | None) -> str | None:
    """Normaliza vacíos/espacios a None (= dato ausente)."""
    v = (value or "").strip()
    return v or None


def _build_user_prompt(
    banda: str | None,
    integrante: str | None,
    rol: str | None,
    tema_semilla: str | None,
    rechazados: list[str] | None,
) -> str:
    ejemplos = "\n".join(f"- {e}" for e in FEW_SHOT_POSITIVOS)
    partes = [
        "Ejemplos del estilo y la voz a imitar:",
        ejemplos,
        "",
        "Datos disponibles para el nuevo titular (usa SOLO los presentes):",
    ]
    presentes = []
    if banda:
        partes.append(f"- Banda: {banda}")
        presentes.append("banda")
    if integrante:
        partes.append(f"- Integrante: {integrante}")
        presentes.append("integrante")
    if rol:
        partes.append(f"- Rol: {rol}")
        presentes.append("rol")

    faltantes = [c for c in ("banda", "integrante", "rol") if c not in presentes]
    if faltantes:
        partes.append(
            f"- Datos AUSENTES: {', '.join(faltantes)}. No los inventes; hazlo más "
            "impersonal/ambiguo y compensa con un absurdo más extraño."
        )

    if tema_semilla:
        partes.append(f"- Pista de tema (úsala como semilla, no literal): {tema_semilla}")
    else:
        partes.append("- Tema: libre (elige tú la afirmación absurda).")
    if rechazados:
        negativos = "\n".join(f"- {r}" for r in rechazados)
        partes += [
            "",
            "Titulares ya RECHAZADos para estos datos (NO los repitas ni te parezcas):",
            negativos,
        ]
    partes += ["", "Escribe un titular nuevo siguiendo el patrón."]
    return "\n".join(partes)


def generate_caption(
    banda: str | None = None,
    integrante: str | None = None,
    rol: str | None = None,
    tema_semilla: str | None = None,
    rechazados: list[str] | None = None,
    *,
    temperature: float = 1.0,
) -> str:
    """Genera UN titular. La regeneración se hace volviendo a llamar esta función.

    Campos vacíos o ausentes (banda/integrante/rol) se omiten del prompt: el
    titular se vuelve más impersonal/ambiguo y más absurdo. Nunca se inventan datos.
    `rechazados`: titulares previos rechazados para estos datos, para evitar repetir.
    """
    user_prompt = _build_user_prompt(
        _clean(banda), _clean(integrante), _clean(rol), _clean(tema_semilla), rechazados
    )
    if config.LLM_PROVIDER == "claude":
        text = _via_anthropic(user_prompt, temperature)
    else:
        text = _via_deepseek(user_prompt, temperature)
    return text.strip().strip('"').strip()


def _via_deepseek(user_prompt: str, temperature: float) -> str:
    from openai import OpenAI

    if not config.DEEPSEEK_API_KEY:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en el .env")
    client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=config.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=300,
    )
    return resp.choices[0].message.content or ""


def _via_anthropic(user_prompt: str, temperature: float) -> str:
    import anthropic

    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("Falta ANTHROPIC_API_KEY en el .env (LLM_PROVIDER=claude)")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=300,
        temperature=min(temperature, 1.0),  # anthropic acota temperature a [0,1]
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text")


if __name__ == "__main__":
    # Prueba aislada con datos dummy: python -m src.caption
    print(generate_caption("Noisy Room", "Carlos Virgen", "guitarrista"))
