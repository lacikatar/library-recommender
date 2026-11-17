import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, User } from "./api";

/** The signed-in reader, or null. Cached so every component can ask cheaply. */
export function useUser() {
  const query = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User | null>("/auth/me"),
    staleTime: 5 * 60_000,
  });
  return { user: query.data ?? null, loading: query.isLoading };
}

/** After signing in or out, everything personal is stale. */
export function useSessionChanged() {
  const client = useQueryClient();
  return (user: User | null) => {
    client.clear();
    client.setQueryData(["me"], user);
  };
}

/** Call after any action that changes what the reader has read, rated or borrowed. */
export function useRefreshPersonal() {
  const client = useQueryClient();
  return () =>
    Promise.all(
      ["book", "library", "recommendations", "home", "lists", "similar", "reviews", "books"].map(
        (key) => client.invalidateQueries({ queryKey: [key] }),
      ),
    );
}
