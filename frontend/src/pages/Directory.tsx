// Authors, genres and series: the three ways into the catalogue besides search.
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, Book, Counted, Named, SeriesSummary } from "../api";
import { Availability, BookGrid, ErrorNote, Loading, Stars } from "../components/Book";
import { CoverStack } from "./MyLibrary";

export function Authors() {
  const authors = useQuery({ queryKey: ["authors"], queryFn: () => api.get<Counted[]>("/authors"), staleTime: Infinity });
  if (authors.isLoading) return <Loading />;
  if (authors.error) return <ErrorNote error={authors.error} />;

  const byLetter = new Map<string, Counted[]>();
  for (const author of authors.data ?? []) {
    const surname = author.name.split(" ").at(-1) ?? author.name;
    const letter = surname[0].toUpperCase();
    byLetter.set(letter, [...(byLetter.get(letter) ?? []), author]);
  }
  const letters = [...byLetter.keys()].sort();

  return (
    <>
      <h1>Authors</h1>
      <nav className="letters" aria-label="Jump to letter">
        {letters.map((letter) => <a key={letter} href={`#letter-${letter}`}>{letter}</a>)}
      </nav>
      <div className="directory">
        {letters.map((letter) => (
          <section key={letter} id={`letter-${letter}`}>
            <h2>{letter}</h2>
            <ul>
              {byLetter.get(letter)!.map((a) => (
                <li key={a.id}>
                  <Link to={`/authors/${a.id}`}>{a.name}</Link> <span className="muted small">{a.book_count}</span>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </>
  );
}

function bookFooter(book: Book) {
  return (
    <p className="card-meta">
      <Stars value={book.rating_avg} count={book.rating_count} />
      <Availability book={book} />
    </p>
  );
}

export function AuthorPage() {
  const { id } = useParams();
  const author = useQuery({ queryKey: ["author", id], queryFn: () => api.get<Named & { books: Book[] }>(`/authors/${id}`) });
  if (author.isLoading) return <Loading />;
  if (author.error || !author.data) return <ErrorNote error={author.error} />;
  return (
    <>
      <p><Link to="/authors">All authors</Link></p>
      <h1>{author.data.name}</h1>
      <p className="muted">{author.data.books.length} {author.data.books.length === 1 ? "book" : "books"} in the library, oldest first</p>
      <BookGrid books={author.data.books} footer={bookFooter} />
    </>
  );
}

export function Genres() {
  const genres = useQuery({ queryKey: ["categories"], queryFn: () => api.get<Counted[]>("/categories"), staleTime: Infinity });
  if (genres.isLoading) return <Loading />;
  if (genres.error) return <ErrorNote error={genres.error} />;
  const sorted = [...(genres.data ?? [])].sort((a, b) => b.book_count - a.book_count);
  const big = sorted.slice(0, 18);
  const rest = sorted.slice(18).sort((a, b) => a.name.localeCompare(b.name));
  return (
    <>
      <h1>Genres</h1>
      <ul className="genre-tiles">
        {big.map((g) => (
          <li key={g.id}>
            <Link to={`/browse?category=${encodeURIComponent(g.name)}`}>
              <strong>{g.name}</strong>
              <span>{g.book_count} books</span>
            </Link>
          </li>
        ))}
      </ul>
      <h2>More specific</h2>
      <ul className="chips">
        {rest.map((g) => (
          <li key={g.id}>
            <Link className="chip" to={`/browse?category=${encodeURIComponent(g.name)}`}>
              {g.name} <span className="muted">{g.book_count}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

export function SeriesList() {
  const series = useQuery({ queryKey: ["series"], queryFn: () => api.get<SeriesSummary[]>("/series"), staleTime: Infinity });
  if (series.isLoading) return <Loading />;
  if (series.error) return <ErrorNote error={series.error} />;
  return (
    <>
      <h1>Series</h1>
      <ul className="tile-list">
        {series.data?.map((s) => (
          <li key={s.id}>
            <Link className="tile" to={`/series/${s.id}`}>
              <CoverStack covers={s.covers} />
              <strong>{s.name}</strong>
              <span className="muted small">{s.authors.join(", ")}</span>
              <span className="muted small">{s.book_count} {s.book_count === 1 ? "book" : "books"}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

export function SeriesPage() {
  const { id } = useParams();
  const series = useQuery({ queryKey: ["series", id], queryFn: () => api.get<Named & { books: Book[] }>(`/series/${id}`) });
  if (series.isLoading) return <Loading />;
  if (series.error || !series.data) return <ErrorNote error={series.error} />;
  return (
    <>
      <p><Link to="/series">All series</Link></p>
      <h1>{series.data.name}</h1>
      <p className="muted">In order of publication</p>
      <BookGrid books={series.data.books} footer={bookFooter} />
    </>
  );
}
