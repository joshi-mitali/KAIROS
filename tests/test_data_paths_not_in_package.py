"""Output paths must follow KAIROS_DATA_DIR, never the (read-only) install dir."""
from pathlib import Path

import kairos
from kairos.agents.adk_analysts.base_analyst import BaseADKAnalyst
from kairos.config import settings as settings_mod
from kairos.phase2_orchestrator import Phase2Orchestrator


def test_workspace_root_follows_data_dir(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("KAIROS_DATA_DIR", str(data))
    monkeypatch.setattr(settings_mod, "_SETTINGS_INSTANCE", None)
    pkg = Path(kairos.__file__).resolve().parent
    try:
        a = BaseADKAnalyst()
        assert a.data_dir == data.resolve()
        assert a.workspace_root == tmp_path.resolve()
        assert pkg not in a.workspace_root.parents and a.workspace_root != pkg
        assert (a.workspace_root / "data/processed/trading_proposals.json").is_relative_to(data)
    finally:
        monkeypatch.setattr(settings_mod, "_SETTINGS_INSTANCE", None)
