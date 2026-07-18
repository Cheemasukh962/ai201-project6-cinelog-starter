# PR Response Doc — CineLog Watchlist Feature

## AI Usage
<!-- TODO (fill in at the end).
Things you can honestly document so far:
  - Diagnosing why `feature/watchlist` was missing locally (the repo had been
    created with `git init` + `git pull <url>`, which fetches only the remote
    HEAD branch and saves no remote; fixed with `git remote add` + `git fetch`).
  - Codebase orientation: summarizing the routes/services/models layering and
    identifying that CollectionEntry is the reference implementation for
    WatchlistEntry.
  - Mechanical work: the rename in Comment 1, test scaffolding, commit-format
    checking.
  - Whatever you ask when stress-testing your Comment 4 / Comment 5 drafts —
    record what you asked and what you changed as a result.
-->

## Comment 1 — Rename
**What I did:**
Renamed `save_to_watchlist()` to `add_to_watchlist()` in
`services/watchlist_service.py` so the watchlist service matches the project's
`verb_to_noun` convention and, specifically, the verb already used by its twin
`add_to_collection()`. Updated the one call site in
`routes/watchlist/watchlist.py` (both the import on line 8 and the call on
line 32).

**How I verified:**
Ran a project-wide search for the old name before editing to enumerate every
call site, then re-ran it afterwards to confirm zero remained:

```bash
grep -rn "save_to_watchlist" . --include="*.py"   # empty after the change
grep -rn "add_to_watchlist" . --include="*.py"    # 3 hits: def + import + call
```

Full suite passed (`pytest tests/ -v`, 4 passed) after the rename.

## Comment 2 — Deduplication
**What I did:**
<!-- TODO — this one is yours to write. See the notes below, then delete them.

Three pieces to mirror from add_to_collection() in
services/collection_service.py:

  1. An `AlreadyInWatchlistError` exception class at the top of
     services/watchlist_service.py. Collection defines its own exception
     classes at collection_service.py lines 12-24 — follow that.
  2. The existence check inside add_to_watchlist(), placed AFTER the
     film-exists check but BEFORE db.session.add(). See
     collection_service.py lines 47-53 for the query + raise shape.
  3. A __table_args__ UniqueConstraint on WatchlistEntry in models.py, mirroring
     CollectionEntry's at models.py lines 60-62.

Why all three: the Python check produces a clean 409 response; the database
constraint is the backstop for concurrent requests that both pass the check
before either commits. Collection has both, so watchlist should too.

Also worth doing while you are here: routes/watchlist/watchlist.py currently
calls the service with no try/except, so exceptions escape as HTTP 500. Compare
routes/collection.py lines 42-52, which maps FilmNotFoundError to 404 and
AlreadyInCollectionError to 409. Your new AlreadyInWatchlistError needs the
same treatment or the dedup fix will not be visible to API callers.

Then add the duplicate test to tests/test_watchlist.py, modelled on
test_add_to_collection_duplicate_raises (test_collection.py lines 78-93).
-->

**How I verified:**
<!-- TODO -->

## Comment 3 — Missing test
**What I did:**
Created `tests/test_watchlist.py`, modelled directly on
`tests/test_collection.py`. It reuses the same three-fixture structure (`app`
with an in-memory SQLite database, `sample_user`, `sample_film`) and the same
assertion style. Two tests so far:

- `test_add_to_watchlist_creates_entry` — happy path; asserts the returned
  entry's fields and then re-queries the database to confirm it persisted.
- `test_add_to_watchlist_nonexistent_film_raises` — the test the reviewer asked
  for, mirroring `test_add_to_collection_nonexistent_film_raises`. Asserts
  `FilmNotFoundError` is raised rather than the request falling through to a
  database integrity error.

The duplicate/conflict test required by CONTRIBUTING.md is added alongside the
Comment 2 deduplication work, since it asserts on the exception that change
introduces.

One detail worth noting: the fixtures return `film.id` and `user.id` rather than
the model objects themselves. That is deliberate and copied from the existing
suite — the objects become detached once the `app_context` block exits, so
returning plain IDs avoids `DetachedInstanceError`.

**How I verified:**
```bash
pytest tests/test_watchlist.py -v   # 2 passed
pytest tests/ -v                    # 6 passed — no regressions
```

## Comment 4 — Default visibility
**My position:**
<!-- TODO — yours. This is about `public = db.Column(db.Boolean, default=True)`
at models.py line 80. Take a clear position on whether watchlists should default
to public or private. -->

**Reasoning:**
<!-- TODO — ground it in CineLog specifically: what is a watchlist *for* on a
community film-tracking app, and what does a user reasonably expect when they
save something they have not watched yet? -->

**Tradeoff acknowledged:**
<!-- TODO — name what your choice costs, not just what it buys. -->

## Comment 5 — Sort order
**My position:**
<!-- TODO — yours. `get_watchlist()` sorts `Film.title.asc()`
(watchlist_service.py line 50); `get_collection()` sorts `date_added.desc()`
(collection_service.py line 102). You may implement the maintainer's
date-added preference, keep alphabetical, or propose a third option. -->

**Reasoning:**
<!-- TODO -->

**Engagement with reviewer's point:**
<!-- TODO — quote or paraphrase the maintainer's actual argument and answer it
directly. Stating a preference without engaging their reasoning is what loses
credit here. -->

## Comment 6 — Rebase
**What conflicted:**
<!-- TODO — fill in after the rebase. Expected: models.py, where this branch
still has `Film.id = db.Column(db.Integer, ...)` while main migrated film IDs
to UUID strings in commit 07ca580. -->

**How I resolved it:**
<!-- TODO — the resolution rule is: take main's UUID column types, keep this
branch's WatchlistEntry additions. It is not a one-side-wins resolution.

Do not forget the non-conflicting leftovers that git will not flag:
  - watchlist_service.py line 18 docstring: "film_id (int): ... (pre-refactor)"
  - routes/watchlist/watchlist.py docstring: Body: { "film_id": <int> }
  - tests/test_watchlist.py: nonexistent_film_id = 999999 becomes a UUID string
-->

**How I verified no conflict remains:**
<!-- TODO — suggested evidence:
  grep -rn "db.Integer" models.py
  git log --merges origin/main..HEAD    # must print nothing
  pytest tests/ -v
-->

## Additional fix (not requested in review)
While verifying the feature end to end I found that `GET /watchlist/<user_id>`
raised `AttributeError: 'WatchlistEntry' object has no attribute 'film'` for any
non-empty watchlist. `get_watchlist()` calls `entry.film.to_dict()`, but `Film`
only declared a relationship to `CollectionEntry` — there was no watchlist
equivalent, so the backref never existed.

Added `watchlist_entries = db.relationship("WatchlistEntry", backref="film",
lazy=True)` to the `Film` model, mirroring the existing `collection_entries`
line. Verified by adding a film to a watchlist and calling `get_watchlist()`,
which now returns the film dict with `date_added` and `public` attached.

I kept this as its own commit so it can be reviewed — or dropped — independently
of the six requested changes.

## Git History
<!-- TODO — paste the `git log --oneline` screenshot here after Milestone 4. -->

## PR Description
<!-- TODO — written at the end. Must cover:
  - What the watchlist feature does, in plain language (2-3 sentences)
  - Both design decisions named explicitly (visibility default, sort order)
  - Step-by-step manual testing instructions (curl commands against
    POST /watchlist/<user_id>/add and GET /watchlist/<user_id>)
-->
