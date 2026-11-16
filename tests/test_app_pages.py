"""Every page of the app renders without an exception, and the team workspace records what people do."""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]




@pytest.mark.parametrize("page", ["page_markets", "page_stress", "page_upload", "page_alerts", "page_controls", "page_models", "page_agent", "page_evidence", "page_team"])
def test_page_renders(page, tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    monkeypatch.setenv("ATLAS_DB", str(tmp_path / "ws.db"))
    from streamlit.testing.v1 import AppTest
    script = f"""
import sys
sys.path.insert(0, {str(ROOT / 'src')!r}); sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from atlas_app.state import init
from atlas_app import pages as P
init()
st.session_state['_pages'] = {{'overview': st.Page(P.page_overview, title='x', default=True)}}
P.{page}()
"""
    at = AppTest.from_string(script, default_timeout=180).run()
    assert not at.exception, at.exception


def test_alert_decision_is_saved_for_the_team(tmp_path, monkeypatch):
    pytest.importorskip("streamlit")
    monkeypatch.setenv("ATLAS_DB", str(tmp_path / "ws.db"))
    from streamlit.testing.v1 import AppTest
    script = f"""
import sys
sys.path.insert(0, {str(ROOT / 'src')!r}); sys.path.insert(0, {str(ROOT)!r})
import streamlit as st
from atlas_app.state import init
from atlas_app import pages as P
init()
st.session_state.user = 'ana'
P.page_alerts()
"""
    at = AppTest.from_string(script, default_timeout=180).run()
    next(b for b in at.button if "Escalate" in b.label).click().run()
    assert not at.exception
    from atlas.workspace import Workspace
    ws = Workspace(tmp_path / "ws.db")
    assert any(e["kind"] == "case_decision" and e["user"] == "ana" for e in ws.events()) and ws.verify()
