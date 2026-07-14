import pytest

from app.chess.models import ChessPuzzle
from app.chess.services import ChessService
from app.extensions import db
from app.german.models import GermanResource, VocabularyItem
from app.german.services import GermanService
from app.history.models import HistoryEvent


def test_chess_attempt_tracks_review_and_history(app):
    with app.app_context():
        puzzle = ChessPuzzle(
            external_id="puzzle-1", fen="8/8/8/8/8/8/8/8 w - - 0 1", rating=1400
        )
        db.session.add(puzzle)
        db.session.commit()
        attempt = ChessService.complete_puzzle(
            puzzle, wrong_count=1, reveal_used=False, skipped=False
        )
        assert attempt.needs_repeat is True
        assert attempt.completed_clean is False
        event = db.session.scalar(db.select(HistoryEvent))
        assert event.domain == "chess"
        assert event.entity_id == puzzle.id


def test_german_progress_and_review_are_validated(app):
    with app.app_context():
        resource = GermanResource(title="A1 Course", kind="course")
        word = VocabularyItem(term="ruhig", meaning="calm")
        db.session.add_all([resource, word])
        db.session.commit()
        GermanService.save_progress(resource, 100)
        GermanService.review_word(word)
        assert resource.completed is True
        assert word.review_count == 1
        assert db.session.scalar(db.select(db.func.count()).select_from(HistoryEvent)) == 2
        with pytest.raises(ValueError):
            GermanService.save_progress(resource, 101)
