import types

from src.ui import app
from src.ui.utils import navigation_links


def test_page_spec_to_navigation_page(monkeypatch):
    calls = []

    def fake_page(script, title, icon):
        calls.append({"script": script, "title": title, "icon": icon})
        return types.SimpleNamespace(script=script, title=title, icon=icon)

    monkeypatch.setattr(app.st, "Page", fake_page)

    spec = app.PageSpec(title="Test Page", section="Operations", icon=":material/test:", script="pages/test.py")
    page = spec.to_navigation_page()

    assert page.script == "pages/test.py"
    assert calls[0]["icon"] == ":material/test:"


def test_render_navigation_with_pages_uses_streamlit_navigation(monkeypatch):
    created_pages = {}

    def fake_page(script, title, icon):
        page = types.SimpleNamespace(script=script, title=title, icon=icon)
        created_pages[script] = page
        return page

    class NavigationStub:
        def __init__(self, structure):
            self.structure = structure
            self.ran = False

        def run(self):
            self.ran = True

    navigation_stub = {}

    def fake_navigation(structure):
        stub = NavigationStub(structure)
        navigation_stub["instance"] = stub
        return stub

    monkeypatch.setattr(app.st, "Page", fake_page)
    monkeypatch.setattr(app.st, "navigation", fake_navigation)

    app._render_navigation_with_pages()

    assert created_pages, "Expected navigation pages to be created"
    stub = navigation_stub.get("instance")
    assert stub is not None, "Navigation should be invoked"
    expected_structure = {}
    for spec in app.PAGE_REGISTRY:
        if not spec.script:
            continue
        expected_structure.setdefault(spec.section, []).append(spec.script)

    assert list(stub.structure.keys()) == list(expected_structure.keys())
    for section, scripts in expected_structure.items():
        pages = stub.structure[section]
        assert [page.script for page in pages] == scripts
        for page in pages:
            assert page is created_pages[page.script]

    assert stub.ran is True


def test_render_navigation_link_uses_page_link(monkeypatch):
    recorded = {}

    monkeypatch.setattr(navigation_links, "has", lambda name: name == "page_link")

    def fake_page_link(script, label, icon):
        recorded.update(script=script, label=label, icon=icon)

    monkeypatch.setattr(navigation_links.st, "page_link", fake_page_link)

    navigation_links.render_navigation_link(
        "pages/next.py",
        label="Go Next",
        icon=":material/arrow_forward:",
    )

    assert recorded == {
        "script": "pages/next.py",
        "label": "Go Next",
        "icon": ":material/arrow_forward:",
    }


def test_render_navigation_link_falls_back_to_caption(monkeypatch):
    monkeypatch.setattr(navigation_links, "has", lambda name: False)

    captured = {}

    def fake_caption(message):
        captured["message"] = message

    monkeypatch.setattr(navigation_links.st, "caption", fake_caption)

    navigation_links.render_navigation_link(
        "pages/next.py",
        label="Go Next",
        icon=":material/arrow_forward:",
        help_text="Use the navigation menu to continue.",
    )

    assert captured["message"] == "Use the navigation menu to continue."
