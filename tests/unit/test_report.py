# -*- coding: utf-8 -*-
"""Team telemetry reporting: config store, mirror copy, stats pickup."""
import json
import os

import pytest

from revit_mcp_server import local_config, report, stats, telemetry_db


@pytest.fixture
def machine(tmp_path, monkeypatch):
    """A fake machine: LOCALAPPDATA with some telemetry, plus a team folder."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("USERNAME", "lstevenson")
    snip_dir = tmp_path / "local" / "revit-mcp" / "snippets"
    snip_dir.mkdir(parents=True)
    (snip_dir / "snippets-202608.jsonl").write_text(
        json.dumps({"v": 1, "ts": "2026-08-15T12:00:00+00:00", "session": "s1",
                    "hash": "h1", "code": "x", "description": "d",
                    "ok": True, "route_ok": True, "duration_ms": 1,
                    "output_chars": 1}) + "\n",
        encoding="utf-8",
    )
    team = tmp_path / "team"
    team.mkdir()
    return tmp_path, team


class TestLocalConfig:
    def test_roundtrip(self, machine):
        assert local_config.report_dir() is None
        local_config.save(report_dir=r"\\share\telemetry")
        assert local_config.report_dir() == r"\\share\telemetry"

    def test_corrupt_config_is_empty(self, machine, tmp_path):
        path = tmp_path / "local" / "revit-mcp" / "config.json"
        path.write_text("{broken", encoding="utf-8")
        assert local_config.load() == {}


class TestReport:
    def test_unconfigured_says_how(self, machine, capsys):
        assert report.run_report() == 1
        assert "--to" in capsys.readouterr().out

    def test_mirrors_into_username_folder(self, machine):
        tmp_path, team = machine
        local_config.save(report_dir=str(team))
        assert report.run_report() == 0
        copied = team / "lstevenson" / "snippets" / "snippets-202608.jsonl"
        assert copied.is_file()
        assert "h1" in copied.read_text(encoding="utf-8")

    def test_recopy_only_when_grown(self, machine, capsys):
        tmp_path, team = machine
        local_config.save(report_dir=str(team))
        report.run_report()
        capsys.readouterr()
        report.run_report()
        assert "0 file(s) refreshed" in capsys.readouterr().out
        # append a line -> size changes -> recopied
        src = tmp_path / "local" / "revit-mcp" / "snippets" / "snippets-202608.jsonl"
        with open(src, "a", encoding="utf-8") as f:
            f.write(json.dumps({"v": 1, "ts": "2026-08-15T13:00:00+00:00",
                                "session": "s1", "hash": "h1", "code": "x",
                                "description": "d", "ok": True,
                                "route_ok": True, "duration_ms": 2,
                                "output_chars": 1}) + "\n")
        report.run_report()
        assert "1 file(s) refreshed" in capsys.readouterr().out

    def test_unreachable_target_fails_soft(self, machine, capsys):
        local_config.save(report_dir=r"Q:\definitely\not\a\drive")
        assert report.run_report() == 1
        assert "catch up next run" in capsys.readouterr().out


class TestStatsPicksUpTeamFolder:
    def test_team_member_becomes_second_source(self, machine, capsys):
        tmp_path, team = machine
        local_config.save(report_dir=str(team))
        # simulate a coworker's reported folder
        coworker = team / "jsmith" / "snippets"
        coworker.mkdir(parents=True)
        (coworker / "snippets-202608.jsonl").write_text(
            json.dumps({"v": 1, "ts": "2026-08-15T12:30:00+00:00",
                        "session": "s9", "hash": "h1", "code": "x",
                        "description": "d", "ok": True, "route_ok": True,
                        "duration_ms": 3, "output_chars": 1}) + "\n",
            encoding="utf-8",
        )
        stats.run_stats(days=3650)
        out = capsys.readouterr().out
        # same hash, two sources
        assert "h1" in out
        line = next(l for l in out.splitlines() if l.startswith("h1"))
        columns = line.split()
        assert columns[3] == "2"  # sources column
