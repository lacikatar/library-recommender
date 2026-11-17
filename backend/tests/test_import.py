import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "import_legacy", Path(__file__).parent.parent / "scripts" / "import_legacy.py"
)
import_legacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(import_legacy)

DUMP = r"""
INSERT INTO `author` (`Author_ID`, `Name`, `Date_Of_Birth`, `Nationality`) VALUES
(1, 'Ann O\'Neil', NULL, NULL),
(2, 'Holly  Jackson', NULL, NULL);
INSERT INTO `book_series` (`Series_ID`, `Name`) VALUES
(5, 'Narnia (Chronological Order)');
INSERT INTO `category` (`Category_ID`, `Name`) VALUES
(1, 'Fantasy Fiction'), (2, 'Audiobook'), (3, 'Queer');
INSERT INTO `book` (`ISBN`, `Title`, `Publisher`, `Description`, `Release_Year`, `Page_Nr`, `Series_ID`, `Image_URL`) VALUES
('9780000000001', 'It''s; a (test)', 'Pub', 'Line one.\r\n\r\n\r\nShe said \"hi\"; then left.', 2020, 123, 5, NULL);
INSERT INTO `wrote` (`ISBN`, `Author_ID`) VALUES
('9780000000001', 1), ('9780000000001', 2);
INSERT INTO `belongs` (`ISBN`, `Category_ID`) VALUES
('9780000000001', 1), ('9780000000001', 2), ('9780000000001', 3);
INSERT INTO `copy` (`Copy_ID`, `Copy_Condition`, `Shelf_Position`, `ISBN`) VALUES
(1, 'New', '1-1', '9780000000001');
INSERT INTO `member` (`Member_ID`, `Name`, `Email`, `Password`) VALUES
(1, 'Real Person', 'real@example.com', 'abc123');
"""


def test_parses_mysql_escapes_and_cleans_names():
    catalogue = import_legacy.build_catalogue(import_legacy.read_tables(DUMP))
    (book,) = catalogue["books"]
    assert book["title"] == "It's; a (test)"
    assert book["description"] == 'Line one.\n\nShe said "hi"; then left.'
    assert book["authors"] == ["Ann O'Neil", "Holly Jackson"]
    assert book["series"] == "Narnia"
    assert book["categories"] == ["Fantasy", "LGBTQ+"]  # merged; "Audiobook" dropped
    assert book["copies"] == [{"condition": "New", "shelf": "1-1"}]


def test_member_data_is_never_imported():
    tables = import_legacy.read_tables(DUMP)
    assert "member" not in tables
    assert "real@example.com" not in str(import_legacy.build_catalogue(tables))
