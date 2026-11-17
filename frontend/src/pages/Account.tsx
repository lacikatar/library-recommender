import { useMutation, useQuery } from "@tanstack/react-query";
import { FormEvent, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { api, Counted, User } from "../api";
import { useSessionChanged, useUser } from "../auth";
import { ErrorNote } from "../components/Book";
import { GenrePicker } from "./ForYou";

export function Login() {
  const { user } = useUser();
  const sessionChanged = useSessionChanged();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const login = useMutation({
    mutationFn: (body: { username: string; password: string }) => api.post<User>("/auth/login", body),
    onSuccess: (signedIn) => { sessionChanged(signedIn); navigate("/"); },
  });
  if (user) return <Navigate to="/" replace />;

  function submit(event: FormEvent) {
    event.preventDefault();
    login.mutate({ username, password });
  }

  return (
    <div className="form-page">
      <h1>Log in</h1>
      <form onSubmit={submit} className="stack">
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required autoFocus /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {login.error && <ErrorNote error={login.error} />}
        <button className="button" disabled={login.isPending}>Log in</button>
      </form>
      <p>
        Just looking?{" "}
        <button className="link-button" onClick={() => login.mutate({ username: "demo", password: "demo1234" })}>
          Log in as the demo reader
        </button>
      </p>
      <p>New here? <Link to="/register">Join the library</Link></p>
    </div>
  );
}

export function Register() {
  const { user } = useUser();
  const sessionChanged = useSessionChanged();
  const navigate = useNavigate();
  const [form, setForm] = useState({ name: "", username: "", email: "", password: "", confirm: "" });
  const [genres, setGenres] = useState<number[]>([]);
  const [mismatch, setMismatch] = useState(false);
  const categories = useQuery({ queryKey: ["categories"], queryFn: () => api.get<Counted[]>("/categories"), staleTime: Infinity });
  const register = useMutation({
    mutationFn: () =>
      api.post<User>("/auth/register", {
        name: form.name, username: form.username, email: form.email, password: form.password,
        favorite_category_ids: genres,
      }),
    onSuccess: (created) => { sessionChanged(created); navigate("/for-you"); },
  });
  if (user && !register.isSuccess) return <Navigate to="/" replace />;

  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });

  function submit(event: FormEvent) {
    event.preventDefault();
    const differs = form.password !== form.confirm;
    setMismatch(differs);
    if (!differs) register.mutate();
  }

  return (
    <div className="form-page form-page-wide">
      <h1>Join the library</h1>
      <form onSubmit={submit} className="stack">
        <div className="two-col">
          <label>Your name<input value={form.name} onChange={set("name")} autoComplete="name" required maxLength={120} /></label>
          <label>Username<input value={form.username} onChange={set("username")} autoComplete="username" required minLength={3} maxLength={30} pattern="[A-Za-z0-9_.\-]+" title="Letters, numbers, dots, dashes and underscores" /></label>
        </div>
        <label>Email<input type="email" value={form.email} onChange={set("email")} autoComplete="email" required /></label>
        <div className="two-col">
          <label>Password <span className="muted small">at least 8 characters</span><input type="password" value={form.password} onChange={set("password")} autoComplete="new-password" required minLength={8} /></label>
          <label>Repeat password<input type="password" value={form.confirm} onChange={set("confirm")} autoComplete="new-password" required aria-invalid={mismatch} /></label>
        </div>
        {mismatch && <p className="error" role="alert">The two passwords are different. Type the same password in both boxes.</p>}
        <GenrePicker categories={categories.data ?? []} selected={genres} onChange={setGenres} />
        <p className="muted small">Genres are optional. They give you good picks before you have rated anything.</p>
        {register.error && <ErrorNote error={register.error} />}
        <button className="button" disabled={register.isPending}>Create account</button>
      </form>
      <p>Already a member? <Link to="/login">Log in</Link></p>
    </div>
  );
}
