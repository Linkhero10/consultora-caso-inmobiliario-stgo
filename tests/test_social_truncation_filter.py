"""Regresión: filtro determinista de posts de X/Twitter truncados o con
muro de login capturado en vez del tuit real (decisión de Felipe,
2026-09-15). No llama a la API; se aplica antes de load_classifiable_documents
enviar el documento al modelo."""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SCRIPT_DIR))

import classify as luna  # noqa: E402


def test_login_wall_text_is_flagged():
    text = 'Post Iniciar sesión Regístrate Post Iniciar sesión Regístrate TECHO-Chile en X: "algo"'
    reason = luna._is_incomplete_social_post("https://x.com/TECHOChile/status/123", text)
    assert reason == "muro_login_capturado_en_vez_del_tuit"


def test_javascript_wall_text_is_flagged():
    text = "JavaScript no está disponible. We've detected that JavaScript is disabled in this browser."
    reason = luna._is_incomplete_social_post("https://x.com/TomasVodanovic/all", text)
    assert reason == "muro_login_capturado_en_vez_del_tuit"


def test_text_not_ending_in_punctuation_is_flagged_truncated():
    text = "CONSTRUYAN EL SEGUNDO PUENTE Y DEJEN DE DARSE VUELTAS. Hubo un compromiso... se insistió todo el verano con Fernando Sarmiento y Nada"
    reason = luna._is_incomplete_social_post("https://x.com/alto_macul/status/123", text)
    assert reason == "texto_cortado_a_mitad_de_frase"


def test_complete_tweet_ending_in_punctuation_is_not_flagged():
    text = 'CIPER Chile en X: "Alerta: aunque mega edificios han colapsado servicios públicos, siguen aprobándose proyectos similares."'
    reason = luna._is_incomplete_social_post("https://x.com/ciper/status/123", text)
    assert reason == ""


def test_non_social_domain_is_never_flagged_even_if_it_looks_truncated():
    text = "Este es un articulo de un medio que termina sin punto final porque asi lo extrajo el scraper"
    reason = luna._is_incomplete_social_post("https://www.latercera.com/nota/algo", text)
    assert reason == ""


def test_empty_text_is_flagged():
    reason = luna._is_incomplete_social_post("https://x.com/alguien/status/123", "   ")
    assert reason == "sin_texto"
