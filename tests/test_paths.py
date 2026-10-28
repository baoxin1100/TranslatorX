import sys

from translatorx import paths


def test_source_runs_keep_data_in_the_repository(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert paths.install_root() == paths.PACKAGE_ROOT
    assert paths.app_data_dir() == paths.PACKAGE_ROOT


def test_frozen_build_keeps_data_beside_the_executable(monkeypatch, tmp_path):
    executable = tmp_path / "TranslatorX" / "TranslatorX.exe"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert paths.install_root() == executable.parent
    assert paths.app_data_dir() == executable.parent
    assert paths.config_file_path() == executable.parent / "config" / "translatorx.json"
    assert paths.log_file_path() == executable.parent / "logs" / "translatorx.log"
