"""Router de perfil: prompts, presets (con preview), logo y archivos servidos."""
from __future__ import annotations

import io

from src import db


def _marca(cx, slug="pensionmas"):
    return db.insert(cx, "accounts", slug=slug, ig_handle="@p", nombre="P", ciudad="CDMX")


# ---------- prompts ----------

def test_prompts_lectura_editor_escritura_manager(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.get("/brands/pensionmas/prompts")
    assert r.status_code == 200
    assert set(r.json()) == {"voz", "caption_extra", "por_formato", "hashtags"}

    r = cli.put("/brands/pensionmas/prompts", json={"voz": "tono serio"})
    assert r.status_code == 403
    H.logout()

    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.put("/brands/pensionmas/prompts", json={
        "voz": "tono serio y directo",
        "caption_extra": "siempre cierra con pregunta",
        "por_formato": {"listicle": "usa números"},
        "hashtags": ["#pension", "#retiro"],
    })
    assert r.status_code == 200
    assert r.json()["voz"] == "tono serio y directo"
    assert r.json()["por_formato"] == {"listicle": "usa números"}

    r = cli.get("/brands/pensionmas/prompts")
    assert r.json()["hashtags"] == ["#pension", "#retiro"]


def test_prompts_valida_por_formato_y_hashtags(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    r = cli.put("/brands/pensionmas/prompts", json={
        "voz": "x", "por_formato": {"formato_no_existe": "algo"},
    })
    assert r.status_code == 422 and r.json()["campo"] == "por_formato"

    r = cli.put("/brands/pensionmas/prompts", json={
        "voz": "x", "hashtags": ["sinhash"],
    })
    assert r.status_code == 422 and r.json()["campo"] == "hashtags"

    r = cli.put("/brands/pensionmas/prompts", json={"voz": "x" * 4001})
    assert r.status_code == 422 and r.json()["campo"] == "voz"


def test_prompts_por_formato_valor_excede_2000_chars_422(api_cliente) -> None:
    """H8: cada valor de por_formato tiene su propio tope (2000 chars)."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    r = cli.put("/brands/pensionmas/prompts", json={
        "voz": "x", "por_formato": {"listicle": "y" * 2001},
    })
    assert r.status_code == 422 and r.json()["campo"] == "por_formato"


def test_probar_prompt_con_llm_monkeypatcheado(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    guion_fake = {"tema": "gatos", "hook": "h", "caption": "c", "cta": "cta",
                  "slides": [{"text": "h", "rol": "hook", "image_hint": "cat"}]}

    def _fake_generar(tema, *, formato="listicle", n_slides=6, contexto=None,
                      rechazados=None, feedback=None):
        assert tema == "gatos"
        assert n_slides == 4
        return guion_fake

    from src import slideshow_script
    monkeypatch.setattr(slideshow_script, "generar_guion", _fake_generar)

    from api.routers import perfil
    monkeypatch.setattr(perfil.slideshow_script, "generar_guion", _fake_generar)

    r = cli.post("/brands/pensionmas/prompts/probar", json={"tema": "gatos"})
    assert r.status_code == 200 and r.json()["tema"] == "gatos"


def test_probar_prompt_error_llm_devuelve_502_redactado(api_cliente, monkeypatch) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    def _revienta(tema, *, formato="listicle", n_slides=6, contexto=None,
                  rechazados=None, feedback=None):
        raise RuntimeError("clave-secreta-123 inválida en el proveedor")

    from api.routers import perfil
    monkeypatch.setattr(perfil.slideshow_script, "generar_guion", _revienta)
    monkeypatch.setattr(perfil.config, "account_creds",
                        lambda slug: {"LLM_API_KEY": "clave-secreta-123"})

    r = cli.post("/brands/pensionmas/prompts/probar", json={"tema": "gatos"})
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "prueba_fallida"
    assert "clave-secreta-123" not in body["detalle"]


def test_probar_prompt_error_redacta_key_global_del_llm(api_cliente, monkeypatch) -> None:
    """Re-review: `generar_guion` puede usar la key GLOBAL del proveedor
    (DEEPSEEK_API_KEY/ANTHROPIC_API_KEY), no solo `account_creds` de la
    marca — redactar solo `account_creds` (H8) dejaba escapar la global."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    def _revienta(tema, *, formato="listicle", n_slides=6, contexto=None,
                  rechazados=None, feedback=None):
        raise RuntimeError("clave-global-999 inválida en el proveedor")

    from api.routers import perfil
    monkeypatch.setattr(perfil.slideshow_script, "generar_guion", _revienta)
    monkeypatch.setattr(perfil.config, "account_creds", lambda slug: {})
    monkeypatch.setattr(perfil.config, "DEEPSEEK_API_KEY", "clave-global-999")

    r = cli.post("/brands/pensionmas/prompts/probar", json={"tema": "gatos"})
    assert r.status_code == 502
    body = r.json()
    assert body["error"] == "prueba_fallida"
    assert "clave-global-999" not in body["detalle"]


# ---------- presets ----------

def test_presets_listar_marca_propios(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    db.update(cx, "accounts", pid, estilos_json='{"mio": {"texto": "blanco", "roles": {"hook": {}}}}')
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.get("/brands/pensionmas/presets")
    assert r.status_code == 200
    por_nombre = {p["nombre"]: p for p in r.json()}
    assert por_nombre["mio"]["propio"] is True
    assert por_nombre["tiktok_bold"]["propio"] is False


def test_presets_crud_manager(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.put("/brands/pensionmas/presets/mipreset",
               json={"texto": "blanco", "roles": {"hook": {"font": "x"}}})
    assert r.status_code == 403
    H.logout()

    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.put("/brands/pensionmas/presets/mipreset",
               json={"texto": "blanco", "roles": {"hook": {"font": "x"}}})
    assert r.status_code == 200

    r = cli.put("/brands/pensionmas/presets/MalNombre", json={"texto": "a", "roles": {"h": {}}})
    assert r.status_code == 422

    r = cli.put("/brands/pensionmas/presets/otro", json={"texto": "a", "roles": {}})
    assert r.status_code == 422 and r.json()["campo"] == "roles"

    r = cli.get("/brands/pensionmas/presets")
    nombres = {p["nombre"] for p in r.json()}
    assert "mipreset" in nombres

    r = cli.delete("/brands/pensionmas/presets/tiktok_bold")
    assert r.status_code == 404

    r = cli.delete("/brands/pensionmas/presets/mipreset")
    assert r.status_code == 204
    r = cli.get("/brands/pensionmas/presets")
    assert "mipreset" not in {p["nombre"] for p in r.json()}


def test_preset_rechaza_payload_mayor_a_32kb(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    relleno = "x" * (33 * 1024)
    r = cli.put("/brands/pensionmas/presets/grande",
               json={"texto": "blanco", "roles": {"hook": {"nota": relleno}}})
    assert r.status_code == 422


def test_nombre_re_rechaza_traversal_y_caracteres_invalidos() -> None:
    # Unit directo del validador: "../x" trae "/" y nunca podría viajar como
    # un solo segmento de URL (httpx/starlette lo normalizan antes de rutear),
    # así que la garantía real vive aquí, no en un round-trip HTTP.
    from api.routers.perfil import _NOMBRE_RE
    assert _NOMBRE_RE.match("../x") is None
    assert _NOMBRE_RE.match("..") is None
    assert _NOMBRE_RE.match("a b") is None
    assert _NOMBRE_RE.match("tiktok_bold") is not None
    # Re-review: con "$" (en vez de "\Z"), un nombre con salto de línea al
    # final ("tiktok_bold\n") pasaba el regex igual — "$" en Python permite
    # un \n final antes del fin de cadena.
    assert _NOMBRE_RE.match("tiktok_bold\n") is None


def test_preset_nombre_invalido_en_segmento_unico_da_error_json(api_cliente) -> None:
    # ".." SÍ llega al router como un segmento único (va codificado, sin "/"),
    # y debe responder con el shape uniforme de la API, no un 404 crudo de
    # Starlette por "no matching route".
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))

    r = cli.get("/brands/pensionmas/files/previews/%2E%2E.png")
    assert r.status_code == 422
    assert r.json()["error"] == "validacion" and r.json()["campo"] == "nombre"

    r = cli.put("/brands/pensionmas/presets/%2E%2E", json={"texto": "a", "roles": {"h": {}}})
    assert r.status_code == 422
    assert r.json()["error"] == "validacion" and r.json()["campo"] == "nombre"


# ---------- preview (job) + archivo servido ----------

def test_preview_crea_job_y_archivo_se_sirve(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    otra_id = _marca(cx, "otramarca")
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager"), (otra_id, "manager")]))

    from api.routers import perfil
    monkeypatch.setattr(perfil, "PREVIEWS_DIR", tmp_path / "previews")

    r = cli.post("/brands/pensionmas/presets/tiktok_bold/preview", json={"texto": "hola"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    job = db.get(cx, "jobs", job_id)
    assert job["tipo"] == "preset.preview" and job["account_id"] == pid

    # 404 antes de que exista el archivo
    r = cli.get("/brands/pensionmas/files/previews/tiktok_bold.png")
    assert r.status_code == 404

    dest_dir = tmp_path / "previews" / "pensionmas"
    dest_dir.mkdir(parents=True)
    (dest_dir / "tiktok_bold.png").write_bytes(b"fakepng")

    r = cli.get("/brands/pensionmas/files/previews/tiktok_bold.png")
    assert r.status_code == 200 and r.content == b"fakepng"

    # 404 para otra marca (aunque el usuario tenga acceso a ambas)
    r = cli.get("/brands/otramarca/files/previews/tiktok_bold.png")
    assert r.status_code == 404


def test_preview_preset_inexistente_404(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    from api.routers import perfil
    monkeypatch.setattr(perfil, "PREVIEWS_DIR", tmp_path / "previews")
    r = cli.post("/brands/pensionmas/presets/no-existe/preview", json={})
    assert r.status_code in (404, 422)


# ---------- logo ----------

def test_logo_upload_valida_extension_y_tamano(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    from api.routers import perfil
    monkeypatch.setattr(perfil, "BRANDS_DIR", tmp_path / "brands")

    r = cli.post("/brands/pensionmas/logo",
                files={"archivo": ("virus.exe", io.BytesIO(b"MZ..."), "application/octet-stream")})
    assert r.status_code == 422

    grande = b"0" * (2 * 1024 * 1024 + 1)
    r = cli.post("/brands/pensionmas/logo",
                files={"archivo": ("logo.png", io.BytesIO(grande), "image/png")})
    assert r.status_code == 422

    r = cli.post("/brands/pensionmas/logo",
                files={"archivo": ("logo.png", io.BytesIO(b"\x89PNGdata"), "image/png")})
    assert r.status_code == 200
    assert (tmp_path / "brands" / "pensionmas" / "logo.png").exists()

    r = cli.get("/brands/pensionmas/files/logo")
    assert r.status_code == 200 and r.content == b"\x89PNGdata"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_logo_upload_streaming_aborta_sin_escribir_nada(api_cliente, monkeypatch, tmp_path) -> None:
    """H5: lectura por chunks, aborta con 422 antes de tener el archivo
    completo en memoria. Tope monkeypatcheado a un valor chico para no
    necesitar generar 2 MB reales en el test."""
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    from api.routers import perfil
    monkeypatch.setattr(perfil, "BRANDS_DIR", tmp_path / "brands")
    monkeypatch.setattr(perfil, "_MAX_LOGO", 200)  # tope chico

    grande = b"\x89PNG" + b"0" * 500
    r = cli.post("/brands/pensionmas/logo",
                files={"archivo": ("logo.png", io.BytesIO(grande), "image/png")})
    assert r.status_code == 422
    assert not (tmp_path / "brands" / "pensionmas").exists()


def test_logo_svg_con_script_se_rechaza(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    from api.routers import perfil
    monkeypatch.setattr(perfil, "BRANDS_DIR", tmp_path / "brands")

    svg_malicioso = b"<svg><script>alert(1)</script></svg>"
    r = cli.post("/brands/pensionmas/logo",
                files={"archivo": ("logo.svg", io.BytesIO(svg_malicioso), "image/svg+xml")})
    assert r.status_code == 422
    assert not (tmp_path / "brands" / "pensionmas" / "logo.svg").exists()


def test_logo_svg_limpio_se_sirve_como_descarga_con_csp(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    from api.routers import perfil
    monkeypatch.setattr(perfil, "BRANDS_DIR", tmp_path / "brands")

    svg_limpio = b"<svg xmlns='http://www.w3.org/2000/svg'><circle r='5'/></svg>"
    r = cli.post("/brands/pensionmas/logo",
                files={"archivo": ("logo.svg", io.BytesIO(svg_limpio), "image/svg+xml")})
    assert r.status_code == 200

    r = cli.get("/brands/pensionmas/files/logo")
    assert r.status_code == 200
    assert r.headers["content-disposition"] == "attachment; filename=logo.svg"
    assert r.headers["content-security-policy"] == "default-src 'none'"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_logo_solo_manager(api_cliente, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("e@x.com", marcas=[(pid, "editor")]))
    r = cli.post("/brands/pensionmas/logo",
                files={"archivo": ("logo.png", io.BytesIO(b"\x89PNGdata"), "image/png")})
    assert r.status_code == 403


# ---------- PATCH /brands/{slug} extras ----------

def test_patch_brand_campos_extendidos(api_cliente) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("m@x.com", marcas=[(pid, "manager")]))
    r = cli.patch("/brands/pensionmas", json={
        "descripcion": "Somos una pensión digital",
        "sitio_web": "https://pensionmas.mx",
        "hashtags_default": "#pension #retiro",
    })
    assert r.status_code == 200
    assert r.json()["descripcion"] == "Somos una pensión digital"
    assert r.json()["sitio_web"] == "https://pensionmas.mx"

    r = cli.patch("/brands/pensionmas", json={"descripcion": "x" * 601})
    assert r.status_code == 422 and r.json()["campo"] == "descripcion"
    r = cli.patch("/brands/pensionmas", json={"sitio_web": "x" * 201})
    assert r.status_code == 422 and r.json()["campo"] == "sitio_web"
    r = cli.patch("/brands/pensionmas", json={"hashtags_default": "x" * 401})
    assert r.status_code == 422 and r.json()["campo"] == "hashtags_default"


# ---------- preview real de estilo ----------

def test_preview_estilo_sirve_png_y_404_si_no_existe(api_cliente, monkeypatch, tmp_path) -> None:
    cli, cx, H = api_cliente
    pid = _marca(cx)
    H.login(H.usuario("v@x.com", marcas=[(pid, "editor")]))
    from src import estilo_preview
    png = tmp_path / "p.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    llamadas = []

    def falso_png_de(cx_, slug, estilo):
        llamadas.append((slug, estilo))
        if estilo == "no_existe":
            raise KeyError(estilo)
        return png
    monkeypatch.setattr(estilo_preview, "png_de", falso_png_de)
    r = cli.get("/brands/pensionmas/estilos/editorial/preview.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG") and llamadas == [("pensionmas", "editorial")]
    assert cli.get("/brands/pensionmas/estilos/no_existe/preview.png").status_code == 404
    assert cli.get("/brands/pensionmas/estilos/..%2Fx/preview.png").status_code in (404, 422)
    H.logout()
    assert cli.get("/brands/pensionmas/estilos/editorial/preview.png").status_code == 401
