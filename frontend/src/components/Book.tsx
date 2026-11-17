import { ReactNode, useState } from "react";
import { Link } from "react-router-dom";
import { Book } from "../api";

const SPINE_COLOURS = ["#1F4038", "#4A3D9E", "#7A2E3A", "#2F5D7C", "#6B5B2E", "#3D3D3D"];

/** A book cover. Falls back to a plain cloth-bound cover if the image is missing. */
export function Cover({ book, size = "m" }: { book: Pick<Book, "title" | "cover_url" | "isbn">; size?: "s" | "m" | "l" }) {
  const [broken, setBroken] = useState(false);
  if (book.cover_url && !broken) {
    return (
      <img
        className={`cover cover-${size}`}
        src={book.cover_url}
        alt={`Cover of ${book.title}`}
        loading="lazy"
        referrerPolicy="no-referrer"
        onError={() => setBroken(true)}
      />
    );
  }
  const hash = [...book.isbn].reduce((sum, ch) => sum + ch.charCodeAt(0), 0);
  const colour = SPINE_COLOURS[hash % SPINE_COLOURS.length];
  return (
    <div className={`cover cover-${size} cover-blank`} style={{ background: colour }} role="img" aria-label={`Cover of ${book.title}`}>
      <span>{book.title}</span>
    </div>
  );
}

export function Stars({ value, count }: { value: number | null; count?: number }) {
  if (value == null) return <span className="muted small">No ratings yet</span>;
  return (
    <span className="stars" aria-label={`Rated ${value.toFixed(1)} out of 5`}>
      <span aria-hidden="true">★</span> {value.toFixed(1)}
      {count != null && <span className="muted"> ({count})</span>}
    </span>
  );
}

export function authorNames(book: Book): string {
  return book.authors.map((a) => a.name).join(", ");
}

/** The yellow note a librarian clips under a book they recommend. */
export function ShelfTalker({ children }: { children: ReactNode }) {
  return <p className="talker">{children}</p>;
}

export function BookCard({ book, footer }: { book: Book; footer?: ReactNode }) {
  return (
    <article className="book-card">
      <Link to={`/books/${book.isbn}`} className="book-card-link">
        <Cover book={book} />
        <h3>{book.title}</h3>
      </Link>
      <p className="muted small">{authorNames(book)}</p>
      {book.reason && <ShelfTalker>{book.reason}</ShelfTalker>}
      {footer}
    </article>
  );
}

/** A horizontal row of books standing on a shelf edge. */
export function Shelf({ title, books, action }: { title: string; books: Book[]; action?: ReactNode }) {
  return (
    <section className="shelf">
      <header className="shelf-head">
        <h2>{title}</h2>
        {action}
      </header>
      <div className="shelf-row" tabIndex={0} role="group" aria-label={title}>
        {books.map((book) => (
          <BookCard key={book.isbn} book={book} />
        ))}
      </div>
    </section>
  );
}

export function BookGrid({ books, footer }: { books: Book[]; footer?: (book: Book) => ReactNode }) {
  return (
    <div className="book-grid">
      {books.map((book) => (
        <BookCard key={book.isbn} book={book} footer={footer?.(book)} />
      ))}
    </div>
  );
}

export function Availability({ book }: { book: Book }) {
  return book.available_copies > 0 ? (
    <span className="tag tag-in">On the shelf</span>
  ) : (
    <span className="tag tag-out">All copies out</span>
  );
}

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted" role="status">{what}…</p>;
}

export function ErrorNote({ error }: { error: unknown }) {
  return <p className="error" role="alert">{error instanceof Error ? error.message : "Something went wrong."}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
