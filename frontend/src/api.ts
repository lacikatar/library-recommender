// One small typed wrapper around fetch. The session lives in an httpOnly
// cookie, so there is no token handling in the browser at all.

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail)
      ? detail.map((d: { loc: string[]; msg: string }) => `${d.loc.at(-1)}: ${d.msg}`).join(". ")
      : detail || "Something went wrong. Try again.";
    throw new ApiError(response.status, message);
  }
  return data as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body ?? {}),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body ?? {}),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

export type Named = { id: number; name: string };

export type Book = {
  isbn: string;
  title: string;
  authors: Named[];
  series: Named | null;
  cover_url: string | null;
  year: number | null;
  pages: number | null;
  categories: string[];
  rating_avg: number | null;
  rating_count: number;
  available_copies: number;
  total_copies: number;
  reason?: string;
  reason_kind?: string;
  signals?: Record<string, number>;
  my_rating?: number | null;
};

export type ShelfStatus = "want" | "reading" | "read";

export type Loan = {
  id: number;
  borrowed_at: string;
  due_at: string;
  returned_at: string | null;
  overdue: boolean;
  shelf: string;
  condition: string;
  book: Book;
};

export type MyState = {
  shelf: ShelfStatus | null;
  review: { rating: number; text: string } | null;
  loan: Omit<Loan, "book"> | null;
  waitlist_position: number | null;
  list_ids: number[];
};

export type BookDetail = Book & {
  description: string;
  publisher: string;
  waitlist_length: number;
  series_books?: Book[];
  mine: MyState | null;
};

export type Page<T> = { total: number; page: number; page_size: number; items: T[] };
export type Counted = Named & { book_count: number };
export type SeriesSummary = Counted & { authors: string[]; covers: (string | null)[] };
export type HomeShelf = { title: string; subtitle: string; kind: string; books: Book[] };
export type User = {
  id: number;
  username: string;
  name: string;
  favorite_category_ids: number[];
  favorite_categories: string[];
};
export type ReadingList = Named & {
  description: string;
  book_count: number;
  covers: (string | null)[];
  books?: Book[];
};
export type Reviews = {
  histogram: Record<string, number>;
  items: { id: number; reader: string; rating: number; text: string; updated_at: string }[];
};
export type Library = {
  current_loans: Loan[];
  past_loans: Loan[];
  shelves: Record<ShelfStatus, Book[]>;
  waitlist: { book: Book; position: number; ready: boolean }[];
  loan_limit: number;
};
export type Answer = {
  reply: string;
  mode: "llm" | "builtin";
  understood: string;
  picks: Book[];
};

export function formatDate(iso: string): string {
  return new Date(iso + (iso.endsWith("Z") ? "" : "Z")).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
