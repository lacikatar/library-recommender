import { Link } from "react-router-dom";

export default function About() {
  return (
    <div className="narrow prose">
      <h1>How recommendations work</h1>
      <p className="lede">
        There is one ranking, not a menu of algorithms. For every book you have not read, the
        library asks four questions and blends the answers.
      </p>

      <dl className="signals">
        <div>
          <dt>Is it like books you enjoyed?</dt>
          <dd>
            Each book is described by its blurb, its genres, its author and its series. Rare
            genres count for more than broad ones, so sharing “Greek Mythology” means more than
            sharing “Fiction”. Books you rated low push similar books down.
          </dd>
        </div>
        <div>
          <dt>Did readers with your taste enjoy it?</dt>
          <dd>
            If people who loved the books you loved also loved another one, that book rises,
            even when its description looks nothing like your usual reading.
          </dd>
        </div>
        <div>
          <dt>Is it in your favourite genres?</dt>
          <dd>The genres you picked when you joined. They matter most before you have rated anything.</dd>
        </div>
        <div>
          <dt>Do readers here rate it well?</dt>
          <dd>
            A smoothed average, so one five-star review cannot beat forty reviews averaging 4.6.
          </dd>
        </div>
      </dl>

      <h2>The blend changes as the library gets to know you</h2>
      <p>
        A new reader sees favourite genres and popular books. One five-star rating is already
        enough for your own taste to carry about 40% of the weight, and after half a dozen it
        carries about three quarters. If you are partway through a series, the next book goes to the front.
      </p>
      <p>
        The final list is then spread out: no series appears twice, and a book too similar to
        one already chosen gives way to something different. Every pick says why it is there,
        and “Not interested” removes a book for good.
      </p>

      <h2>Ask the librarian</h2>
      <p>
        A request such as “something like Dune but shorter” is read for genres, an author, a
        book to compare with, length and publication date, and whatever words remain are matched
        against book descriptions. That shortlist needs no outside service.
      </p>
      <p>
        If the library is configured with an AI model, the model chooses from that shortlist and
        writes a sentence about each pick. It never sees or suggests a book the library does not
        own: any title outside the shortlist is discarded before you see the answer.
      </p>

      <h2>What is stored about you</h2>
      <p>
        Your ratings, shelves, loans, the book pages you open and the books you mark “Not
        interested”. Nothing else, and none of it leaves this server unless an AI model is
        switched on, in which case your request, favourite genres and the titles you rated
        highest are sent with each question to the librarian.
      </p>

      <p><Link to="/for-you">See your picks</Link></p>
    </div>
  );
}
