"""Two identifiers that are easy to confuse and expensive to get wrong.

Both of these were live bugs. Neither raised an error: one silently disabled a
safety rule, the other would have sent an accept to a URL built from the wrong
id — on an offer the agent was actively recommending.
"""

from __future__ import annotations

from fantasy.domain.models import Team
from fantasy.sources.sync import _apply_scoring_status, _market_ids


class TestMarketIdsAreNotPlayerIds:
    """An offer is accepted against the market id, not the player's.

    The listing is the only place that links them, so it is resolved there.
    Passing the player's id through as a market id built a valid-looking URL
    pointing at nothing.
    """

    def test_resolves_the_listing_id_for_a_player(self):
        raw = [{"id": "24142735", "playerTeam": {"playerTeamId": "34189656"}}]
        assert _market_ids(raw) == {"34189656": "24142735"}

    def test_a_listing_without_either_id_is_skipped(self):
        raw = [{"id": "1"}, {"playerTeam": {"playerTeamId": "2"}}, {}]
        assert _market_ids(raw) == {}

    def test_an_unexpected_payload_yields_nothing(self):
        assert _market_ids(None) == {}
        assert _market_ids({"error": "nope"}) == {}


class TestScoringStatus:
    """`can_punctuate` is the game's own verdict and has to be read, not assumed.

    It defaulted to True and nothing ever set it, so the warning that a squad
    in the red scores nothing all week could never fire.
    """

    def test_it_marks_only_our_own_team(self):
        teams = [Team(id="mine", manager="iker"), Team(id="theirs", manager="rival")]
        updated = _apply_scoring_status(teams, "mine", False)
        assert updated[0].can_punctuate is False
        assert updated[1].can_punctuate is True

    def test_it_can_restore_a_team_that_is_solvent_again(self):
        teams = [Team(id="mine", manager="iker", can_punctuate=False)]
        assert _apply_scoring_status(teams, "mine", True)[0].can_punctuate is True
