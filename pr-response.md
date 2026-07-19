# PR Response Doc — CineLog Watchlist Feature

## AI Usage

I used Claude Code throughout this project. Specifically:

**Orientation (Milestone 1).** Before reading the review comments I had the AI
summarize `models.py`, `services/collection_service.py`, and
`tests/test_collection.py` — what each file owns, what depends on what. The
useful output was the observation that `CollectionEntry` is the reference
implementation for `WatchlistEntry`: same entry-table shape, same
exception-per-failure-mode pattern, same three-fixture test structure. That
framing is what made the review comments legible — Comment 1 and Comment 2 are
both really "make watchlist look like collection."

**Verification, not just generation.** Two things the AI got wrong that I caught
by checking against the code:

- Its first version of the sort-order test set up the fixture data so that the
  date-added ordering and the alphabetical ordering were *the same list*. The
  test passed, but it would also have passed with the sort bug still present. I
  had it flip the dates so the two orderings genuinely differ.
- It initially bundled the visibility test into the sort-order commit, which
  violates CONTRIBUTING.md's one-logical-change rule. Split into two commits.

**Diagnosing local setup.** `feature/watchlist` was missing locally because the
repo had been created with `git init` + `git pull <url>`, which fetches only the
remote HEAD branch and records no remote. Fixed with `git remote add` +
`git fetch`.

**Stress-testing Comments 4 and 5.** After drafting both positions I asked: "what
counterargument would a careful reviewer raise, and what tradeoff am I not
acknowledging?" For Comment 4 it surfaced the discovery-cost argument — that
defaults dominate behavior, so a private default means public watchlists are
effectively ~0% at launch and any social feature built on them launches empty.
I had framed privacy as costless; it isn't. My final answer keeps the private
default but now names that cost explicitly and proposes making the opt-in cheap
and visible rather than pretending the tradeoff doesn't exist. For Comment 5 it
raised YAGNI against the `?sort=` parameter, which I'd already accounted for —
the branch already shipped alphabetical, so the parameter preserves existing
behavior rather than inventing new surface.

---

## Comment 1 — Rename

**What I did:**
Renamed `save_to_watchlist()` to `add_to_watchlist()` in
`services/watchlist_service.py` so the watchlist service matches the project's
`verb_to_noun` convention and, specifically, the verb already used by its twin
`add_to_collection()`. Updated the one call site in
`routes/watchlist/watchlist.py` (both the import and the call).

**How I verified:**
Ran a project-wide search for the old name before editing to enumerate every
call site, then re-ran it afterwards to confirm zero remained:

```bash
grep -rn "save_to_watchlist" . --include="*.py"   # empty after the change
grep -rn "add_to_watchlist" . --include="*.py"    # def + import + call
```

Full suite passed after the rename.

---

## Comment 2 — Deduplication

**What I did:**
Mirrored `add_to_collection()`'s three-layer approach, because a duplicate
watchlist entry is the same class of problem as a duplicate collection entry and
should fail the same way:

1. **`AlreadyInWatchlistError`** in `services/watchlist_service.py`, following
   collection's convention of a named exception per failure mode rather than a
   generic `ValueError`.
2. **An existence check in `add_to_watchlist()`**, placed after the
   film-exists check and before `db.session.add()` — same ordering as
   `add_to_collection()`, so a request for a nonexistent film reports "film not
   found" rather than "already on your watchlist."
3. **A `UniqueConstraint("user_id", "film_id")` on `WatchlistEntry`** in
   `models.py`, mirroring `CollectionEntry`'s.

Why both the Python check and the database constraint: the Python check produces
a clean 409 for the normal case, and the constraint is the backstop for two
concurrent requests that both pass the check before either commits. Collection
has both; dropping either one would make watchlist weaker than the thing it's
modelled on.

I also fixed the route. `routes/watchlist/watchlist.py` had a bare
`except Exception` returning 400 for everything, so the new exception would have
been invisible to API callers — every failure looked identical. It now maps
`FilmNotFoundError` → 404 and `AlreadyInWatchlistError` → 409, matching
`routes/collection.py`. This is a separate commit from the service change.

**How I verified:**
Unit test (`test_add_to_watchlist_duplicate_raises`) asserts the exception is
raised *and* that only one row exists afterwards — the count assertion is the
part that actually proves deduplication, since an exception alone wouldn't tell
you whether a row got written first.

Then end to end against a running server:

```
POST /watchlist/<user>/add  {"film_id": "<zodiac-uuid>"}   => 201
POST /watchlist/<user>/add  {"film_id": "<zodiac-uuid>"}   => 409
  {"error":"Film '<uuid>' is already on this user's watchlist"}
POST /watchlist/<user>/add  {"film_id": "0000...0000"}     => 404
  {"error":"No film found with id '0000...0000'"}
```

---

## Comment 3 — Missing test

**What I did:**
Created `tests/test_watchlist.py`, modelled directly on
`tests/test_collection.py`. It reuses the same three-fixture structure (`app`
with an in-memory SQLite database, `sample_user`, `sample_film`) and the same
assertion style. `test_add_to_watchlist_nonexistent_film_raises` is the direct
counterpart of `test_add_to_collection_nonexistent_film_raises` — same
nonexistent-UUID input, same `pytest.raises(FilmNotFoundError)` assertion.

CONTRIBUTING.md requires three tests per new service function (happy path,
duplicate/conflict, nonexistent ID), so the file also covers the happy path and
the duplicate case, plus the visibility and sort-order behavior from Comments 4
and 5. Six tests total.

One detail worth noting: the fixtures return `film.id` and `user.id` rather than
the model objects. That is deliberate and copied from the existing suite — the
objects become detached once the `app_context` block exits, so returning plain
IDs avoids `DetachedInstanceError`.

**How I verified:**
```bash
pytest tests/test_watchlist.py -v   # 6 passed
pytest tests/ -v                    # 10 passed — no regressions
```

---

## Comment 4 — Default visibility

**My position:**
Watchlists should default to **private**. I changed
`public = db.Column(db.Boolean, default=True)` to `default=False`.

**Reasoning:**
A collection and a watchlist look structurally identical but carry very
different information, and CineLog already treats the collection as the public
artifact. A collection entry is a *judgment* — I watched this, here's my rating.
That's the thing a user is choosing to say publicly, and it's what makes their
profile worth following. A watchlist entry is an *intention*, and intentions
leak things judgments don't:

- **Absence is information.** A public watchlist broadcasts what a user hasn't
  seen. On a film community where taste is social currency, "still hasn't
  watched Chinatown" is a thing people are self-conscious about, and it's
  revealed passively by a feature whose purpose was just to remember things.
- **The act of adding is low-deliberation.** Users add films in bulk while
  browsing — five taps in thirty seconds. Publishing should require deliberation
  proportional to its consequences, and a tap during a browsing spree isn't that.
  A rating, by contrast, is deliberate by nature.
- **The reversal is asymmetric.** Flipping a private list to public later costs
  the user nothing. Flipping a public list to private doesn't un-see what was
  already seen, cached, or screenshotted. When the two error directions cost
  different amounts, default to the recoverable one.

**Tradeoff acknowledged:**
This has a real cost and it isn't small. Watchlists are excellent discovery
fuel — seeing what a friend is planning to watch is one of the better reasons to
follow someone on a film site, and it's more forward-looking than their ratings
history. Defaults dominate behavior: most users never change them, so a private
default means the population of public watchlists will be a small single-digit
percentage rather than most of them. Any future feature that depends on
aggregate watchlist data — a "trending on watchlists" row, friend-activity
feed — launches nearly empty and looks broken, and that's much harder to fix
later than it would have been to ship public from day one.

I'm accepting that cost, but it should be mitigated rather than ignored: make
sharing a visible, one-tap action on the list view, and consider prompting once
after a user's first several adds ("share your watchlist?"). That gets most of
the discovery value from users who actually want to share, without harvesting
consent by default from users who never thought about it.

---

## Comment 5 — Sort order

**My position:**
I implemented the maintainer's preference — `get_watchlist()` now defaults to
`date_added` descending, matching `get_collection()` — but kept alphabetical
available as an explicit `?sort=title` option rather than deleting it.

**Engagement with reviewer's point:**
The maintainer's argument is that watchlist should sort newest-first like
collection does, and that alphabetical buries what the user just added. I think
that's right, and the reason it's right is worth stating precisely: it's not
really about consistency with `get_collection()` for its own sake, it's that
both endpoints answer the same question. The dominant interaction right after a
write is *"did the thing I just added land?"* — and under alphabetical sort, a
film the user just added surfaces at an unpredictable position in the list, or
below the fold entirely on a long one. Recency answers that question directly.
Consistency with collection is a real but secondary benefit; if the interaction
pattern had been different, matching collection wouldn't have been reason enough.

**Reasoning:**
Where I'd push back slightly is on deleting alphabetical outright. It serves a
genuine second job: on a watchlist of 200 films, "do I already have this saved?"
is a lookup, and a stable alphabetical ordering is the right shape for scanning
for a known title — a recency ordering is effectively random for that purpose.
So the fix is a default change, not a removal. Two lines of branching in the
service and one query parameter on the route, covered by two tests.

I deliberately did *not* invent a third default. The strongest case against
recency is "I want to pick something to watch tonight," where neither date nor
title helps — but that's a filtering problem (runtime, genre, streaming
availability), not a sorting one, and inventing a clever default sort would be
the wrong place to solve it. Recency as the default, title as an escape hatch,
filtering later when there's a reason to build it.

---

## Comment 6 — Rebase

**What conflicted:**
Two conflicts while running `git rebase origin/main`:

1. **`.gitignore` (add/add).** Main had added its own `.gitignore` in
   `chore: add .gitignore for generated files` while my branch added one too.
2. **`models.py` (content).** The real one. Main's
   `refactor: migrate film IDs from integer to UUID` changed `Film.id` from
   `db.Integer` to `db.String(36)` and updated `CollectionEntry.film_id` to
   match — and, because `WatchlistEntry` didn't exist on main, the refactor
   never touched it. My branch's `WatchlistEntry.film_id` was still
   `db.Integer` pointing at a foreign key that is now a UUID string.

**How I resolved it:**
For `.gitignore`: main's version was a strict superset of mine, so my commit
added nothing. I dropped it with `git rebase --skip` rather than keeping a
no-op commit in the history.

For `models.py`: this was not a one-side-wins resolution. I took main's UUID
column types and kept my branch's `WatchlistEntry` additions —
`WatchlistEntry.film_id` became `db.String(36)`, and the `UniqueConstraint` and
`Film.watchlist_entries` relationship from my branch were preserved.

The important part was the leftovers git *couldn't* flag. The conflict markers
only covered `models.py`, but three other places still assumed integer IDs and
would have merged silently:

- `services/watchlist_service.py` — docstring `film_id (int): ... pre-refactor`
- `routes/watchlist/watchlist.py` — `Body: { "film_id": <int> }`
- `tests/test_watchlist.py` — `nonexistent_film_id = 999999`

The test one is the instructive case: it kept passing after the rebase, because
`db.session.get()` on a string primary key returns `None` for an integer just as
it does for a bogus UUID. Green tests were not evidence the migration was
complete. All three are fixed in
`fix: update watchlist film_id references to UUID after main refactor`.

**How I verified no conflict remains:**
```bash
grep -n "db.Integer" models.py
# only legitimate hits remain: Film.year and CollectionEntry.rating

git log --merges origin/main..HEAD
# prints nothing — linear history, no merge commits

pytest tests/ -v          # 10 passed
```

Plus the end-to-end run below, which exercises real UUIDs through the HTTP layer
rather than trusting the unit tests alone.

---

## Additional fix (not requested in review)

While verifying the feature end to end I found that `GET /watchlist/<user_id>`
raised `AttributeError: 'WatchlistEntry' object has no attribute 'film'` for any
non-empty watchlist. `get_watchlist()` calls `entry.film.to_dict()`, but `Film`
only declared a relationship to `CollectionEntry` — there was no watchlist
equivalent, so the backref never existed.

Added `watchlist_entries = db.relationship("WatchlistEntry", backref="film",
lazy=True)` to the `Film` model, mirroring the existing `collection_entries`
line. Kept as its own commit so it can be reviewed — or dropped — independently
of the six requested changes.

---

## Git History

```
892bd32 docs: document design decisions and rebase in pr-response
dce6549 fix: update watchlist film_id references to UUID after main refactor
f44b417 feat: sort watchlist newest-first with opt-in title sort
1b4217e feat: default watchlist entries to private
7499ff9 test: add duplicate entry test for add_to_watchlist
c315cab fix: map watchlist errors to 404 and 409 responses
0bcc207 fix: add deduplication check to prevent duplicate watchlist entries
f0a4cb1 docs: add pr-response.md documenting review responses
d26980e test: add tests for add_to_watchlist happy path and nonexistent film
803589a fix: add Film to WatchlistEntry relationship so get_watchlist can load films
e2391b7 fix: rename save_to_watchlist to add_to_watchlist per naming convention
a9c740f fix: update film retrieval method to use db.session.get in collection and watchlist services
e2fb782 feat: add watchlist model and add_to_watchlist endpoint
```

<!-- TODO: replace the block above with the screenshot of `git log --oneline`. -->

Cleanup done during `git rebase -i origin/main`:

- Reworded the branch's first commit from
  `added watchlist model and endpoint fixed a bug more changes` — which was both
  non-conventional and three changes announced in one message — to
  `feat: add watchlist model and add_to_watchlist endpoint`.
- Dropped the redundant `.gitignore` commit during the rebase.
- Split the visibility change and the sort-order change, which had initially
  been committed together, into one commit each.

Thirteen commits, all conventional, no merge commits.

---

## PR Description

### What this does

Adds a watchlist to CineLog: a per-user list of films they intend to watch,
sitting alongside the existing collection (films they've already watched and
rated). Two endpoints — `POST /watchlist/<user_id>/add` to save a film and
`GET /watchlist/<user_id>` to read the list back. Adding a film twice is
rejected rather than silently duplicated, and adding a film that doesn't exist
returns a 404 instead of a database error.

### Design decisions

**1. Watchlist entries default to private (`public=False`).** A collection entry
is a judgment a user chose to publish; a watchlist entry is an intention, and a
public watchlist also broadcasts what someone *hasn't* seen. Adding films is a
low-deliberation, bulk action, and un-publishing doesn't un-see. The cost is
real — watchlists are strong discovery fuel and defaults dominate, so public
watchlists will be rare — which argues for making sharing a visible one-tap
action rather than the silent default. Full reasoning in `pr-response.md`.

**2. `GET /watchlist/<user_id>` sorts newest-first by default, with opt-in
`?sort=title`.** This adopts the maintainer's date-added preference: the
dominant interaction after a write is "did what I just added land?", which
recency answers and alphabetical doesn't. Alphabetical is kept as an explicit
option because scanning a long list for a known title is a real second use case.

### How to test manually

```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash
pip install -r requirements.txt
pytest tests/ -v                 # 10 passed
```

Create a user and two films, then start the server:

```bash
python -c "
from app import create_app, db
from models import User, Film
app = create_app()
with app.app_context():
    u = User(username='demo', email='demo@example.com')
    f1, f2 = Film(title='Zodiac', year=2007), Film(title='Arrival', year=2016)
    db.session.add_all([u, f1, f2]); db.session.commit()
    print('USER', u.id); print('ZODIAC', f1.id); print('ARRIVAL', f2.id)
"
python app.py     # http://127.0.0.1:5000
```

> Note: on some setups `python app.py` loads the module twice (as `__main__` and
> as `app`), creating two SQLAlchemy instances and 500ing every DB request. This
> is pre-existing starter behavior and affects the collection endpoints
> identically. If you hit it, run
> `python -c "from app import create_app; create_app().run(port=5000)"` instead.

Substitute the printed UUIDs:

| Step | Request | Expected |
|---|---|---|
| 1 | `POST /watchlist/$USER/add` body `{"film_id":"$ZODIAC"}` | `201`, entry JSON with `"public": false` |
| 2 | `POST /watchlist/$USER/add` body `{"film_id":"$ARRIVAL"}` | `201` |
| 3 | Repeat step 1 | `409` — `"already on this user's watchlist"` |
| 4 | `POST /watchlist/$USER/add` body `{"film_id":"00000000-0000-0000-0000-000000000000"}` | `404` — `"No film found with id ..."` |
| 5 | `GET /watchlist/$USER` | `["Arrival", "Zodiac"]` — newest added first |
| 6 | `GET /watchlist/$USER?sort=title` | `["Arrival", "Zodiac"]` — A–Z |
| 7 | `POST /watchlist/$USER/add` body `{}` | `400` — `"film_id is required"` |

```bash
curl -X POST http://127.0.0.1:5000/watchlist/$USER/add \
     -H "Content-Type: application/json" \
     -d "{\"film_id\":\"$ZODIAC\"}"

curl "http://127.0.0.1:5000/watchlist/$USER"
curl "http://127.0.0.1:5000/watchlist/$USER?sort=title"
```

Steps 1–6 were run against a live server on the final rebased branch. Step 7
exercises the pre-existing `film_id is required` guard, which this PR did not
change.
