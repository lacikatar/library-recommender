import { FormEvent, useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useSessionChanged, useUser } from "../auth";

export default function Layout() {
  const { user } = useUser();
  const sessionChanged = useSessionChanged();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  function search(event: FormEvent) {
    event.preventDefault();
    navigate(`/browse?q=${encodeURIComponent(query.trim())}`);
    setMenuOpen(false);
  }

  async function logOut() {
    await api.post("/auth/logout");
    sessionChanged(null);
    navigate("/");
  }

  const close = () => setMenuOpen(false);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <header className="site-header">
        <div className="wrap header-row">
          <Link to="/" className="brand" onClick={close}>
            Laci’s Library
          </Link>
          <button className="menu-toggle" aria-expanded={menuOpen} aria-controls="site-nav" onClick={() => setMenuOpen(!menuOpen)}>
            Menu
          </button>
          <nav id="site-nav" className={menuOpen ? "nav open" : "nav"} aria-label="Main">
            <NavLink to="/browse" onClick={close}>Browse</NavLink>
            <NavLink to="/genres" onClick={close}>Genres</NavLink>
            <NavLink to="/authors" onClick={close}>Authors</NavLink>
            <NavLink to="/series" onClick={close}>Series</NavLink>
            <NavLink to="/ask" onClick={close}>Ask the librarian</NavLink>
            {user && <NavLink to="/for-you" onClick={close}>For you</NavLink>}
            {user && <NavLink to="/my-library" onClick={close}>My library</NavLink>}
            <form className="header-search" role="search" onSubmit={search}>
              <label className="visually-hidden" htmlFor="header-q">Search the catalogue</label>
              <input id="header-q" type="search" placeholder="Title, author or theme" value={query} onChange={(e) => setQuery(e.target.value)} />
            </form>
            {user ? (
              <span className="account">
                <span className="muted-on-dark">{user.name.split(" ")[0]}</span>
                <button className="link-on-dark" onClick={logOut}>Log out</button>
              </span>
            ) : (
              <span className="account">
                <NavLink to="/login" onClick={close}>Log in</NavLink>
                <Link to="/register" className="button button-yellow" onClick={close}>Join</Link>
              </span>
            )}
          </nav>
        </div>
      </header>
      <main id="main" className="wrap">
        <Outlet />
      </main>
      <footer className="site-footer">
        <div className="wrap">
          <Link to="/about">How recommendations work</Link>
          <span className="muted">A portfolio project by Laci. Demo data, fictional readers.</span>
        </div>
      </footer>
    </>
  );
}
