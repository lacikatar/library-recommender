import { useMutation, useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, formatDate, Library, Loan, ReadingList } from "../api";
import { useRefreshPersonal, useUser } from "../auth";
import { authorNames, BookGrid, Cover, Empty, ErrorNote, Loading } from "../components/Book";

const TABS = [
  ["loans", "Borrowed"],
  ["reading", "Reading now"],
  ["want", "Want to read"],
  ["read", "Read"],
  ["lists", "Reading lists"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function MyLibrary() {
  const { user, loading } = useUser();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "loans";
  const refresh = useRefreshPersonal();
  const library = useQuery({ queryKey: ["library", user?.id ?? 0], queryFn: () => api.get<Library>("/me/library"), enabled: !!user });
  const giveBack = useMutation({ mutationFn: (id: number) => api.post(`/loans/${id}/return`), onSuccess: refresh });

  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;

  const data = library.data;
  const counts: Record<Tab, number | undefined> = {
    loans: data?.current_loans.length,
    reading: data?.shelves.reading.length,
    want: data?.shelves.want.length,
    read: data?.shelves.read.length,
    lists: undefined,
  };

  return (
    <>
      <h1>My library</h1>
      <div className="tabs" role="tablist">
        {TABS.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} className={tab === key ? "tab on" : "tab"} onClick={() => setParams({ tab: key })}>
            {label}{counts[key] != null && <span className="count">{counts[key]}</span>}
          </button>
        ))}
      </div>

      {library.isLoading && <Loading />}
      {library.error && <ErrorNote error={library.error} />}

      {data && tab === "loans" && (
        <>
          {data.waitlist.length > 0 && (
            <section>
              <h2>Waitlist</h2>
              <ul className="loan-list">
                {data.waitlist.map(({ book, position, ready }) => (
                  <li key={book.isbn} className="loan">
                    <Link to={`/books/${book.isbn}`}><Cover book={book} size="s" /></Link>
                    <div>
                      <h3><Link to={`/books/${book.isbn}`}>{book.title}</Link></h3>
                      {ready
                        ? <p><span className="tag tag-in">Ready for you</span> <Link to={`/books/${book.isbn}`}>Borrow it now</Link></p>
                        : <p className="muted">Number {position} in the queue</p>}
                    </div>
                  </li>
                ))}
              </ul>
            </section>
          )}
          <h2>Out now <span className="muted small">{data.current_loans.length} of {data.loan_limit}</span></h2>
          {data.current_loans.length === 0 ? (
            <Empty><p>Nothing borrowed. <Link to="/for-you">See what we picked for you</Link>.</p></Empty>
          ) : (
            <ul className="loan-list">
              {data.current_loans.map((loan) => (
                <LoanRow key={loan.id} loan={loan}>
                  <button className="button button-quiet" disabled={giveBack.isPending} onClick={() => giveBack.mutate(loan.id)}>Return book</button>
                </LoanRow>
              ))}
            </ul>
          )}
          {data.past_loans.length > 0 && (
            <>
              <h2>Returned</h2>
              <ul className="loan-list">
                {data.past_loans.map((loan) => <LoanRow key={loan.id} loan={loan} />)}
              </ul>
            </>
          )}
        </>
      )}

      {data && (tab === "reading" || tab === "want" || tab === "read") && (
        data.shelves[tab].length === 0 ? (
          <Empty><p>This shelf is empty. Open any book and choose a shelf for it.</p></Empty>
        ) : (
          <BookGrid
            books={data.shelves[tab]}
            footer={(book) => tab === "read" ? (
              <p className="card-meta">
                {book.my_rating ? <span className="stars">{"★".repeat(book.my_rating)}</span> : <Link to={`/books/${book.isbn}`}>Rate it</Link>}
              </p>
            ) : null}
          />
        )
      )}

      {tab === "lists" && <Lists />}
    </>
  );
}

function LoanRow({ loan, children }: { loan: Loan; children?: React.ReactNode }) {
  return (
    <li className="loan">
      <Link to={`/books/${loan.book.isbn}`}><Cover book={loan.book} size="s" /></Link>
      <div>
        <h3><Link to={`/books/${loan.book.isbn}`}>{loan.book.title}</Link></h3>
        <p className="muted small">{authorNames(loan.book)}</p>
        {loan.returned_at ? (
          <p className="muted small">Borrowed {formatDate(loan.borrowed_at)}, returned {formatDate(loan.returned_at)}</p>
        ) : (
          <p><span className={loan.overdue ? "stamp stamp-late" : "stamp"}>{loan.overdue ? "Overdue since" : "Due"} {formatDate(loan.due_at)}</span></p>
        )}
      </div>
      {children}
    </li>
  );
}

function Lists() {
  const refresh = useRefreshPersonal();
  const [name, setName] = useState("");
  const lists = useQuery({ queryKey: ["lists"], queryFn: () => api.get<ReadingList[]>("/lists") });
  const create = useMutation({
    mutationFn: () => api.post<ReadingList>("/lists", { name }),
    onSuccess: () => { setName(""); refresh(); },
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) create.mutate();
  }
  return (
    <>
      <form className="inline-form" onSubmit={submit}>
        <label>
          New reading list
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Summer holiday" maxLength={120} />
        </label>
        <button className="button" disabled={!name.trim() || create.isPending}>Create list</button>
      </form>
      {create.error && <ErrorNote error={create.error} />}
      {lists.data?.length === 0 && <Empty><p>Lists are for anything: a holiday stack, books to buy, a challenge for the year.</p></Empty>}
      <ul className="tile-list">
        {lists.data?.map((list) => (
          <li key={list.id}>
            <Link className="tile" to={`/lists/${list.id}`}>
              <CoverStack covers={list.covers} />
              <strong>{list.name}</strong>
              <span className="muted small">{list.book_count} {list.book_count === 1 ? "book" : "books"}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

export function CoverStack({ covers }: { covers: (string | null)[] }) {
  return (
    <span className="cover-stack" aria-hidden="true">
      {covers.filter(Boolean).slice(0, 4).map((src, i) => (
        <img key={i} src={src!} alt="" loading="lazy" referrerPolicy="no-referrer" />
      ))}
    </span>
  );
}

export function ListPage() {
  const { id } = useParams();
  const { user, loading } = useUser();
  const navigate = useNavigate();
  const refresh = useRefreshPersonal();
  const list = useQuery({ queryKey: ["lists", id], queryFn: () => api.get<ReadingList>(`/lists/${id}`), enabled: !!user });
  const removeBook = useMutation({ mutationFn: (isbn: string) => api.delete(`/lists/${id}/books/${isbn}`), onSuccess: refresh });
  const removeList = useMutation({
    mutationFn: () => api.delete(`/lists/${id}`),
    onSuccess: async () => { await refresh(); navigate("/my-library?tab=lists"); },
  });

  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace />;
  if (list.isLoading) return <Loading />;
  if (list.error || !list.data) return <ErrorNote error={list.error} />;

  return (
    <>
      <p><Link to="/my-library?tab=lists">All reading lists</Link></p>
      <h1>{list.data.name}</h1>
      {list.data.books!.length === 0 ? (
        <Empty><p>No books yet. Open a book and tick this list under “Reading lists”.</p></Empty>
      ) : (
        <BookGrid
          books={list.data.books!}
          footer={(book) => (
            <button className="link-button small" onClick={() => removeBook.mutate(book.isbn)}>Remove from list</button>
          )}
        />
      )}
      <p>
        <button className="button button-quiet" disabled={removeList.isPending}
          onClick={() => window.confirm(`Delete the list “${list.data!.name}”? The books stay in the library.`) && removeList.mutate()}>
          Delete list
        </button>
      </p>
    </>
  );
}
