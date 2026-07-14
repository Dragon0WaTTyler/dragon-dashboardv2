from app.chess.models import ChessGame, ChessPuzzle
from app.extensions import db
from app.german.models import GermanResource


def seed_training_api(app) -> dict[str, str]:
    with app.app_context():
        game = ChessGame(
            external_id="api-game",
            source="chess.com",
            white="A",
            black="B",
            user_result="draw",
        )
        puzzle = ChessPuzzle(
            external_id="api-puzzle", fen="8/8/8/8/8/8/8/8 w - - 0 1", rating=1200
        )
        resource = GermanResource(title="API German", kind="playlist")
        db.session.add_all([game, puzzle, resource])
        db.session.commit()
        return {"game": game.id, "puzzle": puzzle.id}


def test_chess_and_german_api_contracts(authenticated_client, app):
    ids = seed_training_api(app)
    chess = authenticated_client.get("/api/v1/chess").get_json()
    assert chess["ok"] is True
    assert chess["item"]["recent_games"][0]["id"] == ids["game"]
    games = authenticated_client.get("/api/v1/chess/games").get_json()
    puzzles = authenticated_client.get("/api/v1/chess/puzzles").get_json()
    assert games["items"][0]["external_id"] == "api-game"
    assert puzzles["items"][0]["external_id"] == "api-puzzle"
    german = authenticated_client.get("/api/v1/german").get_json()
    assert german["item"]["resources"][0]["title"] == "API German"


def test_history_api_contract_after_progress(authenticated_client, app):
    ids = seed_training_api(app)
    with app.app_context():
        puzzle = db.session.get(ChessPuzzle, ids["puzzle"])
        from app.chess.services import ChessService

        ChessService.complete_puzzle(puzzle, wrong_count=0, reveal_used=False, skipped=False)
    payload = authenticated_client.get("/api/v1/history?domain=chess").get_json()
    assert payload["count"] == 1
    assert payload["items"][0]["event_type"] == "puzzle_attempt"
