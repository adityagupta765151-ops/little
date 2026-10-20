"""The installed app: where it reads its own files and where it keeps yours."""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

from jarvis.app import config

ROOT = Path(__file__).resolve().parents[1]


class TestFromTheProjectFolder:
    def test_app_files_are_the_project_folder(self):
        assert config.FROZEN is False
        assert config.APP_DIR == config.BASE_DIR
        assert (config.APP_DIR / "ui" / "index.html").exists()


class TestInstalled:
    def test_your_data_lives_in_your_profile_and_the_app_files_in_the_bundle(self, tmp_path, monkeypatch):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / ".env.example").write_text("GEMINI_API_KEY=your-key-here\n", encoding="utf-8")
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
        try:
            fresh = importlib.reload(config)
            data = tmp_path / "home" / "AppData" / "Local" / "Little"
            assert fresh.BASE_DIR == data
            assert fresh.APP_DIR == bundle
            # First start: a .env to fill in, copied from the example.
            assert (data / ".env").read_text(encoding="utf-8").startswith("GEMINI_API_KEY=your-key")
        finally:
            monkeypatch.undo()
            importlib.reload(config)

    def test_the_recipe_ships_the_window_and_the_example_settings(self):
        spec = (ROOT / "packaging" / "little.spec").read_text(encoding="utf-8")
        assert '"ui"' in spec and ".env.example" in spec and "little.ico" in spec

    def test_the_installer_never_overwrites_your_settings(self):
        iss = (ROOT / "packaging" / "little.iss").read_text(encoding="utf-8")
        assert "onlyifdoesntexist uninsneveruninstall" in iss
        assert "PrivilegesRequired=lowest" in iss
