import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { Answer, api } from "../api";
import { useUser } from "../auth";
import { authorNames, Availability, Cover, Empty, ErrorNote, Loading, ShelfTalker } from "../components/Book";
import { AskBox, EXAMPLE_REQUESTS } from "./Home";

export default function Ask() {
  const [params] = useSearchParams();
  const question = params.get("q")?.trim() ?? "";
  const { user } = useUser();

  const status = useQuery({
    queryKey: ["assistant-status"],
    queryFn: () => api.get<{ llm: boolean }>("/assistant/status"),
    staleTime: Infinity,
  });
  const answer = useQuery({
    queryKey: ["ask", question, user?.id ?? 0],
    queryFn: () => api.post<Answer>("/assistant/ask", { message: question }),
    enabled: question.length >= 2,
    staleTime: 60_000,
    retry: false,
  });

  return (
    <div className="narrow">
      <h1>Ask the librarian</h1>
      <p className="lede">
        Say it the way you would at the desk: a mood, a genre, a length, or “something like” a
        book you enjoyed.
      </p>
      <AskBox key={question} initial={question} autoFocus />

      {!question && (
        <>
          <h2 className="h3">Try one of these</h2>
          <ul className="chips">
            {[...EXAMPLE_REQUESTS, "Sci-fi classics under 300 pages", "Anything by Leigh Bardugo", "A sad book about grief"].map((example) => (
              <li key={example}>
                <Link className="chip" to={`/ask?q=${encodeURIComponent(example)}`}>{example}</Link>
              </li>
            ))}
          </ul>
        </>
      )}

      {answer.isFetching && <Loading what="Checking the shelves" />}
      {answer.error && <ErrorNote error={answer.error} />}

      {answer.data && !answer.isFetching && (
        <section aria-live="polite">
          <p className="reply">{answer.data.reply}</p>
          {answer.data.picks.length === 0 ? (
            <Empty>
              <p>Try a broader request, or <Link to="/browse">browse the whole catalogue</Link>.</p>
            </Empty>
          ) : (
            <ol className="pick-list">
              {answer.data.picks.map((book) => (
                <li key={book.isbn} className="pick">
                  <Link to={`/books/${book.isbn}`}><Cover book={book} size="s" /></Link>
                  <div>
                    <h2 className="h3"><Link to={`/books/${book.isbn}`}>{book.title}</Link></h2>
                    <p className="muted small">
                      {[authorNames(book), book.year].filter(Boolean).join(", ")}.
                      {book.pages ? ` ${book.pages} pages.` : ""}
                    </p>
                    <ShelfTalker>{book.reason}</ShelfTalker>
                    <Availability book={book} />
                  </div>
                </li>
              ))}
            </ol>
          )}
          <p className="muted small">
            {answer.data.mode === "llm"
              ? "Chosen and explained by an AI model, from books this library owns."
              : status.data?.llm
                ? "The AI model was unavailable, so this answer came from the built-in search."
                : "Answered by the built-in search. Add an API key to let an AI model explain its picks in full sentences."}
          </p>
        </section>
      )}
    </div>
  );
}
