import { useEffect } from "react";
import { Link, Route, Routes, useLocation } from "react-router-dom";
import Layout from "./components/Layout";
import About from "./pages/About";
import { Login, Register } from "./pages/Account";
import Ask from "./pages/Ask";
import BookPage from "./pages/BookPage";
import Browse from "./pages/Browse";
import { AuthorPage, Authors, Genres, SeriesList, SeriesPage } from "./pages/Directory";
import ForYou from "./pages/ForYou";
import Home from "./pages/Home";
import MyLibrary, { ListPage } from "./pages/MyLibrary";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

function NotFound() {
  return (
    <div className="narrow">
      <h1>That page is not on our shelves</h1>
      <p>The link may be old. <Link to="/browse">Browse the catalogue</Link> or go <Link to="/">home</Link>.</p>
    </div>
  );
}

export default function App() {
  return (
    <>
      <ScrollToTop />
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="browse" element={<Browse />} />
          <Route path="books/:isbn" element={<BookPage />} />
          <Route path="genres" element={<Genres />} />
          <Route path="authors" element={<Authors />} />
          <Route path="authors/:id" element={<AuthorPage />} />
          <Route path="series" element={<SeriesList />} />
          <Route path="series/:id" element={<SeriesPage />} />
          <Route path="ask" element={<Ask />} />
          <Route path="for-you" element={<ForYou />} />
          <Route path="my-library" element={<MyLibrary />} />
          <Route path="lists/:id" element={<ListPage />} />
          <Route path="login" element={<Login />} />
          <Route path="register" element={<Register />} />
          <Route path="about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </>
  );
}
