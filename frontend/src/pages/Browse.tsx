import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { api, Book, Counted, Page } from "../api";
import { Availability, BookGrid, Empty, ErrorNote, Loading, Stars } from "../components/Book";

const SORTS = [
  ["relevance", "Best match"],
  ["title", "Title A to Z"],
  ["newest", "Newest first"],
  ["rating", "Highest rated"],
  ["popular", "Most popular"],
  ["added", "Recently added"],
] as const;

export default function Browse() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const sort = params.get("sort") ?? (q ? "relevance" : "title");
  const available = params.get("available") === "1";
  const page = Number(params.get("page") ?? "1");

  const categories = useQuery({
    queryKey: ["categories"],
    queryFn: () => api.get<Counted[]>("/categories"),
    staleTime: Infinity,
  });
  const search = new URLSearchParams({ q, sort, page: String(page), page_size: "24" });
  if (category) search.set("category", category);
  if (available) search.set("available", "true");
  const books = useQuery({
    queryKey: ["books", search.toString()],
    queryFn: () => api.get<Page<Book>>(`/books?${search}`),
    placeholderData: keepPreviousData,
  });

  function update(changes: Record<string, string>) {
    const next = new URLSearchParams(params);
    next.delete("page");
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next);
  }

  const pages = books.data ? Math.ceil(books.data.total / books.data.page_size) : 0;

  return (
    <>
      <h1>{q ? `Results for “${q}”` : category || "The catalogue"}</h1>
      <form className="filters" onSubmit={(e) => e.preventDefault()}>
        <label>
          Search
          <input type="search" defaultValue={q} key={q} placeholder="Title, author or theme"
            onKeyDown={(e) => e.key === "Enter" && update({ q: e.currentTarget.value.trim(), sort: "" })} />
        </label>
        <label>
          Genre
          <select value={category} onChange={(e) => update({ category: e.target.value })}>
            <option value="">All genres</option>
            {categories.data?.map((c) => (
              <option key={c.id} value={c.name}>{c.name} ({c.book_count})</option>
            ))}
          </select>
        </label>
        <label>
          Sort by
          <select value={sort} onChange={(e) => update({ sort: e.target.value })}>
            {SORTS.filter(([value]) => q || value !== "relevance").map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label className="check">
          <input type="checkbox" checked={available} onChange={(e) => update({ available: e.target.checked ? "1" : "" })} />
          On the shelf now
        </label>
      </form>

      {books.isLoading && <Loading what="Fetching books" />}
      {books.error && <ErrorNote error={books.error} />}
      {books.data && (
        <>
          <p className="muted" role="status">
            {books.data.total} {books.data.total === 1 ? "book" : "books"}
          </p>
          {books.data.total === 0 ? (
            <Empty>
              <p>No books match. Remove a filter, or <Link to={`/ask?q=${encodeURIComponent(q)}`}>ask the librarian</Link> in your own words.</p>
            </Empty>
          ) : (
            <BookGrid
              books={books.data.items}
              footer={(book) => (
                <p className="card-meta">
                  <Stars value={book.rating_avg} count={book.rating_count} />
                  <Availability book={book} />
                </p>
              )}
            />
          )}
          {pages > 1 && (
            <nav className="pager" aria-label="Pages">
              <button className="button button-quiet" disabled={page <= 1} onClick={() => { const n = new URLSearchParams(params); n.set("page", String(page - 1)); setParams(n); }}>
                Previous
              </button>
              <span>Page {page} of {pages}</span>
              <button className="button button-quiet" disabled={page >= pages} onClick={() => { const n = new URLSearchParams(params); n.set("page", String(page + 1)); setParams(n); }}>
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </>
  );
}
