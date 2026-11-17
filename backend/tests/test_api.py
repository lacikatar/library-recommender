from .conftest import isbn_of


def test_catalogue_is_seeded(client):
    page = client.get("/api/books", params={"page_size": 60}).json()
    assert page["total"] == 251
    assert len(page["items"]) == 60
    assert all(b["total_copies"] >= 1 for b in page["items"])
    assert len(client.get("/api/authors").json()) == 122
    assert client.get("/api/books/0000000000000").status_code == 404


def test_search_finds_titles_authors_and_themes(client):
    def titles(q):
        return [b["title"] for b in client.get("/api/books", params={"q": q}).json()["items"]]

    assert titles("pride and prejudice")[0] == "Pride and Prejudice"
    assert "Six of Crows" in titles("bardugo")
    assert any(t.startswith("Harry Potter") for t in titles("wizard school")[:3])


def test_filters_and_sorting(client):
    fantasy = client.get("/api/books", params={"category": "Fantasy", "sort": "newest"}).json()
    assert fantasy["total"] > 50
    years = [b["year"] for b in fantasy["items"]]
    assert years == sorted(years, reverse=True)
    assert all("Fantasy" in b["categories"] for b in fantasy["items"])


def test_register_validates_and_rejects_duplicates(client):
    body = {"name": "A", "username": "alice", "email": "a@example.com", "password": "long-enough"}
    assert client.post("/api/auth/register", json={**body, "password": "short"}).status_code == 422
    assert client.post("/api/auth/register", json=body).status_code == 201
    assert client.get("/api/auth/me").json()["username"] == "alice"
    duplicate = client.post("/api/auth/register", json={**body, "email": "b@example.com"})
    assert duplicate.status_code == 409 and "username" in duplicate.json()["detail"]


def test_login_logout(client):
    wrong = client.post("/api/auth/login", json={"username": "demo", "password": "nope"})
    assert wrong.status_code == 401
    assert (
        client.post(
            "/api/auth/login", json={"username": "DEMO", "password": "demo1234"}
        ).status_code
        == 200
    )
    assert client.get("/api/auth/me").json()["name"] == "Demo Reader"
    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").json() is None
    assert client.get("/api/me/library").status_code == 401


def test_passwords_are_hashed(db):
    from app.models import User

    demo = db.query(User).filter_by(username="demo").one()
    assert demo.password_hash.startswith("$2") and "demo1234" not in demo.password_hash


def test_book_page_works_logged_out(client):
    """The original PHP page crashed here: it logged a view with no user."""
    detail = client.get(f"/api/books/{isbn_of(client, 'Dune')}").json()
    assert detail["title"] == "Dune" and detail["mine"] is None
    assert len(detail["series_books"]) == 8


def test_borrow_return_cycle(newcomer):
    isbn = isbn_of(newcomer, "Circe")
    before = newcomer.get(f"/api/books/{isbn}").json()["available_copies"]
    state = newcomer.post(f"/api/books/{isbn}/borrow").json()
    assert state["loan"] and state["shelf"] == "reading"
    assert newcomer.get(f"/api/books/{isbn}").json()["available_copies"] == before - 1
    assert newcomer.post(f"/api/books/{isbn}/borrow").status_code == 409  # already out

    library = newcomer.get("/api/me/library").json()
    assert [l["book"]["title"] for l in library["current_loans"]] == ["Circe"]

    returned = newcomer.post(f"/api/loans/{state['loan']['id']}/return").json()
    assert returned["returned_at"]
    library = newcomer.get("/api/me/library").json()
    assert library["current_loans"] == []
    assert [b["title"] for b in library["shelves"]["read"]] == ["Circe"]


def test_loan_limit(newcomer):
    books = newcomer.get("/api/books", params={"available": True, "page_size": 10}).json()["items"]
    for book in books[:5]:
        assert newcomer.post(f"/api/books/{book['isbn']}/borrow").status_code == 201
    sixth = newcomer.post(f"/api/books/{books[5]['isbn']}/borrow")
    assert sixth.status_code == 409 and "5 books" in sixth.json()["detail"]


def test_waitlist_is_first_come_first_served(client, db):
    from app.models import Copy, Loan, User, utcnow

    isbn = isbn_of(client, "Circe")
    holder = db.query(User).filter_by(username="reader01").one()
    copies = db.query(Copy).filter_by(isbn=isbn).all()
    db.query(Loan).filter(Loan.copy_id.in_([c.id for c in copies])).delete()
    loans = [Loan(copy_id=c.id, user_id=holder.id, due_at=utcnow()) for c in copies]
    db.add_all(loans)
    db.commit()

    def sign_up(name):
        client.post("/api/auth/logout")
        client.post(
            "/api/auth/register",
            json={
                "name": name,
                "username": name,
                "email": f"{name}@example.com",
                "password": "password1",
            },
        )

    sign_up("first")
    assert client.post(f"/api/books/{isbn}/borrow").status_code == 409  # nothing free
    assert client.post(f"/api/books/{isbn}/waitlist").json()["waitlist_position"] == 1
    sign_up("second")
    assert client.post(f"/api/books/{isbn}/waitlist").json()["waitlist_position"] == 2

    loans[0].returned_at = utcnow()  # one copy comes back
    db.commit()
    assert client.post(f"/api/books/{isbn}/borrow").status_code == 409  # "second" must wait
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "first", "password": "password1"})
    assert client.get("/api/me/library").json()["waitlist"][0]["ready"] is True
    assert client.post(f"/api/books/{isbn}/borrow").status_code == 201
    assert client.get("/api/me/library").json()["waitlist"] == []


def test_review_marks_book_read_and_updates_average(newcomer):
    isbn = isbn_of(newcomer, "Yellowface")
    before = newcomer.get(f"/api/books/{isbn}").json()["rating_count"]
    assert newcomer.put(f"/api/books/{isbn}/review", json={"rating": 6}).status_code == 422
    state = newcomer.put(f"/api/books/{isbn}/review", json={"rating": 5, "text": "Sharp."}).json()
    assert state["review"] == {"rating": 5, "text": "Sharp."} and state["shelf"] == "read"
    newcomer.put(f"/api/books/{isbn}/review", json={"rating": 4})  # editing, not duplicating
    assert newcomer.get(f"/api/books/{isbn}").json()["rating_count"] == before + 1
    reviews = newcomer.get(f"/api/books/{isbn}/reviews").json()
    assert reviews["items"][0]["reader"] == "New Reader"


def test_reading_lists(newcomer, client):
    created = newcomer.post("/api/lists", json={"name": "Summer"}).json()
    isbn = isbn_of(newcomer, "Life of Pi")
    assert newcomer.put(f"/api/lists/{created['id']}/books/{isbn}").status_code == 204
    newcomer.put(f"/api/lists/{created['id']}/books/{isbn}")  # adding twice is harmless
    assert [b["title"] for b in newcomer.get(f"/api/lists/{created['id']}").json()["books"]] == [
        "Life of Pi"
    ]
    assert newcomer.get(f"/api/books/{isbn}").json()["mine"]["list_ids"] == [created["id"]]

    # Lists are private to their owner.
    client.post("/api/auth/logout")
    client.post("/api/auth/login", json={"username": "demo", "password": "demo1234"})
    assert client.get(f"/api/lists/{created['id']}").status_code == 404
    assert client.delete(f"/api/lists/{created['id']}").status_code == 404
