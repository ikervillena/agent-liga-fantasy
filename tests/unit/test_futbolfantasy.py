"""The scouting scraper, against a real captured club page.

The fixture is Levante's hierarchy page exactly as the site served it. Parsing
is checked against it rather than against a hand-made sample, because the
failure mode that matters is the site changing its markup — and only real
markup can catch that.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fantasy.domain.models import SquadRole
from fantasy.sources.scouting.futbolfantasy import (
    build_index,
    club_url,
    discover_clubs,
    parse_roles,
)
from fantasy.sources.scouting.roles import RoleBook

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "futbolfantasy"
    / "jerarquias_levante.html"
)


@pytest.fixture
def page() -> str:
    return FIXTURE.read_text(encoding="utf-8", errors="replace")


class TestParsing:
    def test_reads_the_whole_squad(self, page: str):
        assert len(parse_roles(page)) == 25

    def test_assigns_the_tier_from_the_section_heading(self, page: str):
        roles = parse_roles(page)
        assert roles["Aissa Mandi"] is SquadRole.KEY
        assert roles["Manu Sánchez"] is SquadRole.IMPORTANT

    def test_covers_every_tier(self, page: str):
        found = set(parse_roles(page).values())
        assert found == {
            SquadRole.KEY,
            SquadRole.IMPORTANT,
            SquadRole.ROTATION,
            SquadRole.IMPACT_SUB,
            SquadRole.BENCH,
        }

    def test_a_player_listed_twice_keeps_his_first_tier(self, page: str):
        """Injury blocks repeat players already listed in a tier."""
        roles = parse_roles(page)
        assert roles["Aissa Mandi"] is SquadRole.KEY

    def test_unrecognisable_markup_yields_nothing_rather_than_raising(self):
        """A silent empty result is safe: unknown roles fail the starter filter."""
        assert parse_roles("<html><body><p>nothing here</p></body></html>") == {}


class TestClubDiscovery:
    def test_finds_every_club_in_the_division(self, page: str):
        clubs = discover_clubs(page)
        assert len(clubs) == 20
        assert "levante" in clubs
        assert "real-madrid" in clubs

    def test_builds_the_expected_url(self):
        assert club_url("levante").endswith("/laliga/equipos/levante/jerarquias")


class TestNameIndex:
    """Bridging "Aissa Mandi" on the site and "Mandi" in the game."""

    def test_indexes_both_the_full_name_and_the_surname(self):
        index = build_index({"Aissa Mandi": SquadRole.KEY})
        book = RoleBook(index)
        assert book.role_of("Aissa Mandi") is SquadRole.KEY
        assert book.role_of("Mandi") is SquadRole.KEY

    def test_an_ambiguous_surname_refuses_to_guess(self):
        """Two players, one surname, different tiers: the alias is not indexed."""
        index = build_index(
            {"Pablo García": SquadRole.KEY, "Sergio García": SquadRole.BENCH}
        )
        book = RoleBook(index)
        assert book.role_of("García") is SquadRole.UNKNOWN
        assert book.role_of("Pablo García") is SquadRole.KEY

    def test_a_shared_surname_in_one_tier_is_still_usable(self):
        index = build_index({"Pablo García": SquadRole.KEY, "Sergio García": SquadRole.KEY})
        assert RoleBook(index).role_of("García") is SquadRole.KEY

    def test_a_full_name_is_never_shadowed_by_somebody_elses_surname(self):
        index = build_index({"Mandi": SquadRole.BENCH, "Aissa Mandi": SquadRole.KEY})
        assert RoleBook(index).role_of("Mandi") is SquadRole.BENCH

    def test_single_word_names_need_no_alias(self):
        index = build_index({"Dela": SquadRole.KEY})
        assert set(index) == {"dela"}

    def test_accents_do_not_break_a_match(self):
        """The sources disagree about accents, and so do humans typing overrides."""
        index = build_index({"Ángel Pérez": SquadRole.KEY})
        book = RoleBook(index)
        assert book.role_of("Angel Perez") is SquadRole.KEY
        assert book.role_of("Perez") is SquadRole.KEY

    def test_the_real_squad_resolves_by_game_nicknames(self, page: str):
        """End to end: the names the game actually uses must resolve."""
        book = RoleBook(build_index(parse_roles(page)))
        assert book.role_of("Mandi") is SquadRole.KEY
        assert book.role_of("Olasagasti") is SquadRole.KEY
