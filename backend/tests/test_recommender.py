import pytest

from app.config import Settings
from app.recsys import assistant, llm, state
from app.recsys.content import BookDoc
from app.recsys.engine import RecommendationEngine, Signal
from app.recsys.query import find_candidates, parse

from .conftest import isbn_of


# ----------------------------------------------------------- engine, in isolation
def tiny_engine() -> RecommendationEngine:
    def doc(isbn, title, cats, text, series=None, year=2000):
        return BookDoc(isbn, title, ["Author " + isbn[0]], series, cats, text, year, 300)

    return RecommendationEngine(
        [
            doc(
                "f1",
                "Dragon Rider",
                ["Fantasy", "Dragons"],
                "a girl bonds with a dragon at a war college",
                "Riders",
                2001,
            ),
            doc(
                "f2",
                "Dragon Queen",
                ["Fantasy", "Dragons"],
                "the dragon rider returns to war",
                "Riders",
                2002,
            ),
            doc(
                "f3",
                "Dragon King",
                ["Fantasy", "Dragons"],
                "the final dragon battle",
                "Riders",
                2003,
            ),
            doc("f4", "Elf Song", ["Fantasy", "Magic"], "an elf sings ancient magic in the forest"),
            doc(
                "m1",
                "Body in the Library",
                ["Mystery", "Crime"],
                "a detective investigates a murder in a village",
            ),
            doc(
                "m2",
                "Death on the Train",
                ["Mystery", "Crime"],
                "a detective solves a murder on a train",
            ),
            doc(
                "m3",
                "The Quiet Witness",
                ["Mystery", "Thriller"],
                "a witness to murder goes silent",
            ),
            doc(
                "n1",
                "Deep Work Habits",
                ["Nonfiction", "Self Help"],
                "how to focus and build better habits",
            ),
        ]
    )


def test_content_similarity_groups_like_with_like():
    engine = tiny_engine()
    assert set(engine.similar("m1", limit=2)) == {"m2", "m3"}
    assert engine.similar("f4", limit=1, same_series=False)[0].startswith("f")


def test_new_reader_gets_popular_books_then_favourite_genres():
    engine = tiny_engine()
    engine.set_interactions({1: {"n1": Signal(rating=5)}, 2: {"n1": Signal(rating=5)}})
    assert engine.recommend(user_id=99, limit=1)[0].isbn == "n1"
    picks = engine.recommend(user_id=99, favourite_categories=["Mystery"], limit=3)
    assert picks[0].isbn in {"m1", "m2"}
    assert picks[0].kind == "genres" and "Mystery" in picks[0].reason


def test_history_drives_picks_and_read_books_are_excluded():
    engine = tiny_engine()
    engine.set_interactions({1: {"m1": Signal(rating=5)}})
    picks = engine.recommend(user_id=1, limit=3)
    assert "m1" not in {p.isbn for p in picks}
    assert picks[0].isbn == "m2"
    assert picks[0].reason == "Because you rated Body in the Library 5★"
    assert picks[0].because_isbn == "m1"


def test_series_continuation_comes_first_and_only_once():
    engine = tiny_engine()
    engine.set_interactions({1: {"f1": Signal(rating=4)}})
    picks = engine.recommend(user_id=1, limit=5)
    assert picks[0].isbn == "f2" and picks[0].reason == "Next up in Riders"
    assert "f3" not in {p.isbn for p in picks}  # one book per series in a list


def test_dislikes_push_similar_books_down():
    engine = tiny_engine()
    engine.set_interactions({1: {"m1": Signal(rating=1), "f4": Signal(rating=5)}})
    ranked = [p.isbn for p in engine.recommend(user_id=1, limit=6)]
    assert ranked.index("f1") < ranked.index("m2")


def test_dismissed_books_never_come_back():
    engine = tiny_engine()
    engine.set_interactions({1: {"m1": Signal(rating=5), "m2": Signal(dismissed=True)}})
    assert "m2" not in {p.isbn for p in engine.recommend(user_id=1, limit=8)}


def test_collaborative_signal_links_books_that_share_readers():
    engine = tiny_engine()
    # Three readers love both the dragon book and the habits book: unrelated by content.
    fans = {u: {"f4": Signal(rating=5), "n1": Signal(rating=5)} for u in (1, 2, 3)}
    engine.set_interactions({**fans, 9: {"f4": Signal(rating=5)}})
    ranked = engine.recommend(user_id=9, limit=8)
    picks = {p.isbn: p for p in ranked}
    assert picks["n1"].signals["community"] > 0
    assert all(picks[m].signals["community"] == 0 for m in ("m1", "m2", "m3"))
    order = [p.isbn for p in ranked]
    assert order.index("n1") < min(order.index(m) for m in ("m1", "m2", "m3"))


# ------------------------------------------------------------- against the real data
def test_home_feed_for_demo_reader(demo):
    shelves = demo.get("/api/recommendations/home").json()["shelves"]
    picked = shelves[0]
    assert picked["title"] == "Picked for Demo"
    titles = [b["title"] for b in picked["books"]]
    assert "Crooked Kingdom" in titles  # sequel to Six of Crows, rated 5
    assert not {"Six of Crows", "Dune", "Twilight"} & set(titles)  # already read
    assert all(b["reason"] for b in picked["books"])
    series = [b["series"]["name"] for b in picked["books"] if b["series"]]
    assert len(series) == len(set(series))


def test_feed_reacts_immediately_to_a_new_rating(newcomer):
    before = [b["title"] for b in newcomer.get("/api/recommendations").json()["items"]]
    isbn = isbn_of(newcomer, "The Silent Patient")
    newcomer.put(f"/api/books/{isbn}/review", json={"rating": 5})
    after = newcomer.get("/api/recommendations").json()["items"]
    assert [b["title"] for b in after] != before
    assert any("The Silent Patient" in b["reason"] for b in after[:5])
    assert "Thriller" in after[0]["categories"] or "Mystery" in after[0]["categories"]


def test_not_interested_removes_a_book(demo):
    first = demo.get("/api/recommendations").json()["items"][0]
    assert demo.post(f"/api/books/{first['isbn']}/dismiss").status_code == 204
    again = demo.get("/api/recommendations").json()["items"]
    assert first["isbn"] not in {b["isbn"] for b in again}


def test_logged_out_home_has_shelves(client):
    shelves = client.get("/api/recommendations/home").json()["shelves"]
    assert len(shelves) >= 3 and shelves[0]["title"] == "Popular with readers"


# ----------------------------------------------------------------- the librarian
def test_query_understanding(client, db):
    content = state.get_engine(db).content
    q = parse("something like Dune but shorter", content)
    assert q.like_label == "Dune" and q.max_pages == 320 and not q.lookup
    q = parse("sci-fi classics published after 1950 under 400 pages", content)
    assert q.categories == ["Science Fiction", "Classics"] or set(q.categories) == {
        "Science Fiction",
        "Classics",
    }
    assert q.min_year == 1950 and q.max_pages == 400
    assert parse("anything by Leigh Bardugo", content).author == "Leigh Bardugo"
    assert parse("Harry Potter", content).lookup is True


def test_candidates_respect_constraints(client, db):
    engine = state.get_engine(db)
    _, found = find_candidates(engine, "short classics")
    assert found and all(engine.docs[c.isbn].pages <= 320 for c in found)
    assert all("Classics" in engine.docs[c.isbn].categories for c in found[:5])
    _, found = find_candidates(engine, "something like Six of Crows")
    assert engine.docs[found[0].isbn].title == "Crooked Kingdom"
    assert all(engine.docs[c.isbn].title != "Six of Crows" for c in found)


def test_ask_without_llm(client):
    answer = client.post("/api/assistant/ask", json={"message": "new thrillers"}).json()
    assert answer["mode"] == "builtin" and len(answer["picks"]) == 5
    assert all(p["year"] >= 2018 and "Thriller" in p["categories"] for p in answer["picks"])
    nothing = client.post("/api/assistant/ask", json={"message": "qwzx vbnm"}).json()
    assert nothing["picks"] == [] and "Nothing on the shelves" in nothing["reply"]


LLM_ON = Settings(llm_api_key="test-key")


def test_llm_answer_is_grounded_in_the_shortlist(client, db, monkeypatch):
    engine = state.get_engine(db)
    _, shortlist = find_candidates(engine, "dark academia")
    real = shortlist[1].isbn

    def fake(settings, system, user, max_tokens=900):
        assert "shortlist" in user and "dark academia" in user
        return {
            "reply": "Try these.",
            "picks": [
                {"isbn": "9999999999999", "reason": "A book the library does not own"},
                {"isbn": real, "reason": "Murder among classics students."},
                {"isbn": real, "reason": "Duplicate"},
            ],
        }

    monkeypatch.setattr(llm, "complete_json", fake)
    answer = assistant.ask(engine, LLM_ON, "dark academia")
    assert answer.mode == "llm" and answer.reply == "Try these."
    assert [(p.isbn, p.reason) for p in answer.picks] == [(real, "Murder among classics students.")]


@pytest.mark.parametrize("failure", [llm.LLMError("timeout"), None])
def test_llm_failure_falls_back_to_builtin(client, db, monkeypatch, failure):
    def broken(*args, **kwargs):
        if failure:
            raise failure
        return {"reply": "Sure!", "picks": [{"isbn": "not-in-shortlist"}]}

    monkeypatch.setattr(llm, "complete_json", broken)
    answer = assistant.ask(state.get_engine(db), LLM_ON, "dark academia")
    assert answer.mode == "builtin" and len(answer.picks) >= 1


def test_extract_json_tolerates_code_fences():
    assert llm.extract_json('```json\n{"reply": "hi", "picks": []}\n```') == {
        "reply": "hi",
        "picks": [],
    }
    with pytest.raises(llm.LLMError):
        llm.extract_json("no json here")
