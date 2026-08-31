from __future__ import annotations

from sqlalchemy import func, select

from app.auth.models import PersonalWorkspace, User
from app.extensions import db
from app.movies.models import Movie, MovieCustomList
from app.vault.runtime import bind_workspace, runtime_for


def _workspace(app, *, username: str, workspace_id: str) -> PersonalWorkspace:
    with app.app_context():
        user = User(username=username, password_hash=workspace_id)
        db.session.add(user)
        db.session.flush()
        workspace = PersonalWorkspace(
            id=workspace_id,
            owner_user_id=user.id,
            remote_locator=f"drive-{workspace_id}",
            state="ready",
        )
        db.session.add(workspace)
        db.session.commit()
        return db.session.get(PersonalWorkspace, workspace_id)


def _add_movie_in_workspace(app, workspace: PersonalWorkspace) -> None:
    with app.test_request_context("/"):
        bind_workspace(workspace)
        movie = Movie(title=f"Movie for {workspace.id}", normalized_title=workspace.id)
        db.session.add(movie)
        db.session.flush()
        db.session.add(
            MovieCustomList(
                owner_user_id=workspace.owner_user_id,
                title="Watch later",
            )
        )
        db.session.commit()
        db.session.remove()


def test_google_workspace_runtime_routes_content_to_isolated_sqlite_caches(app):
    first = _workspace(app, username="first-google-user", workspace_id="workspace_first")
    second = _workspace(app, username="second-google-user", workspace_id="workspace_second")

    _add_movie_in_workspace(app, first)
    _add_movie_in_workspace(app, second)

    with app.app_context():
        # The central authentication database did not receive personal content.
        assert db.session.scalar(select(func.count()).select_from(Movie)) == 0

        runtime = runtime_for(app)
        first_engine = runtime.engine_for(
            bind_workspace_for_test(first, app)
        )
        second_engine = runtime.engine_for(
            bind_workspace_for_test(second, app)
        )
        with first_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Movie.__table__)) == 1
            assert (
                connection.scalar(select(func.count()).select_from(MovieCustomList.__table__))
                == 1
            )
        with second_engine.connect() as connection:
            assert connection.scalar(select(func.count()).select_from(Movie.__table__)) == 1
            assert (
                connection.scalar(select(func.count()).select_from(MovieCustomList.__table__))
                == 1
            )


def bind_workspace_for_test(workspace: PersonalWorkspace, app):
    return runtime_for(app).bind(workspace)
