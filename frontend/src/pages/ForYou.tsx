import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { api, Book, Counted, User } from "../api";
import { useRefreshPersonal, useSessionChanged, useUser } from "../auth";
import { BookGrid, ErrorNote, Loading } from "../components/Book";

// Plain-language names for the four signals the ranker blends.
const SIGNAL_LABELS: Record<string, string> = {
  series: "Continues a series you follow",
  taste: "Similar to books you liked",
  community: "Liked by readers like you",
  genres: "In your favourite genres",
  popular: "Popular in the library",
};

export default function ForYou() {
  const { user, loading } = useUser();
  const refresh = useRefreshPersonal();
  const picks = useQuery({
    queryKey: ["recommendations", user?.id ?? 0],
    queryFn: () => api.get<{ items: Book[]; known_books: number }>("/recommendations?limit=24"),
    enabled: !!user,
  });
  const dismiss = useMutation({
    mutationFn: (isbn: string) => api.post(`/books/${isbn}/dismiss`),
    onSuccess: refresh,
  });

  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;

  return (
    <>
      <h1>Picked for {user.name.split(" ")[0]}</h1>
      <p className="lede">
        {picks.data && picks.data.known_books < 3
          ? "These are based on your favourite genres and what other readers enjoy. Rate a few books and they will get much more personal."
          : "Based on what you have rated, read and borrowed. Every pick updates the moment you rate something."}
      </p>
      <GenrePreferences user={user} />

      {picks.isLoading && <Loading what="Choosing books" />}
      {picks.error && <ErrorNote error={picks.error} />}
      {picks.data && (
        <BookGrid
          books={picks.data.items}
          footer={(book) => (
            <>
              <details className="why">
                <summary>Why this book</summary>
                <ul>
                  {Object.entries(book.signals ?? {})
                    .filter(([, value]) => value > 0.005)
                    .sort((a, b) => b[1] - a[1])
                    .map(([key, value]) => (
                      <li key={key}>
                        <span>{SIGNAL_LABELS[key] ?? key}</span>
                        <span className="bar"><span style={{ width: `${Math.min(100, value * 250)}%` }} /></span>
                      </li>
                    ))}
                </ul>
              </details>
              <button className="link-button small" disabled={dismiss.isPending} onClick={() => dismiss.mutate(book.isbn)}>
                Not interested
              </button>
            </>
          )}
        />
      )}
      <p className="muted small"><Link to="/about">How these picks are made</Link></p>
    </>
  );
}

function GenrePreferences({ user }: { user: User }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<number[]>(user.favorite_category_ids);
  const sessionChanged = useSessionChanged();
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.get<Counted[]>("/categories"), staleTime: Infinity });
  const save = useMutation({
    mutationFn: () => api.put<User>("/auth/preferences", { favorite_category_ids: selected }),
    onSuccess: (updated) => { sessionChanged(updated); setOpen(false); },
  });

  if (!open) {
    return (
      <p className="prefs-line">
        Favourite genres: {user.favorite_categories.length ? user.favorite_categories.join(", ") : "none chosen"}.{" "}
        <button className="link-button" onClick={() => setOpen(true)}>Change</button>
      </p>
    );
  }
  return (
    <GenrePicker
      categories={categories.data ?? []}
      selected={selected}
      onChange={setSelected}
      footer={
        <div className="row">
          <button className="button" onClick={() => save.mutate()} disabled={save.isPending}>Save genres</button>
          <button className="button button-quiet" onClick={() => setOpen(false)}>Cancel</button>
        </div>
      }
    />
  );
}

export function GenrePicker({ categories, selected, onChange, footer }: {
  categories: Counted[];
  selected: number[];
  onChange: (ids: number[]) => void;
  footer?: React.ReactNode;
}) {
  const popular = [...categories].sort((a, b) => b.book_count - a.book_count).filter((c) => c.name !== "Fiction").slice(0, 28);
  const toggle = (id: number) =>
    onChange(selected.includes(id) ? selected.filter((x) => x !== id) : selected.length < 12 ? [...selected, id] : selected);
  return (
    <fieldset className="genre-picker">
      <legend>Pick the genres you reach for first</legend>
      <div className="chips">
        {popular.map((c) => (
          <label key={c.id} className={selected.includes(c.id) ? "chip chip-on" : "chip"}>
            <input type="checkbox" className="visually-hidden" checked={selected.includes(c.id)} onChange={() => toggle(c.id)} />
            {c.name}
          </label>
        ))}
      </div>
      {footer}
    </fieldset>
  );
}
