"""The role book decides what may be bought at all, so its failure modes are
the interesting part: silence must never read as approval."""

from __future__ import annotations

from pathlib import Path

from fantasy_agent.intel.roles import load_roles
from fantasy_agent.models import SquadRole

SAMPLE = """
key:
  - Angel Perez
  - Mandi
important:
  - Xavi Espart
bench:
  - Adama Traore
nonsense_tier:
  - Somebody
"""


def write(tmp_path: Path, body: str = SAMPLE) -> Path:
    path = tmp_path / "roles.yml"
    path.write_text(body, encoding="utf-8")
    return path


class TestLookup:
    def test_reads_the_tiers(self, tmp_path: Path) -> None:
        roles = load_roles(write(tmp_path))
        assert roles.role_of("Angel Perez") is SquadRole.KEY
        assert roles.role_of("Xavi Espart") is SquadRole.IMPORTANT
        assert roles.role_of("Adama Traore") is SquadRole.BENCH

    def test_ignores_case_and_stray_whitespace(self, tmp_path: Path) -> None:
        assert load_roles(write(tmp_path)).role_of("  mandi ") is SquadRole.KEY

    def test_tries_each_key_it_is_given(self, tmp_path: Path) -> None:
        roles = load_roles(write(tmp_path))
        assert roles.role_of("unknown id", "Mandi") is SquadRole.KEY


class TestFailureModes:
    def test_an_unlisted_player_is_unknown_and_therefore_unbuyable(self, tmp_path: Path) -> None:
        assert load_roles(write(tmp_path)).role_of("Nobody") is SquadRole.UNKNOWN

    def test_a_missing_file_degrades_instead_of_crashing(self, tmp_path: Path) -> None:
        roles = load_roles(tmp_path / "absent.yml")
        assert len(roles) == 0
        assert "missing" in roles.source

    def test_an_unrecognised_tier_is_skipped_not_guessed(self, tmp_path: Path) -> None:
        assert load_roles(write(tmp_path)).role_of("Somebody") is SquadRole.UNKNOWN

    def test_an_empty_file_is_valid_and_buys_nothing(self, tmp_path: Path) -> None:
        assert len(load_roles(write(tmp_path, ""))) == 0
