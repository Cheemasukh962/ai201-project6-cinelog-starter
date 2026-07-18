"""
tests/test_watchlist.py — CineLog

Tests for the watchlist service. Structured to mirror tests/test_collection.py
so the two suites stay readable side by side.
"""

import pytest
from app import create_app, db
from models import User, Film, WatchlistEntry
from services.watchlist_service import (
    add_to_watchlist,
    get_watchlist,
    AlreadyInWatchlistError,
)
from services.collection_service import FilmNotFoundError


@pytest.fixture
def app():
    """Create an isolated test app with an in-memory database."""
    app = create_app(config={
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
    })
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def sample_user(app):
    """A user to use in tests."""
    with app.app_context():
        user = User(username="testuser", email="test@example.com")
        db.session.add(user)
        db.session.commit()
        return user.id


@pytest.fixture
def sample_film(app):
    """A film to use in tests."""
    with app.app_context():
        film = Film(title="Paddington 2", year=2017, genre="Comedy")
        db.session.add(film)
        db.session.commit()
        return film.id


# ── Basic add ───────────────────────────────────────────────────────────────

def test_add_to_watchlist_creates_entry(app, sample_user, sample_film):
    """
    Adding a valid film should create a WatchlistEntry in the database.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)

        assert entry is not None
        assert entry.user_id == sample_user
        assert entry.film_id == sample_film

        # Verify it persisted
        in_db = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).first()
        assert in_db is not None


# ── Deduplication (Comment 2) ────────────────────────────────────────────────

def test_add_to_watchlist_duplicate_raises(app, sample_user, sample_film):
    """
    Adding the same film twice should raise AlreadyInWatchlistError,
    not silently create a duplicate entry.

    Mirrors test_add_to_collection_duplicate_raises.
    """
    with app.app_context():
        add_to_watchlist(user_id=sample_user, film_id=sample_film)

        with pytest.raises(AlreadyInWatchlistError):
            add_to_watchlist(user_id=sample_user, film_id=sample_film)

        # Confirm only one entry exists
        count = WatchlistEntry.query.filter_by(
            user_id=sample_user, film_id=sample_film
        ).count()
        assert count == 1


# ── Nonexistent film (Comment 3) ─────────────────────────────────────────────

def test_add_to_watchlist_nonexistent_film_raises(app, sample_user):
    """
    Adding a film_id that doesn't exist in the database should raise
    FilmNotFoundError, not a database integrity error.

    Mirrors test_add_to_collection_nonexistent_film_raises.
    """
    with app.app_context():
        # NOTE: film IDs are integers on this branch (pre-UUID-refactor).
        # After rebasing onto main this becomes a UUID string, matching
        # test_collection.py.
        nonexistent_film_id = 999999

        with pytest.raises(FilmNotFoundError):
            add_to_watchlist(user_id=sample_user, film_id=nonexistent_film_id)


# ── Visibility default (Comment 4) ───────────────────────────────────────────

def test_add_to_watchlist_defaults_to_private(app, sample_user, sample_film):
    """
    New watchlist entries should be private until the user opts in to sharing.
    """
    with app.app_context():
        entry = add_to_watchlist(user_id=sample_user, film_id=sample_film)
        assert entry.public is False


# ── Sort order (Comment 5) ───────────────────────────────────────────────────

def test_get_watchlist_returns_newest_first_by_default(app, sample_user):
    """
    get_watchlist() defaults to date_added descending, matching get_collection().
    """
    with app.app_context():
        from datetime import datetime, timezone, timedelta

        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_b = Film(title="Blade Runner", year=1982, genre="Sci-Fi")
        db.session.add_all([film_a, film_b])
        db.session.commit()

        earlier = datetime.now(timezone.utc) - timedelta(days=5)
        later = datetime.now(timezone.utc)

        # Blade Runner sorts second alphabetically but was added later, so a
        # date_added sort must put it first. This ordering deliberately differs
        # from the alphabetical one, so the test fails if the sort regresses.
        db.session.add_all([
            WatchlistEntry(user_id=sample_user, film_id=film_a.id, date_added=earlier),
            WatchlistEntry(user_id=sample_user, film_id=film_b.id, date_added=later),
        ])
        db.session.commit()

        titles = [f["title"] for f in get_watchlist(sample_user)]
        assert titles == ["Blade Runner", "Alien"]


def test_get_watchlist_supports_title_sort(app, sample_user):
    """
    Passing sort="title" returns the watchlist A–Z regardless of date added.
    """
    with app.app_context():
        from datetime import datetime, timezone, timedelta

        film_a = Film(title="Alien", year=1979, genre="Horror")
        film_b = Film(title="Blade Runner", year=1982, genre="Sci-Fi")
        db.session.add_all([film_a, film_b])
        db.session.commit()

        earlier = datetime.now(timezone.utc) - timedelta(days=5)
        later = datetime.now(timezone.utc)

        db.session.add_all([
            WatchlistEntry(user_id=sample_user, film_id=film_a.id, date_added=earlier),
            WatchlistEntry(user_id=sample_user, film_id=film_b.id, date_added=later),
        ])
        db.session.commit()

        titles = [f["title"] for f in get_watchlist(sample_user, sort="title")]
        assert titles == ["Alien", "Blade Runner"]
