import { useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, HomeShelf } from "../api";
import { useUser } from "../auth";
import { ErrorNote, Loading, Shelf } from "../components/Book";

export const EXAMPLE_REQUESTS = [
  "Something like Six of Crows",
  "Short classics",
  "New thrillers",
  "Enemies to lovers with dragons",
  "Greek myths retelling",
];

export function AskBox({ initial = "", autoFocus = false }: { initial?: string; autoFocus?: boolean }) {
  const [text, setText] = useState(initial);
  const navigate = useNavigate();
  function submit(event: FormEvent) {
    event.preventDefault();
    if (text.trim().length >= 2) navigate(`/ask?q=${encodeURIComponent(text.trim())}`);
  }
  return (
    <form className="ask-box" onSubmit={submit}>
      <label htmlFor="ask-input" className="visually-hidden">Describe what you feel like reading</label>
      <input
        id="ask-input"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="A heist with a found family, under 500 pages"
        autoFocus={autoFocus}
        maxLength={600}
      />
      <button className="button button-yellow" type="submit">Find books</button>
    </form>
  );
}

export default function Home() {
  const { user } = useUser();
  const home = useQuery({
    queryKey: ["home", user?.id ?? 0],
    queryFn: () => api.get<{ shelves: HomeShelf[] }>("/recommendations/home"),
  });

  return (
    <>
      <section className="hero">
        <h1>What do you feel like reading?</h1>
        <p className="lede">
          Describe a mood, a genre or a book you loved. The librarian searches every book on
          our shelves.
        </p>
        <AskBox />
        <ul className="chips" aria-label="Example requests">
          {EXAMPLE_REQUESTS.map((example) => (
            <li key={example}>
              <Link className="chip" to={`/ask?q=${encodeURIComponent(example)}`}>{example}</Link>
            </li>
          ))}
        </ul>
      </section>

      {!user && (
        <aside className="notice">
          <p>
            <strong>Picks get personal once you rate a few books.</strong> Join, or look around
            as the demo reader: username <code>demo</code>, password <code>demo1234</code>.
          </p>
          <span className="notice-actions">
            <Link className="button" to="/register">Join the library</Link>
            <Link className="button button-quiet" to="/login">Log in</Link>
          </span>
        </aside>
      )}

      {home.isLoading && <Loading what="Filling the shelves" />}
      {home.error && <ErrorNote error={home.error} />}
      {home.data?.shelves.map((shelf) => (
        <Shelf
          key={shelf.title}
          title={shelf.title}
          books={shelf.books}
          action={
            shelf.kind === "for_you" ? <Link to="/for-you">See all picks</Link>
            : shelf.kind === "new" ? <Link to="/browse?sort=added">See everything new</Link>
            : shelf.kind === "genre" ? <Link to={`/browse?category=${encodeURIComponent(shelf.title)}`}>Browse {shelf.title}</Link>
            : undefined
          }
        />
      ))}
    </>
  );
}
