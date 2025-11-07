import streamlit as st

from src.ui.helpers import streaming


def test_stream_with_fallback_uses_write_stream(monkeypatch):
    recorded = []

    def fake_write_stream(generator):
        for chunk in generator:
            recorded.append(chunk)

    monkeypatch.setattr(st, "write_stream", fake_write_stream, raising=False)
    monkeypatch.setattr(streaming, "has_feature", lambda name: name == "write_stream")

    result = streaming.stream_with_fallback(lambda: iter(["Step 1", "Step 2"]))

    assert recorded == ["Step 1", "Step 2"]
    assert result == ["Step 1", "Step 2"]


def test_stream_with_fallback_without_write_stream(monkeypatch):
    outputs = []

    class Placeholder:
        def markdown(self, value: str) -> None:
            outputs.append(value)

    monkeypatch.delattr(st, "write_stream", raising=False)
    monkeypatch.setattr(st, "empty", lambda: Placeholder())
    monkeypatch.setattr(streaming, "has_feature", lambda name: False)

    result = streaming.stream_with_fallback(lambda: iter(["Alpha", "Beta"]))

    assert "Beta" in outputs[-1]
    assert result == ["Alpha", "Beta"]


def test_status_with_steps_calls_callbacks(monkeypatch):
    messages = []
    executed = []

    class DummyStatus:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def write(self, message):
            messages.append(message)

        def update(self, **kwargs):
            messages.append(kwargs.get("label"))

    monkeypatch.setattr(streaming, "has_feature", lambda name: name == "status")
    monkeypatch.setattr(st, "status", lambda *args, **kwargs: DummyStatus())

    def callback():
        executed.append("done")

    steps = [
        ":material/info: Prepare",
        (":material/play_arrow: Execute", callback),
    ]

    result = list(streaming.status_with_steps("Test Status", steps))

    assert executed == ["done"]
    assert result == [
        ":material/info: Prepare",
        ":material/play_arrow: Execute",
    ]
    assert messages[0] == ":material/info: Prepare"


def test_show_success_toast_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(streaming, "has_feature", lambda name: False)
    monkeypatch.setattr(st, "success", lambda message: calls.append(message))

    streaming.show_success_toast("All good")

    assert calls == ["All good"]


def test_handle_streaming_error_with_retry(monkeypatch):
    errors = []
    retries = []
    rerun_called = []
    buttons = iter([True, False])

    monkeypatch.setattr(st, "error", lambda message: errors.append(message))
    monkeypatch.setattr(st, "warning", lambda message: errors.append(message))
    monkeypatch.setattr(st, "button", lambda *args, **kwargs: next(buttons))
    monkeypatch.setattr(st, "rerun", lambda: rerun_called.append(True))
    monkeypatch.setattr(streaming, "show_success_toast", lambda message: retries.append(message))

    streaming.handle_streaming_error(Exception("boom"), "test op", retry_func=lambda: retries.append("retried"))

    assert "Error during test op" in errors[0]
    assert "retried" in retries
    assert rerun_called == [True]


def test_show_pdf_preview_with_feature(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    captured = {}

    monkeypatch.setattr(streaming, "has_feature", lambda name: name == "pdf")
    monkeypatch.setattr(st, "pdf", lambda path, height: captured.update({"path": path, "height": height}))

    assert streaming.show_pdf_preview(pdf_path, height=400)
    assert captured["path"] == str(pdf_path)
    assert captured["height"] == 400


def test_show_pdf_preview_without_feature(monkeypatch, tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF")
    infos = []
    downloads = []

    monkeypatch.setattr(streaming, "has_feature", lambda name: False)
    monkeypatch.setattr(st, "info", lambda message: infos.append(message))
    monkeypatch.setattr(
        st,
        "download_button",
        lambda **kwargs: downloads.append(kwargs["file_name"]),
    )

    assert not streaming.show_pdf_preview(pdf_path, height=400)
    assert downloads == [pdf_path.name]
