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
Eres el redactor de @gdlscene, sátira estilo The Onion sobre la escena musical \
underground de Guadalajara. Escribes titulares de noticia FALSOS con tono de nota \
periodística seria (deadpan).

EL SUJETO se arma SOLO con los datos que te den:
- integrante + rol + banda → "El {rol} de {banda}, {integrante}, …".
- sin rol → "{integrante}, de {banda}, …".
- sin integrante (con banda) → la banda en colectivo o "un integrante de {banda}" sin \
  nombrarlo. NUNCA inventes un nombre propio.
- sin banda ni integrante → impersonal ("una banda local", "un músico de la escena", \
  "reporte:", "fuentes cercanas a la escena tapatía…").
Jamás rellenes datos faltantes con invenciones concretas.

EL MÉTODO THE ONION (esto es lo que evita el "texto de IA"):
1. UNA sola idea absurda por titular. NO encadenes elementos random; un buen titular \
   tiene UN giro filoso, no tres cosas raras amontonadas.
2. CORTO Y SECO. Idealmente una frase de ~8 a 20 palabras. Si usas "porque", \
   "equivalente a", "lo que provocó que…" probablemente lo estás estirando: córtalo.
3. Registro de nota real, en presente, estilo agencia: declara, anuncia, admite, \
   exige, celebra, demota, "Reporte:", "preocupado por", "bajo fuego por".
4. El humor nace de algo RECONOCIBLE exagerado o de un GIRO LÓGICO seco, no de \
   surrealismo random. Patético-humano, oscuro-deadpan, o sobre-logro/misdirección.
5. Especificidad AL SERVICIO del chiste: un número o un detalle concreto que remate \
   ("cayó 74%", "comunicado de 14 páginas", "lo completó en 9"). No decoración.
6. Si te dan un TEMA, es el disparador: dale UN giro absurdo, no una nota literal.

Plantillas de chiste (elige UNA, varía entre titulares):
- Músico + acción mundana patética tratada como noticia seria.
- "Reporte:" / "Estudio:" con un dato absurdo específico.
- Yuxtaposición deadpan oscura (de buen gusto).
- Autoridad / festival / comité reaccionando a una tontería.
- Giro de sobre-logro o de misdirección lógica.
- Confesión en primera persona estilo columna de opinión.

Ejemplos del registro y la concisión a imitar (NO los copies, imita el estilo):
- "El baterista de Kabala, Damián, completó su programa de 12 pasos en 9."
- "Reporte: el poder del post-punk tapatío para unir a la gente cayó 74%."
- "Bajista de Extraño Enemigo demota su pedalera a vaso entrenador."
- "Músico local preocupado por estar en una relación codependiente con su afinador."
- "Banda de la escena anuncia gira tras enterarse de que eso es algo que se puede hacer."

Reglas:
- Español de México. Sin emojis, sin hashtags, sin comillas alrededor del titular.
- Una sola frase, idealmente corta. Prohibido amontonar sustantivos random o estirar.
- Absurdo evidentemente ficticio; nada de acusaciones serias y creíbles de delitos \
  reales contra una persona nombrada (eso es difamación, no chiste).
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
    temperature: float | None = None,
) -> str:
    """Genera UN titular. La regeneración se hace volviendo a llamar esta función.

    Campos vacíos o ausentes (banda/integrante/rol) se omiten del prompt: el
    titular se vuelve más impersonal/ambiguo y más absurdo. Nunca se inventan datos.
    `rechazados`: titulares previos rechazados para estos datos, para evitar repetir.
    """
    if temperature is None:
        temperature = config.CAPTION_TEMPERATURE
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
