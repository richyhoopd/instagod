"""El host de Graph depende del tipo de token: EAA (Facebook Login) solo
funciona en graph.facebook.com; IGAA (Instagram Login) en el host configurado."""
from unittest import mock

from src import instagram as ig


def test_token_eaa_va_a_graph_facebook():
    assert ig._base("EAAxyz").startswith("https://graph.facebook.com/")


def test_token_igaa_y_sin_token_usan_el_host_configurado():
    with mock.patch.object(ig.config, "IG_GRAPH_BASE", "https://graph.instagram.com"):
        assert ig._base("IGAAxyz").startswith("https://graph.instagram.com/")
        assert ig._base().startswith("https://graph.instagram.com/")


def test_create_container_usa_el_host_del_token_de_la_marca():
    resp = mock.Mock(status_code=200)
    resp.json.return_value = {"id": "c1"}
    with mock.patch.object(ig.requests, "post", return_value=resp) as post:
        ig._create_container("https://x/img.png", "hola", {"user_id": "178", "token": "EAAabc"})
    assert post.call_args.args[0].startswith("https://graph.facebook.com/")
    assert post.call_args.args[0].endswith("/178/media")
