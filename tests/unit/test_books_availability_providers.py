from app.books.availability_providers import JackettBookAvailabilityProvider
from app.books.models import Book, BookEdition


class Response:
    ok = True
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, *, params, headers, timeout):
        self.calls.append(
            {"url": url, "params": params, "headers": headers, "timeout": timeout}
        )
        return Response(self.payload)


def test_jackett_book_provider_ranks_by_kindle_format_priority():
    session = Session(
        {
            "Results": [
                {
                    "Title": "Candidate Book - Example Author [English] EPUB",
                    "Seeders": 80,
                    "Size": 9 * 1024**2,
                    "Tracker": "Books",
                    "Details": "https://tracker.example/details/epub?apikey=private",
                },
                {
                    "Title": "Candidate Book - Example Author [English] KFX",
                    "Seeders": 5,
                    "Size": 15 * 1024**2,
                    "Tracker": "Books",
                    "Details": "https://tracker.example/details/kfx?apikey=private",
                },
                {
                    "Title": "Candidate Book - Example Author [English] PDF",
                    "Seeders": 200,
                    "Size": 40 * 1024**2,
                    "Tracker": "Books",
                    "Details": "https://tracker.example/details/pdf?apikey=private",
                },
                {
                    "Title": "Candidate Book - Example Author MOBI",
                    "Seeders": 500,
                    "Size": 5 * 1024**2,
                    "Tracker": "Books",
                },
            ]
        }
    )
    provider = JackettBookAvailabilityProvider(
        base_url="http://127.0.0.1:9117",
        api_key="private-key",
        min_seeders=1,
        session=session,
    )
    book = Book(title="Candidate Book", authors=["Example Author"], edition_language="English")

    results = provider.search(book, limit=10)

    assert [result.format_guess for result in results[:3]] == ["KFX", "EPUB", "PDF"]
    assert results[0].title == "Candidate Book - Example Author"
    assert results[0].language_guess == "English"
    assert "apikey" not in results[0].source_reference
    assert results[0].match_confidence == "medium"
    assert all(result.format_guess != "MOBI" for result in results)
    assert session.calls[0]["params"]["Category"] == "7000"
    assert session.calls[0]["params"]["apikey"] == "private-key"


def test_jackett_queries_fall_back_to_primary_edition_language():
    session = Session({"Results": []})
    provider = JackettBookAvailabilityProvider(
        base_url="http://127.0.0.1:9117",
        api_key="private-key",
        min_seeders=1,
        session=session,
    )
    book = Book(title="Candidate Book", authors=["Example Author"])
    book.editions.append(
        BookEdition(title="Candidate Book", language="English", primary=True)
    )

    provider.search(book, limit=10)

    assert "English" in session.calls[0]["params"]["Query"]
