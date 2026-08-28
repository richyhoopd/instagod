# Product

## Register

product

## Users

Core team de instagod: colaboradores **no técnicos** que administran marcas de Instagram (gdlscene, melaquecapital, etc.) y generan carruseles de contenido. Roles: admin (Ricardo), manager (configura su marca completa), editor (solo contenido). Usan el portal en desktop principalmente, a veces móvil para aprobar/revisar. No saben qué es un token, un RSS o un preset JSON; necesitan que la UI los guíe.

## Product Purpose

Portal web (Next.js + API FastAPI) para que el equipo genere y administre contenido de Instagram sin tocar terminal ni archivos: calendario de publicación estilo Buffer, wizard de creación de carruseles, biblioteca, aprobación/rechazo/reprogramación, y configuración de marca (perfil, voz, presets visuales, fuentes de imagen/información, credenciales, horarios). Éxito = un colaborador no técnico completa el ciclo crear → revisar → aprobar → ver publicado sin ayuda.

## Brand Personality

Confiable, claro, ágil. Herramienta profesional que se siente ligera: el estándar de usabilidad es Airbnb (claridad extrema, jerarquía obvia, cero fricción), no un panel de admin genérico. En español, tono directo y humano.

## Anti-references

- AI slop: grids de cards idénticas, side-stripes de color, gradient text, eyebrows uppercase en cada sección, hero-metrics.
- Paneles de admin genéricos (Django admin, dashboards Bootstrap) donde cada pantalla exige conocimiento técnico.
- Jerga de desarrollador expuesta al usuario: JSON crudo, slugs, códigos de error HTTP, nombres de columnas de DB.

## Design Principles

1. **Cero jerga técnica visible**: cada campo, error y estado se explica en lenguaje del equipo (contenido, marca, publicación), nunca del sistema.
2. **El estado siempre visible**: qué se va a publicar, cuándo, y qué falta por hacer se entiende en 5 segundos desde el dashboard.
3. **Acciones irreversibles protegidas y explicadas**: aprobar publica de verdad en Instagram; la UI lo deja claro antes, durante y después.
4. **Progressive disclosure**: los defaults funcionan; la complejidad (presets, fuentes, credenciales) se revela solo cuando se necesita.
5. **Consistencia de vocabulario**: misma acción = mismo botón, mismo nombre y mismo lugar en todas las pantallas.

## Accessibility & Inclusion

WCAG AA como piso (contraste 4.5:1 en texto de cuerpo). Interfaz en español. Usable con teclado en flujos principales. `prefers-reduced-motion` respetado.
