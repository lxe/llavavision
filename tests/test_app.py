"""Tests for llavavision app.py — unit and integration."""

import json
import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    """Flask test client with llamacpp backend (default)."""
    monkeypatch.delenv("VISION_BACKEND", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    import app as app_module
    import importlib
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


@pytest.fixture
def minimax_client(monkeypatch):
    """Flask test client with minimax backend."""
    monkeypatch.setenv("VISION_BACKEND", "minimax")
    monkeypatch.setenv("MINIMAX_API_KEY", "test-key")
    monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7")
    import app as app_module
    import importlib
    importlib.reload(app_module)
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as c:
        yield c


# ---------------------------------------------------------------------------
# Unit tests — llamacpp backend
# ---------------------------------------------------------------------------

class TestLlamaCppBackend:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_describe_calls_llamacpp(self, client):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [
            b'data: {"content":"A cat","stop":false}',
        ]
        with patch("app.requests.post", return_value=mock_response) as mock_post:
            resp = client.post(
                "/describe",
                json={"image": "base64data"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "localhost:8080" in call_kwargs[0][0]
        payload = call_kwargs[1]["json"]
        assert payload["image_data"][0]["data"] == "base64data"
        assert payload["stream"] is True

    def test_describe_streams_content(self, client):
        chunks = [
            b'data: {"content":"A ","stop":false}',
            b'data: {"content":"cat","stop":false}',
        ]
        mock_response = MagicMock()
        mock_response.iter_content.return_value = chunks
        with patch("app.requests.post", return_value=mock_response):
            resp = client.post(
                "/describe",
                json={"image": "abc"},
                content_type="application/json",
            )
        assert b"A " in resp.data or b"cat" in resp.data

    def test_describe_skips_invalid_chunks(self, client):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = [b"bad-chunk", b""]
        with patch("app.requests.post", return_value=mock_response):
            resp = client.post(
                "/describe",
                json={"image": "abc"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        assert resp.data == b""

    def test_describe_uses_custom_llamacpp_url(self, monkeypatch):
        monkeypatch.setenv("LLAMACPP_URL", "http://custom-host:9090/completion")
        import app as app_module
        import importlib
        importlib.reload(app_module)
        assert app_module.LLAMACPP_URL == "http://custom-host:9090/completion"

    def test_describe_prompt_format(self, client):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = []
        with patch("app.requests.post", return_value=mock_response) as mock_post:
            client.post("/describe", json={"image": "img"}, content_type="application/json")
        payload = mock_post.call_args[1]["json"]
        assert "USER:" in payload["prompt"]
        assert "ASSISTANT:" in payload["prompt"]
        assert payload["n_predict"] == 128


# ---------------------------------------------------------------------------
# Unit tests — MiniMax backend
# ---------------------------------------------------------------------------

class TestMiniMaxBackend:
    def _make_sse_line(self, content, stop=False):
        obj = {"choices": [{"delta": {"content": content}, "finish_reason": None if not stop else "stop"}]}
        return b"data: " + json.dumps(obj).encode()

    def test_describe_calls_minimax_api(self, minimax_client):
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            self._make_sse_line("A dog"),
            b"data: [DONE]",
        ]
        with patch("app.requests.post", return_value=mock_response) as mock_post:
            resp = minimax_client.post(
                "/describe",
                json={"image": "base64img"},
                content_type="application/json",
            )
        assert resp.status_code == 200
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert "minimax.io" in url
        payload = mock_post.call_args[1]["json"]
        assert payload["model"] == "MiniMax-M2.7"
        assert payload["stream"] is True

    def test_describe_sends_base64_image(self, minimax_client):
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [b"data: [DONE]"]
        with patch("app.requests.post", return_value=mock_response) as mock_post:
            minimax_client.post("/describe", json={"image": "MYBASE64"}, content_type="application/json")
        content_blocks = mock_post.call_args[1]["json"]["messages"][0]["content"]
        image_block = next(b for b in content_blocks if b["type"] == "image_url")
        assert "MYBASE64" in image_block["image_url"]["url"]
        assert "data:image/jpeg;base64," in image_block["image_url"]["url"]

    def test_describe_streams_minimax_content(self, minimax_client):
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            self._make_sse_line("Hello "),
            self._make_sse_line("world"),
            b"data: [DONE]",
        ]
        with patch("app.requests.post", return_value=mock_response):
            resp = minimax_client.post("/describe", json={"image": "x"}, content_type="application/json")
        assert b"Hello " in resp.data
        assert b"world" in resp.data

    def test_missing_api_key_returns_500(self, monkeypatch):
        monkeypatch.setenv("VISION_BACKEND", "minimax")
        monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
        import app as app_module
        import importlib
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        with app_module.app.test_client() as c:
            resp = c.post("/describe", json={"image": "x"}, content_type="application/json")
        assert resp.status_code == 500

    def test_temperature_clamped_above_zero(self, monkeypatch):
        monkeypatch.setenv("VISION_BACKEND", "minimax")
        monkeypatch.setenv("MINIMAX_API_KEY", "key")
        monkeypatch.setenv("MINIMAX_TEMPERATURE", "0.0")
        import app as app_module
        import importlib
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [b"data: [DONE]"]
        with app_module.app.test_client() as c:
            with patch("app.requests.post", return_value=mock_response) as mock_post:
                c.post("/describe", json={"image": "x"}, content_type="application/json")
        temperature = mock_post.call_args[1]["json"]["temperature"]
        assert temperature > 0.0

    def test_temperature_clamped_at_most_one(self, monkeypatch):
        monkeypatch.setenv("VISION_BACKEND", "minimax")
        monkeypatch.setenv("MINIMAX_API_KEY", "key")
        monkeypatch.setenv("MINIMAX_TEMPERATURE", "2.5")
        import app as app_module
        import importlib
        importlib.reload(app_module)
        app_module.app.config["TESTING"] = True
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [b"data: [DONE]"]
        with app_module.app.test_client() as c:
            with patch("app.requests.post", return_value=mock_response) as mock_post:
                c.post("/describe", json={"image": "x"}, content_type="application/json")
        temperature = mock_post.call_args[1]["json"]["temperature"]
        assert temperature <= 1.0

    def test_minimax_skips_invalid_sse_lines(self, minimax_client):
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [
            b"",
            b"not-data",
            b"data: {bad json}",
            b"data: [DONE]",
        ]
        with patch("app.requests.post", return_value=mock_response):
            resp = minimax_client.post("/describe", json={"image": "x"}, content_type="application/json")
        assert resp.status_code == 200

    def test_minimax_uses_custom_model(self, monkeypatch):
        monkeypatch.setenv("VISION_BACKEND", "minimax")
        monkeypatch.setenv("MINIMAX_API_KEY", "key")
        monkeypatch.setenv("MINIMAX_MODEL", "MiniMax-M2.7-highspeed")
        import app as app_module
        import importlib
        importlib.reload(app_module)
        assert app_module.MINIMAX_MODEL == "MiniMax-M2.7-highspeed"

    def test_minimax_sends_auth_header(self, minimax_client):
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [b"data: [DONE]"]
        with patch("app.requests.post", return_value=mock_response) as mock_post:
            minimax_client.post("/describe", json={"image": "x"}, content_type="application/json")
        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer test-key"

    def test_minimax_text_prompt_included(self, minimax_client):
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [b"data: [DONE]"]
        with patch("app.requests.post", return_value=mock_response) as mock_post:
            minimax_client.post("/describe", json={"image": "x"}, content_type="application/json")
        content_blocks = mock_post.call_args[1]["json"]["messages"][0]["content"]
        text_block = next(b for b in content_blocks if b["type"] == "text")
        assert "Describe" in text_block["text"]


# ---------------------------------------------------------------------------
# Integration tests — backend routing
# ---------------------------------------------------------------------------

class TestBackendRouting:
    def test_default_backend_is_llamacpp(self, monkeypatch):
        monkeypatch.delenv("VISION_BACKEND", raising=False)
        import app as app_module
        import importlib
        importlib.reload(app_module)
        assert app_module.VISION_BACKEND == "llamacpp"

    def test_minimax_backend_env_selects_minimax(self, monkeypatch):
        monkeypatch.setenv("VISION_BACKEND", "minimax")
        import app as app_module
        import importlib
        importlib.reload(app_module)
        assert app_module.VISION_BACKEND == "minimax"

    def test_describe_routes_to_minimax_when_env_set(self, minimax_client):
        mock_response = MagicMock()
        mock_response.iter_lines.return_value = [b"data: [DONE]"]
        with patch("app.describe_with_minimax", wraps=lambda x: MagicMock(status_code=200)) as mock_fn:
            with patch("app.requests.post", return_value=mock_response):
                minimax_client.post("/describe", json={"image": "x"}, content_type="application/json")
        mock_fn.assert_called_once()

    def test_describe_routes_to_llamacpp_by_default(self, client):
        mock_response = MagicMock()
        mock_response.iter_content.return_value = []
        with patch("app.describe_with_llamacpp", wraps=lambda x: MagicMock(status_code=200)) as mock_fn:
            with patch("app.requests.post", return_value=mock_response):
                client.post("/describe", json={"image": "x"}, content_type="application/json")
        mock_fn.assert_called_once()
