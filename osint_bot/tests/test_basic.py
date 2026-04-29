"""Tests que NO requieren red ni credenciales.

Ejecutar:
    TELEGRAM_TOKEN=dummy ANTHROPIC_API_KEY=dummy pytest tests/
"""
from handlers.commands import _chunk_text
from handlers.messages import _looks_like_question
from services.osint import format_results


def test_question_heuristic_spanish():
    assert _looks_like_question("¿Dónde estudió?")
    assert _looks_like_question("qué hace ahora")
    assert _looks_like_question("Cuándo nació?")
    assert _looks_like_question("dime su biografía")


def test_question_heuristic_english():
    assert _looks_like_question("What does she do?")
    assert _looks_like_question("where was he born")


def test_not_a_question():
    assert not _looks_like_question("Ada Lovelace")
    assert not _looks_like_question("torvalds")
    assert not _looks_like_question("")


def test_chunk_text_short():
    assert _chunk_text("hola", 100) == ["hola"]


def test_chunk_text_respects_newlines():
    text = "\n".join([f"line-{i}" for i in range(500)])
    chunks = _chunk_text(text, 500)
    assert all(len(c) <= 500 for c in chunks)
    # Reconstruible con \n entre chunks.
    assert "\n".join(chunks) == text


def test_format_results_with_empty_sources():
    out = format_results(
        {
            "query": "X",
            "wikipedia": None,
            "wikidata": None,
            "github": None,
            "linkedin": [],
            "twitter": [],
            "news": [],
            "web": [],
        }
    )
    assert "Resultados de búsqueda para:" in out
    assert "sin resultados" in out


def test_format_results_escapes_html():
    out = format_results(
        {
            "query": "<script>",
            "wikipedia": None,
            "wikidata": None,
            "github": None,
            "linkedin": [],
            "twitter": [],
            "news": [],
            "web": [],
        }
    )
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_format_results_shows_top_web_results():
    web = [
        {"title": f"Resultado {i}", "url": f"https://example.com/{i}"}
        for i in range(1, 9)
    ]
    out = format_results(
        {
            "query": "Prueba",
            "wikipedia": None,
            "wikidata": None,
            "github": None,
            "linkedin": [],
            "twitter": [],
            "news": [],
            "web": web,
        }
    )
    assert "Resultados web" in out
    assert out.count("<a href=") >= 8
    assert "Resultado 8" in out
