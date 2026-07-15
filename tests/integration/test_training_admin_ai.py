from app.chess.models import ChessCourse, ChessGame, ChessPuzzle
from app.extensions import db
from app.german.models import GermanResource, VocabularyItem
from tests.conftest import csrf_from


def seed_training(app) -> dict[str, str]:
    with app.app_context():
        game = ChessGame(
            external_id="game-1",
            source="lichess",
            white="Walid",
            black="Opponent",
            user_result="win",
            opening={"name": "Italian Game", "eco": "C50"},
        )
        puzzle = ChessPuzzle(
            external_id="puzzle-ui", fen="8/8/8/8/8/8/8/8 w - - 0 1", rating=1500
        )
        course = ChessCourse(title="Italian structures", progress_percent=20)
        resource = GermanResource(title="Deutsch A1", kind="course", progress_percent=10)
        word = VocabularyItem(term="lernen", meaning="to learn")
        db.session.add_all([game, puzzle, course, resource, word])
        db.session.commit()
        return {
            "game": game.id,
            "puzzle": puzzle.id,
            "resource": resource.id,
            "word": word.id,
        }


def test_training_pages_and_ai_disabled_state(authenticated_client, app):
    ids = seed_training(app)
    pages = {
        "/chess": "Italian structures",
        f"/chess/games/{ids['game']}": "Italian Game",
        f"/chess/puzzles/{ids['puzzle']}": "puzzle-ui",
        "/german": "Deutsch A1",
        "/ai/workspace?mode=film_analysis&context_type=movie&context_id=mov_1": "safely disabled",
        "/admin": "Control Center",
    }
    for path, expected in pages.items():
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert expected in response.get_data(as_text=True)


def test_admin_operation_requires_csrf_and_reports_disabled_sync(authenticated_client):
    assert authenticated_client.post(
        "/admin/run", data={"kind": "refresh", "domain": "movies"}
    ).status_code == 400
    page = authenticated_client.get("/admin")
    response = authenticated_client.post(
        "/admin/run",
        data={
            "csrf_token": csrf_from(page),
            "kind": "refresh",
            "domain": "movies",
        },
        follow_redirects=True,
    )
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "completed with warnings" in html
    assert "External synchronization is disabled" in html


def test_unknown_ai_context_is_not_found(authenticated_client):
    assert authenticated_client.get(
        "/ai/workspace?mode=unknown&context_type=none"
    ).status_code == 404
