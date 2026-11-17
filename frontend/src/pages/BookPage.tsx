import { useMutation, useQuery } from "@tanstack/react-query";
import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, Book, BookDetail, formatDate, ReadingList, Reviews, ShelfStatus } from "../api";
import { useRefreshPersonal, useUser } from "../auth";
import { Cover, ErrorNote, Loading, Shelf, Stars } from "../components/Book";

const SHELF_LABELS: Record<ShelfStatus, string> = {
  want: "Want to read",
  reading: "Reading now",
  read: "Read",
};

export default function BookPage() {
  const { isbn = "" } = useParams();
  const { user } = useUser();
  const refresh = useRefreshPersonal();
  const book = useQuery({ queryKey: ["book", isbn, user?.id ?? 0], queryFn: () => api.get<BookDetail>(`/books/${isbn}`) });
  const similar = useQuery({ queryKey: ["similar", isbn], queryFn: () => api.get<Book[]>(`/books/${isbn}/similar?limit=10`) });
  const reviews = useQuery({ queryKey: ["reviews", isbn], queryFn: () => api.get<Reviews>(`/books/${isbn}/reviews`) });

  const action = useMutation({
    mutationFn: (run: () => Promise<unknown>) => run(),
    onSuccess: refresh,
  });
  const run = (fn: () => Promise<unknown>) => action.mutate(fn);

  useEffect(() => {
    if (book.data) document.title = `${book.data.title} | Laci's Library`;
    return () => { document.title = "Laci's Library"; };
  }, [book.data]);

  if (book.isLoading) return <Loading what="Fetching the book" />;
  if (book.error || !book.data) return <ErrorNote error={book.error} />;
  const b = book.data;
  const mine = b.mine;

  return (
    <>
      <article className="book-page">
        <div className="book-page-cover">
          <Cover book={b} size="l" />
        </div>
        <div>
          <h1>{b.title}</h1>
          <p className="byline">
            {b.authors.map((a, i) => (
              <span key={a.id}>{i > 0 && ", "}<Link to={`/authors/${a.id}`}>{a.name}</Link></span>
            ))}
          </p>
          {b.series && <p>Part of the series <Link to={`/series/${b.series.id}`}>{b.series.name}</Link></p>}
          <p><Stars value={b.rating_avg} count={b.rating_count} /></p>

          <section className="desk" aria-label="Borrowing">
            {mine?.loan ? (
              <>
                <p>
                  <span className="stamp">Due {formatDate(mine.loan.due_at)}</span>
                  You have this book. It came from shelf {mine.loan.shelf}.
                </p>
                <button className="button" disabled={action.isPending} onClick={() => run(() => api.post(`/loans/${mine.loan!.id}/return`))}>
                  Return book
                </button>
              </>
            ) : b.available_copies > 0 && !(b.waitlist_length > 0 && !mine?.waitlist_position) ? (
              <>
                <p><strong>{b.available_copies} of {b.total_copies}</strong> copies on the shelf. Loans run for 21 days.</p>
                {user ? (
                  <button className="button" disabled={action.isPending} onClick={() => run(() => api.post(`/books/${isbn}/borrow`))}>
                    Borrow book
                  </button>
                ) : (
                  <Link className="button" to="/login">Log in to borrow</Link>
                )}
              </>
            ) : (
              <>
                <p>
                  {b.available_copies > 0 ? "Returned copies are being held for the waitlist." : `All ${b.total_copies} copies are out.`}{" "}
                  {b.waitlist_length > 0 && `${b.waitlist_length} waiting.`}
                </p>
                {!user ? (
                  <Link className="button" to="/login">Log in to join the waitlist</Link>
                ) : mine?.waitlist_position ? (
                  <>
                    <p>You are number {mine.waitlist_position} in the queue.</p>
                    <button className="button button-quiet" disabled={action.isPending} onClick={() => run(() => api.delete(`/books/${isbn}/waitlist`))}>
                      Leave waitlist
                    </button>
                  </>
                ) : (
                  <button className="button" disabled={action.isPending} onClick={() => run(() => api.post(`/books/${isbn}/waitlist`))}>
                    Join waitlist
                  </button>
                )}
              </>
            )}
            {action.error && <ErrorNote error={action.error} />}
          </section>

          {user && mine && (
            <section className="my-shelf" aria-label="Your shelf">
              <label>
                Your shelf
                <select
                  value={mine.shelf ?? ""}
                  onChange={(e) => run(() => api.put(`/books/${isbn}/shelf`, { status: e.target.value || null }))}
                >
                  <option value="">Not on a shelf</option>
                  {Object.entries(SHELF_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>{label}</option>
                  ))}
                </select>
              </label>
              <AddToList isbn={isbn} inLists={mine.list_ids} onDone={refresh} />
            </section>
          )}

          <div className="description">
            {b.description ? b.description.split(/\n{2,}/).map((p, i) => <p key={i}>{p}</p>) : <p className="muted">No description on file.</p>}
          </div>

          <dl className="facts">
            <div><dt>Published</dt><dd>{[b.year, b.publisher].filter(Boolean).join(", ") || "Unknown"}</dd></div>
            {b.pages && <div><dt>Length</dt><dd>{b.pages} pages</dd></div>}
            <div><dt>ISBN</dt><dd>{b.isbn}</dd></div>
            <div>
              <dt>Genres</dt>
              <dd className="chips">
                {b.categories.map((c) => <Link key={c} className="chip chip-small" to={`/browse?category=${encodeURIComponent(c)}`}>{c}</Link>)}
              </dd>
            </div>
          </dl>
        </div>
      </article>

      {similar.data && similar.data.length > 0 && <Shelf title="Readers also enjoyed" books={similar.data} />}
      {b.series_books && b.series_books.length > 1 && (
        <Shelf title={`All of ${b.series!.name}`} books={b.series_books.filter((s) => s.isbn !== b.isbn)} />
      )}

      <section className="reviews narrow">
        <h2>Ratings and reviews</h2>
        {user && mine ? (
          <ReviewForm key={`${isbn}-${mine.review?.rating}-${mine.review?.text}`} isbn={isbn} existing={mine.review} onDone={refresh} />
        ) : (
          <p><Link to="/login">Log in</Link> to rate this book. Ratings are what make your picks personal.</p>
        )}
        {reviews.data && reviews.data.items.length > 0 && (
          <>
            <div className="histogram" aria-label="Rating breakdown">
              {Object.entries(reviews.data.histogram).sort((a, b) => Number(b[0]) - Number(a[0])).map(([star, n]) => (
                <div key={star} className="histogram-row">
                  <span>{star}★</span>
                  <span className="bar"><span style={{ width: `${(100 * n) / Math.max(1, b.rating_count)}%` }} /></span>
                  <span className="muted small">{n}</span>
                </div>
              ))}
            </div>
            <ul className="review-list">
              {reviews.data.items.filter((r) => r.text).slice(0, 12).map((r) => (
                <li key={r.id}>
                  <p><strong>{r.reader}</strong> <span className="stars">{"★".repeat(r.rating)}</span> <span className="muted small">{formatDate(r.updated_at)}</span></p>
                  <p>{r.text}</p>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
    </>
  );
}

function ReviewForm({ isbn, existing, onDone }: { isbn: string; existing: { rating: number; text: string } | null; onDone: () => void }) {
  const [rating, setRating] = useState(existing?.rating ?? 0);
  const [text, setText] = useState(existing?.text ?? "");
  const save = useMutation({
    mutationFn: () => api.put(`/books/${isbn}/review`, { rating, text }),
    onSuccess: onDone,
  });
  const remove = useMutation({ mutationFn: () => api.delete(`/books/${isbn}/review`), onSuccess: onDone });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (rating) save.mutate();
  }

  return (
    <form className="review-form" onSubmit={submit}>
      <fieldset className="star-input">
        <legend>{existing ? "Your rating" : "Rate this book"}</legend>
        {[1, 2, 3, 4, 5].map((n) => (
          <label key={n} className={n <= rating ? "on" : ""}>
            <input type="radio" name="rating" value={n} checked={rating === n} onChange={() => setRating(n)} />
            <span aria-hidden="true">★</span>
            <span className="visually-hidden">{n} {n === 1 ? "star" : "stars"}</span>
          </label>
        ))}
      </fieldset>
      <label>
        Review <span className="muted">(optional)</span>
        <textarea rows={3} value={text} maxLength={4000} onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="row">
        <button className="button" type="submit" disabled={!rating || save.isPending}>
          {existing ? "Update rating" : "Save rating"}
        </button>
        {existing && (
          <button className="button button-quiet" type="button" onClick={() => remove.mutate()} disabled={remove.isPending}>
            Remove rating
          </button>
        )}
        {save.isSuccess && <span className="muted" role="status">Saved. Your picks have been updated.</span>}
      </div>
      {save.error && <ErrorNote error={save.error} />}
    </form>
  );
}

function AddToList({ isbn, inLists, onDone }: { isbn: string; inLists: number[]; onDone: () => void }) {
  const lists = useQuery({ queryKey: ["lists"], queryFn: () => api.get<ReadingList[]>("/lists") });
  const toggle = useMutation({
    mutationFn: (listId: number) =>
      inLists.includes(listId) ? api.delete(`/lists/${listId}/books/${isbn}`) : api.put(`/lists/${listId}/books/${isbn}`),
    onSuccess: onDone,
  });
  if (!lists.data) return null;
  if (lists.data.length === 0) {
    return <p className="small muted">No reading lists yet. <Link to="/my-library?tab=lists">Create one</Link>.</p>;
  }
  return (
    <fieldset className="list-picker">
      <legend>Reading lists</legend>
      {lists.data.map((list) => (
        <label key={list.id} className="check">
          <input type="checkbox" checked={inLists.includes(list.id)} disabled={toggle.isPending} onChange={() => toggle.mutate(list.id)} />
          {list.name}
        </label>
      ))}
    </fieldset>
  );
}
