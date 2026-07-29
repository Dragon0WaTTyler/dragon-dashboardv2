from __future__ import annotations

from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import login_required

from app.books.assets import BookAssetService, LocalAssetError
from app.books.audiobooks import AudiobookCandidateError, BookAudiobookService
from app.books.availability import AvailabilityCandidateError, BookAvailabilityService
from app.books.availability_providers import (
    AvailabilityProviderError,
    JackettBookAvailabilityProvider,
)
from app.books.book_quotes import BookQuotesSnapshotService
from app.books.clippings import KindleClippingsStateStore, project_clippings_outbox
from app.books.diagnostics import KnowledgeDiagnosticsService
from app.books.kindle import BookKindleExportService
from app.books.kindle_sync import KindleSyncCredentialStore
from app.books.metadata import BookMetadataService
from app.books.repositories import BookRepository
from app.books.runtime import (
    AudioRuntimeError,
    BookAudioRuntimeService,
    BookTextRuntimeService,
    TextRuntimeError,
)
from app.books.services import BookService, book_detail, book_item, quotes_view

bp = Blueprint("books", __name__, url_prefix="/books")
settings_bp = Blueprint("knowledge_settings", __name__, url_prefix="/settings/knowledge")
BOOK_QUOTES_FILTERS = {"all", "review", "matched", "ambiguous", "needs_review"}
KINDLE_CLIPPINGS_FILTERS = {"all", "review", "matched", "ambiguous", "failed"}
KINDLE_CLIPPINGS_BULK_CLEAR_FILTERS = {"matched", "failed"}
KINDLE_CLIPPINGS_FAILURE_RESET_FILTERS = {"failed"}
BOOK_LIBRARY_SECTIONS = (
    ("library", "Library", "books.index"),
    ("reading", "Reading", "books.reading"),
    ("finished", "Finished", "books.finished"),
    ("wishlist", "Wishlist", "books.wishlist"),
    ("paused", "Paused", "books.paused"),
    ("dropped", "Dropped", "books.dropped"),
    ("reference", "Reference", "books.reference"),
    ("audiobooks", "Audiobooks", "books.audiobooks"),
    ("collections", "Collections", "books.collections"),
    ("needs_review", "Needs Review", "books.needs_review"),
    ("highlights", "Highlights", "books.highlights"),
    ("quotes", "Quotes", "books.quotes"),
)
BOOK_METADATA_SECTIONS = (
    ("all", "All Metadata", "books.index"),
    ("inbox", "Inbox", "books.metadata_inbox"),
    ("missing_isbn", "Missing ISBN", "books.metadata_missing_isbn"),
    ("candidate_found", "Candidate Found", "books.metadata_candidate_found"),
    ("needs_review", "Needs Review", "books.metadata_needs_review"),
    ("verified", "Verified", "books.metadata_verified"),
    ("no_isbn", "No ISBN", "books.metadata_no_isbn"),
    ("error", "Errors", "books.metadata_errors"),
)
BOOK_FORMAT_SECTIONS = (
    ("all", "All Formats", "books.index"),
    ("kfx", "Has KFX", "books.format_kfx"),
    ("azw3", "Has AZW3", "books.format_azw3"),
    ("epub", "Has EPUB", "books.format_epub"),
    ("pdf", "Has PDF", "books.format_pdf"),
    ("pdf_only", "PDF Only", "books.format_pdf_only"),
    ("missing", "No Digital", "books.format_no_digital"),
)
BOOK_SIGNAL_SECTIONS = (
    ("all", "All Signals", "books.index"),
    ("highlights", "Has Highlights", "books.signal_highlights"),
    ("quotes", "Has Quotes", "books.signal_quotes"),
    ("notes", "Has Notes", "books.signal_notes"),
    ("audiobook", "Has Audiobook", "books.audiobooks"),
)


def _metadata_providers():
    return current_app.extensions.get("dragon_book_metadata_providers")


def _availability_providers():
    providers = current_app.extensions.get("dragon_book_availability_providers")
    if providers is not None:
        return providers
    providers = [
        JackettBookAvailabilityProvider(
            base_url=current_app.config["DRAGON_JACKETT_URL"],
            api_key=current_app.config["DRAGON_JACKETT_API_KEY"],
            min_seeders=current_app.config["DRAGON_JACKETT_MIN_SEEDERS"],
            categories=current_app.config.get("DRAGON_BOOK_JACKETT_CATEGORIES", "7000"),
        )
    ]
    current_app.extensions["dragon_book_availability_providers"] = providers
    return providers


def _kindle_clippings_store():
    return KindleClippingsStateStore(
        Path(current_app.instance_path) / "knowledge" / "kindle_clippings_sync.json"
    )


def _kindle_sync_credential_store():
    instance_root = Path(current_app.instance_path)
    return KindleSyncCredentialStore(
        token_path=instance_root / "secrets" / "kindle_book_quotes_token",
        metadata_path=instance_root / "knowledge" / "kindle_sync_credentials.json",
    )


def _books_navigation(active_key: str) -> list[dict[str, str]]:
    return [
        {
            "key": key,
            "label": label,
            "href": url_for(endpoint),
            "active": key == active_key,
        }
        for key, label, endpoint in BOOK_LIBRARY_SECTIONS
    ]


def _books_metadata_navigation(active_key: str) -> list[dict[str, str]]:
    return [
        {
            "key": key,
            "label": label,
            "href": url_for(endpoint),
            "active": key == active_key,
        }
        for key, label, endpoint in BOOK_METADATA_SECTIONS
    ]


def _books_format_navigation(active_key: str) -> list[dict[str, str]]:
    return [
        {
            "key": key,
            "label": label,
            "href": url_for(endpoint),
            "active": key == active_key,
        }
        for key, label, endpoint in BOOK_FORMAT_SECTIONS
    ]


def _books_signal_navigation(active_key: str) -> list[dict[str, str]]:
    return [
        {
            "key": key,
            "label": label,
            "href": url_for(endpoint),
            "active": key == active_key,
        }
        for key, label, endpoint in BOOK_SIGNAL_SECTIONS
    ]


def _book_index_args() -> dict[str, str]:
    return {
        "q": str(request.args.get("q") or ""),
        "status": str(request.args.get("status") or ""),
        "format_filter": str(request.args.get("format") or ""),
        "language": str(request.args.get("language") or ""),
        "metadata": str(request.args.get("metadata") or ""),
        "audiobook": str(request.args.get("audiobook") or ""),
        "author": str(request.args.get("author") or ""),
        "translator": str(request.args.get("translator") or ""),
        "highlights": str(request.args.get("highlights") or ""),
        "quotes": str(request.args.get("quotes") or ""),
        "notes": str(request.args.get("notes") or ""),
        "collection": str(request.args.get("collection") or ""),
        "review": str(request.args.get("review") or ""),
        "view": str(request.args.get("view") or "grid"),
    }


def _book_index_context(*, section: str = "library") -> dict[str, object]:
    args = _book_index_args()
    if args["view"] not in {"grid", "list"}:
        args["view"] = "grid"
    section_copy = {
        "library": {
            "title": "Books",
            "description": (
                "Canonical identity, reading state, editions, formats, "
                "and local availability."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.index",
            "empty_title": "Your book library is empty",
            "empty_message": (
                "Import a validated local snapshot when migration is "
                "explicitly approved."
            ),
        },
        "reading": {
            "title": "Reading",
            "description": (
                "Books currently in progress, with the same local filters "
                "still available around that lane."
            ),
            "statuses": {"reading"},
            "status_label": "Reading",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.reading",
            "empty_title": "No books in reading right now",
            "empty_message": (
                "Move a book into reading from its detail page when you want "
                "it to surface here."
            ),
        },
        "finished": {
            "title": "Finished",
            "description": (
                "Books you already completed, kept ready for rediscovery, "
                "quotes, and highlights."
            ),
            "statuses": {"finished"},
            "status_label": "Finished",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.finished",
            "empty_title": "No finished books yet",
            "empty_message": (
                "Finished books will gather here once their reading status "
                "is complete."
            ),
        },
        "wishlist": {
            "title": "Wishlist",
            "description": (
                "Books you want to return to later, including any older "
                "want-to-read records."
            ),
            "statuses": {"wishlist", "want_to_read"},
            "status_label": "Wishlist",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.wishlist",
            "empty_title": "No wishlist books yet",
            "empty_message": (
                "Add books to the wishlist to keep this lane stocked."
            ),
        },
        "paused": {
            "title": "Paused",
            "description": (
                "Books you intentionally paused, kept separate from active "
                "reading without losing them in the wider library."
            ),
            "statuses": {"paused"},
            "status_label": "Paused",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.paused",
            "empty_title": "No paused books right now",
            "empty_message": (
                "Books moved into paused will surface here until you resume "
                "or retire them."
            ),
        },
        "dropped": {
            "title": "Dropped",
            "description": (
                "Books you deliberately stopped, still visible as part of the "
                "personal reading record."
            ),
            "statuses": {"dropped"},
            "status_label": "Dropped",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.dropped",
            "empty_title": "No dropped books yet",
            "empty_message": (
                "Books marked as dropped will gather here for later review."
            ),
        },
        "reference": {
            "title": "Reference",
            "description": (
                "Books you keep around as references, archives, or lookup "
                "material rather than active reading projects."
            ),
            "statuses": {"reference"},
            "status_label": "Reference",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.reference",
            "empty_title": "No reference books yet",
            "empty_message": (
                "Reference books and archive material will surface here."
            ),
        },
        "audiobooks": {
            "title": "Audiobooks",
            "description": (
                "Books that already have audiobook editions or audio assets "
                "attached locally."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "yes",
            "audiobook_label": "Available",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "signal_nav": "audiobook",
            "collection_mode": False,
            "reset_endpoint": "books.audiobooks",
            "empty_title": "No audiobooks in the library yet",
            "empty_message": (
                "Books with audiobook editions will surface here as soon as "
                "they are attached locally."
            ),
        },
        "collections": {
            "title": "Collections",
            "description": (
                "Group the library by your personal shelves, then open one "
                "collection at a time."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": True,
            "reset_endpoint": "books.collections",
            "empty_title": "No collection books yet",
            "empty_message": (
                "Assign books to at least one collection to turn this view "
                "into a proper shelf map."
            ),
        },
        "needs_review": {
            "title": "Needs Review",
            "description": (
                "Books with metadata or candidate signals that still need a "
                "local human pass before the library feels settled."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "yes",
            "review_label": "Needs review",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "",
            "metadata_label": "",
            "metadata_nav": "all",
            "collection_mode": False,
            "reset_endpoint": "books.needs_review",
            "empty_title": "No books need review right now",
            "empty_message": (
                "When metadata or availability matching needs help, those "
                "books will surface here."
            ),
        },
        "metadata_inbox": {
            "title": "Metadata Inbox",
            "description": (
                "Books whose metadata still needs a pass, whether they are "
                "missing details, awaiting a candidate decision, or errored."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "inbox",
            "metadata_label": "Inbox",
            "metadata_nav": "inbox",
            "collection_mode": False,
            "reset_endpoint": "books.metadata_inbox",
            "empty_title": "No books in the metadata inbox",
            "empty_message": (
                "When metadata falls behind or needs review, those books "
                "will gather here."
            ),
        },
        "metadata_missing_isbn": {
            "title": "Missing ISBN",
            "description": (
                "Books that still need an ISBN check, without mixing in "
                "intentional no-ISBN cases."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "missing_isbn",
            "metadata_label": "Missing ISBN",
            "metadata_nav": "missing_isbn",
            "collection_mode": False,
            "reset_endpoint": "books.metadata_missing_isbn",
            "empty_title": "No books missing ISBN data",
            "empty_message": (
                "Books that still need an ISBN lookup will surface here."
            ),
        },
        "metadata_candidate_found": {
            "title": "Candidate Found",
            "description": (
                "Books with a likely metadata candidate that still needs a "
                "local confirmation pass."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "candidate_found",
            "metadata_label": "Candidate Found",
            "metadata_nav": "candidate_found",
            "collection_mode": False,
            "reset_endpoint": "books.metadata_candidate_found",
            "empty_title": "No pending metadata candidates",
            "empty_message": (
                "Books with a likely external metadata candidate will land "
                "here before you verify them."
            ),
        },
        "metadata_needs_review": {
            "title": "Metadata Needs Review",
            "description": (
                "Books whose metadata looks risky enough to deserve a closer "
                "human pass."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "needs_review",
            "metadata_label": "Needs Review",
            "metadata_nav": "needs_review",
            "collection_mode": False,
            "reset_endpoint": "books.metadata_needs_review",
            "empty_title": "No metadata review cases right now",
            "empty_message": (
                "Books with ambiguous or risky metadata will gather here."
            ),
        },
        "metadata_verified": {
            "title": "Verified Metadata",
            "description": (
                "Books whose current metadata state is already clean enough "
                "to trust."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "verified",
            "metadata_label": "Verified",
            "metadata_nav": "verified",
            "collection_mode": False,
            "reset_endpoint": "books.metadata_verified",
            "empty_title": "No verified metadata books yet",
            "empty_message": (
                "Books will surface here once their metadata state is verified."
            ),
        },
        "metadata_no_isbn": {
            "title": "No ISBN",
            "description": (
                "Books that intentionally stay in the library without a "
                "legitimate ISBN."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "no_isbn",
            "metadata_label": "No ISBN",
            "metadata_nav": "no_isbn",
            "collection_mode": False,
            "reset_endpoint": "books.metadata_no_isbn",
            "empty_title": "No no-ISBN books yet",
            "empty_message": (
                "Books with intentionally absent ISBN data will surface here."
            ),
        },
        "metadata_errors": {
            "title": "Metadata Errors",
            "description": (
                "Books whose metadata workflow hit an explicit error and need "
                "attention."
            ),
            "statuses": set(),
            "status_label": "",
            "review": "",
            "review_label": "",
            "audiobook": "",
            "audiobook_label": "",
            "metadata": "error",
            "metadata_label": "Errors",
            "metadata_nav": "error",
            "collection_mode": False,
            "reset_endpoint": "books.metadata_errors",
            "empty_title": "No metadata errors right now",
            "empty_message": (
                "If a metadata pass fails explicitly, those books will gather "
                "here."
            ),
        },
        "format_kfx": {
            "title": "Has KFX",
            "description": (
                "Books that already have a local KFX asset registered, keeping "
                "the Kindle-first lane one click away."
            ),
            "statuses": set(),
            "format": "KFX",
            "format_label": "Has KFX",
            "format_nav": "kfx",
            "collection_mode": False,
            "reset_endpoint": "books.format_kfx",
            "empty_title": "No books with KFX yet",
            "empty_message": (
                "Books with registered KFX assets will surface here."
            ),
        },
        "format_azw3": {
            "title": "Has AZW3",
            "description": (
                "Books that already carry a local AZW3 asset, ready for the "
                "second Kindle-preferred text lane."
            ),
            "statuses": set(),
            "format": "AZW3",
            "format_label": "Has AZW3",
            "format_nav": "azw3",
            "collection_mode": False,
            "reset_endpoint": "books.format_azw3",
            "empty_title": "No books with AZW3 yet",
            "empty_message": (
                "Books with registered AZW3 assets will surface here."
            ),
        },
        "format_epub": {
            "title": "Has EPUB",
            "description": (
                "Books that already have a local EPUB asset, the strongest "
                "browser-reading candidate in the current stack."
            ),
            "statuses": set(),
            "format": "EPUB",
            "format_label": "Has EPUB",
            "format_nav": "epub",
            "collection_mode": False,
            "reset_endpoint": "books.format_epub",
            "empty_title": "No books with EPUB yet",
            "empty_message": (
                "Books with registered EPUB assets will surface here."
            ),
        },
        "format_pdf": {
            "title": "Has PDF",
            "description": (
                "Books that already have a local PDF asset, whether that is a "
                "scanned fallback or one of several available text copies."
            ),
            "statuses": set(),
            "format": "PDF",
            "format_label": "Has PDF",
            "format_nav": "pdf",
            "collection_mode": False,
            "reset_endpoint": "books.format_pdf",
            "empty_title": "No books with PDF yet",
            "empty_message": (
                "Books with registered PDF assets will surface here."
            ),
        },
        "format_pdf_only": {
            "title": "PDF Only",
            "description": (
                "Books whose only registered text asset is PDF, useful for "
                "triaging scanned or last-priority reading copies."
            ),
            "statuses": set(),
            "format": "pdf_only",
            "format_label": "PDF only",
            "format_nav": "pdf_only",
            "collection_mode": False,
            "reset_endpoint": "books.format_pdf_only",
            "empty_title": "No PDF-only books right now",
            "empty_message": (
                "Books with PDF as their only registered text format will "
                "surface here."
            ),
        },
        "format_no_digital": {
            "title": "No Digital Format",
            "description": (
                "Books that still lack any registered local text asset, so the "
                "availability gap stays explicit."
            ),
            "statuses": set(),
            "format": "missing",
            "format_label": "No digital format",
            "format_nav": "missing",
            "collection_mode": False,
            "reset_endpoint": "books.format_no_digital",
            "empty_title": "No books are missing digital formats",
            "empty_message": (
                "Books without any registered KFX, AZW3, EPUB, or PDF asset "
                "will surface here."
            ),
        },
        "signal_highlights": {
            "title": "Has Highlights",
            "description": (
                "Books already linked to synced Book Quotes highlights, so the "
                "signal can be browsed at the book level."
            ),
            "highlights": "yes",
            "highlights_label": "Available",
            "signal_nav": "highlights",
            "reset_endpoint": "books.signal_highlights",
            "empty_title": "No books with synced highlights yet",
            "empty_message": (
                "Books will surface here after a Book Quotes refresh maps "
                "highlights back to DragonBookID."
            ),
        },
        "signal_quotes": {
            "title": "Has Quotes",
            "description": (
                "Books that already carry local notebook quotes, kept separate "
                "from the synced highlight feed."
            ),
            "quotes": "yes",
            "quotes_label": "Available",
            "signal_nav": "quotes",
            "reset_endpoint": "books.signal_quotes",
            "empty_title": "No books with local quotes yet",
            "empty_message": (
                "Books with manually saved quote rows will surface here."
            ),
        },
        "signal_notes": {
            "title": "Has Notes",
            "description": (
                "Books that already have personal notes, making the notebook "
                "signal one click away from the main library."
            ),
            "notes": "yes",
            "notes_label": "Available",
            "signal_nav": "notes",
            "reset_endpoint": "books.signal_notes",
            "empty_title": "No books with personal notes yet",
            "empty_message": (
                "Books with personal notes will surface here."
            ),
        },
    }[section]
    section_copy.setdefault("review", "")
    section_copy.setdefault("review_label", "")
    section_copy.setdefault("audiobook", "")
    section_copy.setdefault("audiobook_label", "")
    section_copy.setdefault("metadata", "")
    section_copy.setdefault("metadata_label", "")
    section_copy.setdefault("metadata_nav", "all")
    section_copy.setdefault("format", "")
    section_copy.setdefault("format_label", "")
    section_copy.setdefault("format_nav", "all")
    section_copy.setdefault("highlights", "")
    section_copy.setdefault("highlights_label", "")
    section_copy.setdefault("quotes", "")
    section_copy.setdefault("quotes_label", "")
    section_copy.setdefault("notes", "")
    section_copy.setdefault("notes_label", "")
    section_copy.setdefault("signal_nav", "all")
    section_copy.setdefault("statuses", set())
    section_copy.setdefault("status_label", "")
    section_copy.setdefault("collection_mode", False)
    forced_statuses: set[str] = set(section_copy["statuses"])
    forced_review = str(section_copy["review"] or "")
    forced_audiobook = str(section_copy["audiobook"] or "")
    forced_metadata = str(section_copy["metadata"] or "")
    forced_format = str(section_copy["format"] or "")
    forced_highlights = str(section_copy["highlights"] or "")
    forced_quotes = str(section_copy["quotes"] or "")
    forced_notes = str(section_copy["notes"] or "")
    repo_status = ""
    if len(forced_statuses) == 1:
        repo_status = next(iter(forced_statuses))
    elif not forced_statuses:
        repo_status = args["status"]
    repo_review = forced_review or args["review"]
    repo_audiobook = forced_audiobook or args["audiobook"]
    repo_metadata = forced_metadata or args["metadata"]
    repo_format = forced_format or args["format_filter"]
    repo_highlights = forced_highlights or args["highlights"]
    repo_quotes = forced_quotes or args["quotes"]
    repo_notes = forced_notes or args["notes"]
    books = BookRepository.list(
        q=args["q"],
        status=repo_status,
        format=repo_format,
        language=args["language"],
        metadata=repo_metadata,
        audiobook=repo_audiobook,
        author=args["author"],
        translator=args["translator"],
        highlights=repo_highlights,
        quotes=repo_quotes,
        notes=repo_notes,
        collection=args["collection"],
        review=repo_review,
    )
    if forced_statuses and len(forced_statuses) > 1:
        books = [book for book in books if book.status in forced_statuses]
    if forced_review:
        books = [book for book in books if book_item(book)["needs_review"]]
    collection_groups: list[dict[str, object]] = []
    if section_copy["collection_mode"]:
        collection_source = [
            book
            for book in BookRepository.list(
                q=args["q"],
                status=repo_status,
                format=repo_format,
                language=args["language"],
                metadata=repo_metadata,
                audiobook=repo_audiobook,
                author=args["author"],
                translator=args["translator"],
                highlights=repo_highlights,
                quotes=repo_quotes,
                notes=repo_notes,
                collection="",
                review=repo_review,
            )
            if any(str(value).strip() for value in book.collections)
        ]
        if not args["collection"]:
            books = collection_source
        collections_by_name: dict[str, list[object]] = {}
        for book in collection_source:
            for value in book.collections:
                name = str(value).strip()
                if not name:
                    continue
                collections_by_name.setdefault(name, []).append(book)
        collection_groups = _collection_groups(
            collections_by_name,
            query=args["q"],
            selected_collection=args["collection"],
        )
    highlight_counts = BookQuotesSnapshotService.book_highlight_counts(books)
    all_books = BookRepository.list()
    authors = sorted(
        {
            str(author).strip()
            for book in all_books
            for author in [*book.authors, *book.additional_authors]
            if str(author).strip()
        },
        key=str.casefold,
    )
    translators = sorted(
        {
            str(translator).strip()
            for book in all_books
            for translator in [
                book.translator,
                *[edition.translator for edition in book.editions],
            ]
            if str(translator).strip()
        },
        key=str.casefold,
    )
    collections = sorted(
        {
            str(collection).strip()
            for book in all_books
            for collection in book.collections
            if str(collection).strip()
        },
        key=str.casefold,
    )
    return {
        "active_module": "books",
        "books": [
            book_item(book, external_highlight_count=highlight_counts.get(book.id, 0))
            for book in books
        ],
        "library_sections": _books_navigation(
            "library"
            if section.startswith(("metadata_", "format_", "signal_"))
            else section
        ),
        "metadata_sections": _books_metadata_navigation(section_copy["metadata_nav"]),
        "format_sections": _books_format_navigation(section_copy["format_nav"]),
        "signal_sections": _books_signal_navigation(section_copy["signal_nav"]),
        "library_section": section,
        "page_title": section_copy["title"],
        "page_description": section_copy["description"],
        "reset_href": url_for(section_copy["reset_endpoint"]),
        "empty_title": section_copy["empty_title"],
        "empty_message": section_copy["empty_message"],
        "locked_status_label": section_copy["status_label"],
        "locked_review_label": section_copy["review_label"],
        "locked_audiobook_label": section_copy["audiobook_label"],
        "locked_metadata_label": section_copy["metadata_label"],
        "locked_format_label": section_copy["format_label"],
        "locked_highlights_label": section_copy["highlights_label"],
        "locked_quotes_label": section_copy["quotes_label"],
        "locked_notes_label": section_copy["notes_label"],
        "collection_groups": collection_groups,
        "q": args["q"],
        "status": next(iter(forced_statuses)) if len(forced_statuses) == 1 else args["status"],
        "format_filter": repo_format,
        "language": args["language"],
        "metadata": repo_metadata,
        "audiobook": repo_audiobook,
        "author": args["author"],
        "authors": authors,
        "translator": args["translator"],
        "translators": translators,
        "highlights": repo_highlights,
        "quotes": repo_quotes,
        "notes": repo_notes,
        "collection": args["collection"],
        "collections": collections,
        "review": forced_review or args["review"],
        "view": args["view"],
    }


def _collection_groups(
    collections_by_name: dict[str, list[object]],
    *,
    query: str = "",
    selected_collection: str = "",
) -> list[dict[str, object]]:
    params = {"q": query} if query else {}
    groups = [
        {
            "name": "All collections",
            "count": sum(len(books) for books in collections_by_name.values()),
            "preview": "",
            "href": url_for("books.collections", **params),
            "active": not selected_collection,
        }
    ]
    for name in sorted(collections_by_name, key=str.casefold):
        books = collections_by_name[name]
        groups.append(
            {
                "name": name,
                "count": len(books),
                "preview": ", ".join(book.title for book in books[:3]),
                "href": url_for("books.collections", collection=name, **params),
                "active": name.casefold() == str(selected_collection or "").casefold(),
            }
        )
    return groups


def _kindle_clippings_filter(value: str) -> str:
    selected = str(value or "all").strip().casefold()
    return selected if selected in KINDLE_CLIPPINGS_FILTERS else "all"


def _book_quotes_filter(value: str) -> str:
    selected = str(value or "all").strip().casefold()
    return selected if selected in BOOK_QUOTES_FILTERS else "all"


def _book_quotes_redirect(state_filter: str, *, query: str = ""):
    params = {}
    state_filter = _book_quotes_filter(state_filter)
    query = " ".join(str(query or "").split())
    if state_filter != "all":
        params["state"] = state_filter
    if query:
        params["q"] = query
    return redirect(url_for("knowledge_settings.book_quotes_review", **params))


def _kindle_clippings_matches_filter(projection, *, state_filter: str) -> bool:
    if state_filter == "all":
        return True
    if state_filter == "review":
        return projection.match.state in {"needs_review", "ambiguous"}
    if state_filter == "failed":
        return bool(projection.item.last_error)
    return projection.match.state == state_filter


def _kindle_clippings_redirect(state_filter: str):
    state_filter = _kindle_clippings_filter(state_filter)
    if state_filter == "all":
        return redirect(url_for("knowledge_settings.kindle_clippings"))
    return redirect(url_for("knowledge_settings.kindle_clippings", state=state_filter))


def _kindle_clippings_view(state, *, state_filter: str = "all"):
    books = BookRepository.list()
    pending = list(project_clippings_outbox(state, books))
    state_filter = _kindle_clippings_filter(state_filter)
    counts = {
        "all": len(pending),
        "matched": sum(1 for item in pending if item.match.state == "matched"),
        "ambiguous": sum(1 for item in pending if item.match.state == "ambiguous"),
        "needs_review": sum(1 for item in pending if item.match.state == "needs_review"),
        "failed": sum(1 for item in pending if item.item.last_error),
    }
    counts["review"] = counts["needs_review"] + counts["ambiguous"]
    latest_error = max(
        (item.item for item in pending if item.item.last_error),
        key=lambda item: item.last_error_at or "",
        default=None,
    )
    filtered_pending = [
        item
        for item in pending
        if _kindle_clippings_matches_filter(item, state_filter=state_filter)
    ]
    return {
        "pending_count": len(pending),
        "filtered_count": len(filtered_pending),
        "synced_count": len(state.synced_hashes),
        "attempt_count": sum(item.item.attempts for item in pending),
        "matched_count": counts["matched"],
        "ambiguous_count": counts["ambiguous"],
        "needs_review_count": counts["needs_review"],
        "review_count": counts["review"],
        "failed_count": counts["failed"],
        "last_error": latest_error.last_error if latest_error else "",
        "last_error_at": latest_error.last_error_at if latest_error else "",
        "active_filter": state_filter,
        "can_reset_failed": state_filter in KINDLE_CLIPPINGS_FAILURE_RESET_FILTERS
        and any(item.item.last_error for item in filtered_pending),
        "can_clear_filtered": state_filter in KINDLE_CLIPPINGS_BULK_CLEAR_FILTERS
        and bool(filtered_pending),
        "pending": filtered_pending,
        "filters": [
            {"key": "all", "label": "All", "count": counts["all"]},
            {"key": "review", "label": "Review", "count": counts["review"]},
            {"key": "matched", "label": "Matched", "count": counts["matched"]},
            {"key": "ambiguous", "label": "Ambiguous", "count": counts["ambiguous"]},
            {"key": "failed", "label": "Failed", "count": counts["failed"]},
        ],
        "book_options": [
            {
                "id": book.id,
                "title": book.title,
                "authors": ", ".join(book.authors),
            }
            for book in books
        ],
    }


@bp.get("")
@login_required
def index():
    return render_template("books/index.html", **_book_index_context(section="library"))


@bp.get("/reading")
@login_required
def reading():
    return render_template("books/index.html", **_book_index_context(section="reading"))


@bp.get("/finished")
@login_required
def finished():
    return render_template("books/index.html", **_book_index_context(section="finished"))


@bp.get("/wishlist")
@login_required
def wishlist():
    return render_template("books/index.html", **_book_index_context(section="wishlist"))


@bp.get("/paused")
@login_required
def paused():
    return render_template("books/index.html", **_book_index_context(section="paused"))


@bp.get("/dropped")
@login_required
def dropped():
    return render_template("books/index.html", **_book_index_context(section="dropped"))


@bp.get("/reference")
@login_required
def reference():
    return render_template(
        "books/index.html",
        **_book_index_context(section="reference"),
    )


@bp.get("/audiobooks")
@login_required
def audiobooks():
    return render_template(
        "books/index.html",
        **_book_index_context(section="audiobooks"),
    )


@bp.get("/collections")
@login_required
def collections():
    return render_template(
        "books/index.html",
        **_book_index_context(section="collections"),
    )


@bp.get("/metadata/inbox")
@login_required
def metadata_inbox():
    return render_template(
        "books/index.html",
        **_book_index_context(section="metadata_inbox"),
    )


@bp.get("/metadata/missing-isbn")
@login_required
def metadata_missing_isbn():
    return render_template(
        "books/index.html",
        **_book_index_context(section="metadata_missing_isbn"),
    )


@bp.get("/metadata/candidate-found")
@login_required
def metadata_candidate_found():
    return render_template(
        "books/index.html",
        **_book_index_context(section="metadata_candidate_found"),
    )


@bp.get("/metadata/needs-review")
@login_required
def metadata_needs_review():
    return render_template(
        "books/index.html",
        **_book_index_context(section="metadata_needs_review"),
    )


@bp.get("/metadata/verified")
@login_required
def metadata_verified():
    return render_template(
        "books/index.html",
        **_book_index_context(section="metadata_verified"),
    )


@bp.get("/metadata/no-isbn")
@login_required
def metadata_no_isbn():
    return render_template(
        "books/index.html",
        **_book_index_context(section="metadata_no_isbn"),
    )


@bp.get("/metadata/errors")
@login_required
def metadata_errors():
    return render_template(
        "books/index.html",
        **_book_index_context(section="metadata_errors"),
    )


@bp.get("/formats/kfx")
@login_required
def format_kfx():
    return render_template(
        "books/index.html",
        **_book_index_context(section="format_kfx"),
    )


@bp.get("/formats/azw3")
@login_required
def format_azw3():
    return render_template(
        "books/index.html",
        **_book_index_context(section="format_azw3"),
    )


@bp.get("/formats/epub")
@login_required
def format_epub():
    return render_template(
        "books/index.html",
        **_book_index_context(section="format_epub"),
    )


@bp.get("/formats/pdf")
@login_required
def format_pdf():
    return render_template(
        "books/index.html",
        **_book_index_context(section="format_pdf"),
    )


@bp.get("/formats/pdf-only")
@login_required
def format_pdf_only():
    return render_template(
        "books/index.html",
        **_book_index_context(section="format_pdf_only"),
    )


@bp.get("/formats/no-digital")
@login_required
def format_no_digital():
    return render_template(
        "books/index.html",
        **_book_index_context(section="format_no_digital"),
    )


@bp.get("/signals/highlights")
@login_required
def signal_highlights():
    return render_template(
        "books/index.html",
        **_book_index_context(section="signal_highlights"),
    )


@bp.get("/signals/quotes")
@login_required
def signal_quotes():
    return render_template(
        "books/index.html",
        **_book_index_context(section="signal_quotes"),
    )


@bp.get("/signals/notes")
@login_required
def signal_notes():
    return render_template(
        "books/index.html",
        **_book_index_context(section="signal_notes"),
    )


@bp.get("/needs-review")
@login_required
def needs_review():
    return render_template(
        "books/index.html",
        **_book_index_context(section="needs_review"),
    )


@bp.get("/highlights")
@login_required
def highlights():
    q = str(request.args.get("q") or "")
    book_id = str(request.args.get("book_id") or "")
    return render_template(
        "books/highlights.html",
        active_module="books",
        library_sections=_books_navigation("highlights"),
        highlights=BookQuotesSnapshotService.highlights_view(
            query=q,
            book_id=book_id,
        ),
    )


@bp.get("/quotes")
@login_required
def quotes():
    q = str(request.args.get("q") or "")
    book_id = str(request.args.get("book_id") or "")
    return render_template(
        "books/quotes.html",
        active_module="books",
        library_sections=_books_navigation("quotes"),
        quotes=quotes_view(query=q, book_id=book_id),
    )


@settings_bp.get("/diagnostics")
@login_required
def diagnostics():
    return render_template(
        "books/diagnostics.html",
        active_module="more",
        diagnostics=KnowledgeDiagnosticsService.snapshot(),
        metadata_sections=_books_metadata_navigation("all"),
        format_sections=_books_format_navigation("all"),
        signal_sections=_books_signal_navigation("all"),
    )


@settings_bp.get("/book-quotes")
@login_required
def book_quotes_review():
    state_filter = _book_quotes_filter(str(request.args.get("state") or "all"))
    query = str(request.args.get("q") or "")
    return render_template(
        "books/book_quotes.html",
        active_module="more",
        book_quotes=BookQuotesSnapshotService.review_view(
            state_filter=state_filter,
            query=query,
        ),
    )


@settings_bp.post("/book-quotes/refresh")
@login_required
def refresh_book_quotes():
    result = BookQuotesSnapshotService.refresh()
    if result.refreshed:
        flash(
            f"Refreshed {result.fetched} Book Quotes row"
            f"{'s' if result.fetched != 1 else ''} into the local snapshot.",
            "success",
        )
        if result.matched:
            flash(
                f"Matched {result.matched} refreshed highlight"
                f"{'s' if result.matched != 1 else ''} to local books.",
                "info",
            )
        pending_review = result.needs_review + result.ambiguous
        if pending_review:
            flash(
                f"{pending_review} refreshed highlight"
                f"{'s' if pending_review != 1 else ''} still need local review.",
                "warning",
            )
    else:
        flash(result.snapshot.last_error or "Book Quotes refresh needs review.", "warning")
    return redirect(url_for("knowledge_settings.diagnostics"))


@settings_bp.post("/book-quotes/<item_key>/assign-book")
@login_required
def assign_book_quote_book(item_key: str):
    state_filter = _book_quotes_filter(str(request.form.get("state") or "all"))
    query = str(request.form.get("q") or "")
    book = BookRepository.get(str(request.form.get("book_id") or ""))
    if book is None:
        flash("Choose a valid local book before saving the Book Quotes match.", "error")
        return _book_quotes_redirect(state_filter, query=query)
    result = BookQuotesSnapshotService.store().assign_book(item_key, book)
    if result.updated:
        flash("Book Quotes match saved locally.", "success")
    else:
        flash("Book Quotes row was not found in the local snapshot.", "warning")
    return _book_quotes_redirect(state_filter, query=query)


@settings_bp.post("/book-quotes/<item_key>/clear-match")
@login_required
def clear_book_quote_match(item_key: str):
    state_filter = _book_quotes_filter(str(request.form.get("state") or "all"))
    query = str(request.form.get("q") or "")
    result = BookQuotesSnapshotService.store().clear_local_match(item_key)
    if result.cleared:
        flash("Book Quotes local match cleared.", "success")
    else:
        flash("No manual local Book Quotes match was stored for that row.", "warning")
    return _book_quotes_redirect(state_filter, query=query)


@settings_bp.get("/kindle-clippings")
@login_required
def kindle_clippings():
    state_filter = _kindle_clippings_filter(str(request.args.get("state") or "all"))
    return render_template(
        "books/kindle_clippings.html",
        active_module="more",
        outbox=_kindle_clippings_view(
            _kindle_clippings_store().load(),
            state_filter=state_filter,
        ),
        sync_readiness=_kindle_sync_credential_store().status(),
    )


@settings_bp.post("/kindle-clippings/queue")
@login_required
def queue_kindle_clippings():
    result = _kindle_clippings_store().queue_raw(str(request.form.get("raw_text") or ""))
    state_filter = _kindle_clippings_filter(str(request.form.get("state") or "all"))
    skipped = (
        result.skipped_malformed
        + result.skipped_synced
        + result.skipped_pending
        + result.skipped_duplicate
    )
    if result.queued:
        flash(
            f"Queued {len(result.queued)} Kindle clipping"
            f"{'s' if len(result.queued) != 1 else ''}.",
            "success",
        )
    else:
        flash("No new Kindle clippings queued.", "warning")
    if skipped:
        flash(f"Skipped {skipped} already-known or malformed item(s).", "info")
    return _kindle_clippings_redirect(state_filter)


@settings_bp.post("/kindle-clippings/<unique_hash>/assign-book")
@login_required
def assign_kindle_clipping_book(unique_hash: str):
    state_filter = _kindle_clippings_filter(str(request.form.get("state") or "all"))
    book = BookRepository.get(str(request.form.get("book_id") or ""))
    if book is None:
        flash("Choose a valid local book before saving the clipping match.", "error")
        return _kindle_clippings_redirect(state_filter)
    result = _kindle_clippings_store().assign_book(unique_hash, book)
    if result.updated:
        flash("Kindle clipping match saved locally.", "success")
    else:
        flash("Kindle clipping was not found in the local outbox.", "warning")
    return _kindle_clippings_redirect(state_filter)


@settings_bp.post("/kindle-clippings/<unique_hash>/remove")
@login_required
def remove_kindle_clipping(unique_hash: str):
    state_filter = _kindle_clippings_filter(str(request.form.get("state") or "all"))
    result = _kindle_clippings_store().remove(unique_hash)
    if result.removed:
        flash("Kindle clipping removed from the local outbox.", "success")
    else:
        flash("Kindle clipping was not found in the local outbox.", "warning")
    return _kindle_clippings_redirect(state_filter)


@settings_bp.post("/kindle-clippings/clear")
@login_required
def clear_kindle_clippings():
    state_filter = _kindle_clippings_filter(str(request.form.get("state") or "all"))
    if state_filter not in KINDLE_CLIPPINGS_BULK_CLEAR_FILTERS:
        flash("Bulk clear is only available for matched or failed outbox filters.", "warning")
        return _kindle_clippings_redirect(state_filter)
    store = _kindle_clippings_store()
    state = store.load()
    hashes = [
        projection.item.unique_hash
        for projection in project_clippings_outbox(state, BookRepository.list())
        if _kindle_clippings_matches_filter(projection, state_filter=state_filter)
    ]
    result = store.remove_many(hashes)
    if result.removed:
        flash(
            f"Cleared {result.removed} {state_filter} Kindle clipping"
            f"{'s' if result.removed != 1 else ''} from the local outbox.",
            "success",
        )
    else:
        flash("No Kindle clippings matched this bulk clear action.", "warning")
    return _kindle_clippings_redirect(state_filter)


@settings_bp.post("/kindle-clippings/reset-failures")
@login_required
def reset_kindle_clipping_failures():
    state_filter = _kindle_clippings_filter(str(request.form.get("state") or "all"))
    if state_filter not in KINDLE_CLIPPINGS_FAILURE_RESET_FILTERS:
        flash("Failure reset is only available for failed outbox filters.", "warning")
        return _kindle_clippings_redirect(state_filter)
    store = _kindle_clippings_store()
    state = store.load()
    hashes = [
        projection.item.unique_hash
        for projection in project_clippings_outbox(state, BookRepository.list())
        if projection.item.last_error
    ]
    result = store.reset_failures(hashes)
    if result.reset:
        flash(
            f"Reset {result.reset} failed Kindle clipping"
            f"{'s' if result.reset != 1 else ''} for a future retry.",
            "success",
        )
    else:
        flash("No failed Kindle clippings were ready to reset.", "warning")
    return _kindle_clippings_redirect(state_filter)


@settings_bp.post("/kindle-clippings/clear-credentials")
@login_required
def clear_kindle_clipping_credentials():
    result = _kindle_sync_credential_store().clear()
    if result.cleared:
        flash("Cleared local Kindle sync credentials.", "success")
    else:
        flash("No local Kindle sync credentials were stored.", "warning")
    return _kindle_clippings_redirect(
        _kindle_clippings_filter(str(request.form.get("state") or "all"))
    )


@settings_bp.post("/kindle-clippings/validate-credentials")
@login_required
def validate_kindle_clipping_credentials():
    result = _kindle_sync_credential_store().validate()
    if result.validated:
        flash("Validated local Kindle sync credentials against Book Quotes.", "success")
    else:
        flash(
            result.status.note or "Local Kindle sync credentials still need review.",
            "warning",
        )
    return _kindle_clippings_redirect(
        _kindle_clippings_filter(str(request.form.get("state") or "all"))
    )


@settings_bp.post("/kindle-clippings/sync")
@login_required
def sync_kindle_clippings():
    state_filter = _kindle_clippings_filter(str(request.form.get("state") or "all"))
    store = _kindle_clippings_store()
    state = store.load()
    if not state.pending:
        flash("No pending Kindle clippings were ready to sync.", "warning")
        return _kindle_clippings_redirect(state_filter)
    result = _kindle_sync_credential_store().sync_pending(state)
    store.save(result.state)
    if result.uploaded:
        flash(
            f"Uploaded {result.uploaded} Kindle clipping"
            f"{'s' if result.uploaded != 1 else ''} to Book Quotes.",
            "success",
        )
    if result.skipped_existing:
        flash(
            f"Skipped {result.skipped_existing} Kindle clipping"
            f"{'s' if result.skipped_existing != 1 else ''} already in Book Quotes.",
            "info",
        )
    if result.failed:
        flash(
            f"{result.failed} Kindle clipping"
            f"{'s' if result.failed != 1 else ''} stayed in the local outbox for retry.",
            "warning",
        )
    return _kindle_clippings_redirect(state_filter)


@bp.get("/<book_id>")
@login_required
def detail(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    return render_template(
        "books/detail.html",
        active_module="books",
        book=book_detail(
            book,
            external_highlights=BookQuotesSnapshotService.book_highlights(book),
            book_quotes_status=BookQuotesSnapshotService.status(),
        ),
    )


@bp.post("/<book_id>/progress")
@login_required
def progress(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookService.save_progress(
            book,
            status=str(request.form.get("status") or ""),
            current_page=int(request.form.get("current_page") or 0),
        )
    except (TypeError, ValueError) as exc:
        flash(str(exc), "error")
    else:
        flash("Book progress updated.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/kindle-aliases")
@login_required
def add_kindle_alias(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookService.add_kindle_title_alias(
            book,
            alias=str(request.form.get("alias") or ""),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Kindle title alias saved.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/kindle-aliases/remove")
@login_required
def remove_kindle_alias(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookService.remove_kindle_title_alias(
            book,
            alias=str(request.form.get("alias") or ""),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Kindle title alias removed.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/metadata-preview")
@login_required
def metadata_preview(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    proposal = BookMetadataService.preview(book, providers=_metadata_providers())
    if proposal is None:
        BookMetadataService.clear_preview(book)
        flash("No metadata candidate found.", "warning")
    else:
        BookMetadataService.store_preview(book, proposal)
        flash("Metadata candidate ready for review.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/metadata-apply")
@login_required
def metadata_apply(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookMetadataService.apply_stored_preview(book)
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Metadata fill applied. Conflicts were left unchanged.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/assets/preview")
@login_required
def asset_preview(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        preview = BookAssetService.preview_text_asset(
            book,
            local_path=str(request.form.get("local_path") or ""),
            edition_id=str(request.form.get("edition_id") or ""),
        )
        BookAssetService.store_text_asset_preview(book, preview)
    except (OSError, LocalAssetError) as exc:
        BookAssetService.clear_text_asset_preview(book)
        flash(str(exc), "error")
    else:
        flash("Local asset ready for review.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/assets/register")
@login_required
def asset_register(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        asset = BookAssetService.register_stored_text_asset(book)
    except (OSError, LocalAssetError) as exc:
        flash(str(exc), "error")
    else:
        flash(f"{asset.format} asset registered.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/audiobooks/assets/preview")
@login_required
def audiobook_asset_preview(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        preview = BookAssetService.preview_audio_asset(
            book,
            local_path=str(request.form.get("local_path") or ""),
            audiobook_id=str(request.form.get("audiobook_id") or ""),
        )
        BookAssetService.store_audio_asset_preview(book, preview)
    except (OSError, LocalAssetError) as exc:
        BookAssetService.clear_audio_asset_preview(book)
        flash(str(exc), "error")
    else:
        flash("Audiobook asset ready for review.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/audiobooks/assets/register")
@login_required
def audiobook_asset_register(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        asset = BookAssetService.register_stored_audio_asset(book)
    except (OSError, LocalAssetError) as exc:
        flash(str(exc), "error")
    else:
        flash(f"{asset.format} audiobook asset registered.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/availability-candidates")
@login_required
def add_availability_candidate(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookAvailabilityService.add_candidate(
            book,
            provider=str(request.form.get("provider") or ""),
            title=str(request.form.get("title") or ""),
            format_guess=str(request.form.get("format_guess") or ""),
            language_guess=str(request.form.get("language_guess") or ""),
            source_reference=str(request.form.get("source_reference") or ""),
        )
    except AvailabilityCandidateError as exc:
        flash(str(exc), "error")
    else:
        flash("Availability candidate saved for review.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/availability-candidates/parse")
@login_required
def parse_availability_candidate(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookAvailabilityService.add_candidate_from_text(
            book,
            provider=str(request.form.get("provider") or ""),
            raw_text=str(request.form.get("raw_text") or ""),
        )
    except AvailabilityCandidateError as exc:
        flash(str(exc), "error")
    else:
        flash("Availability candidate parsed for review.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/availability-candidates/jackett-search")
@login_required
def search_jackett_availability_candidates(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        results = []
        for provider in _availability_providers():
            results.extend(provider.search(book, limit=12))
        created, skipped = BookAvailabilityService.add_provider_results(book, results)
    except (AvailabilityCandidateError, AvailabilityProviderError) as exc:
        flash(str(exc), "error")
    else:
        if created:
            duplicate_note = f" {skipped} duplicate skipped." if skipped else ""
            flash(
                f"Jackett search added {created} candidate{'s' if created != 1 else ''} for review."
                f"{duplicate_note}",
                "success",
            )
        elif skipped:
            flash("Jackett search found only candidates already in review.", "warning")
        else:
            flash("No Jackett book candidates found.", "warning")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/availability-candidates/<candidate_id>/confirm")
@login_required
def confirm_availability_candidate(book_id: str, candidate_id: str):
    return _availability_review(book_id, candidate_id, review_state="confirmed")


@bp.post("/<book_id>/availability-candidates/<candidate_id>/reject")
@login_required
def reject_availability_candidate(book_id: str, candidate_id: str):
    return _availability_review(book_id, candidate_id, review_state="rejected")


def _availability_review(book_id: str, candidate_id: str, *, review_state: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookAvailabilityService.set_review_state(
            book, candidate_id=candidate_id, review_state=review_state
        )
    except AvailabilityCandidateError as exc:
        flash(str(exc), "error")
    else:
        flash(f"Availability candidate {review_state}.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.get("/<book_id>/assets/<asset_id>/stream")
@login_required
def text_asset_stream(book_id: str, asset_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        path, mimetype, asset = BookTextRuntimeService.stream_target(book, asset_id=asset_id)
    except (OSError, TextRuntimeError):
        abort(404)
    return send_file(
        path,
        mimetype=mimetype,
        conditional=True,
        as_attachment=asset.format.upper() != "PDF",
        download_name=asset.filename or path.name,
    )


@bp.get("/<book_id>/kindle-export")
@login_required
def kindle_export(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    return render_template(
        "books/kindle_export.html",
        active_module="books",
        export=BookKindleExportService.export_view(book),
    )


@bp.get("/<book_id>/kindle-export/manifest.json")
@login_required
def kindle_export_manifest(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    return jsonify(BookKindleExportService.manifest(book))


@bp.get("/<book_id>/assets/<asset_id>/reader")
@login_required
def text_asset_reader(book_id: str, asset_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        reader = BookTextRuntimeService.epub_reader(book, asset_id=asset_id)
    except (OSError, TextRuntimeError):
        abort(404)
    return render_template(
        "books/reader.html",
        active_module="books",
        reader=reader,
    )


@bp.post("/<book_id>/assets/<asset_id>/reader-progress")
@login_required
def text_asset_reader_progress(book_id: str, asset_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    payload = request.get_json(silent=True) or request.form
    try:
        progress = BookTextRuntimeService.save_progress(
            book,
            asset_id=asset_id,
            chapter_index=int(float(payload.get("chapter_index") or 0)),
            scroll_percent=float(payload.get("scroll_percent") or 0),
        )
    except (TypeError, ValueError, TextRuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"progress": progress})


@bp.get("/<book_id>/audiobooks/assets/<asset_id>/stream")
@login_required
def audiobook_asset_stream(book_id: str, asset_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        path, mimetype, _asset = BookAudioRuntimeService.stream_target(
            book, asset_id=asset_id
        )
    except (OSError, AudioRuntimeError):
        abort(404)
    return send_file(path, mimetype=mimetype, conditional=True)


@bp.post("/<book_id>/audiobooks/<audiobook_id>/progress")
@login_required
def audiobook_progress(book_id: str, audiobook_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    payload = request.get_json(silent=True) or request.form
    try:
        progress = BookAudioRuntimeService.save_progress(
            book,
            audiobook_id=audiobook_id,
            position_seconds=int(float(payload.get("position_seconds") or 0)),
            duration_seconds=int(float(payload.get("duration_seconds") or 0)),
            current_chapter=int(float(payload.get("current_chapter") or 0)),
            playback_speed=float(payload.get("playback_speed") or 1),
            completed=str(payload.get("completed") or "").casefold()
            in {"1", "true", "yes", "on"},
        )
    except (TypeError, ValueError, AudioRuntimeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"progress": progress})


@bp.post("/<book_id>/audiobooks/candidates")
@login_required
def add_audiobook_candidate(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookAudiobookService.add_candidate(
            book,
            title=str(request.form.get("title") or ""),
            language=str(request.form.get("language") or ""),
            narrator=str(request.form.get("narrator") or ""),
            publisher=str(request.form.get("publisher") or ""),
            release_year=str(request.form.get("release_year") or ""),
            duration_minutes=str(request.form.get("duration_minutes") or ""),
            chapter_count=str(request.form.get("chapter_count") or ""),
            abridgement_type=str(request.form.get("abridgement_type") or ""),
            production_type=str(request.form.get("production_type") or ""),
        )
    except AudiobookCandidateError as exc:
        flash(str(exc), "error")
    else:
        flash("Audiobook candidate saved for review.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/audiobooks/<audiobook_id>/confirm")
@login_required
def confirm_audiobook_candidate(book_id: str, audiobook_id: str):
    return _audiobook_review(book_id, audiobook_id, review_state="verified")


@bp.post("/<book_id>/audiobooks/<audiobook_id>/reject")
@login_required
def reject_audiobook_candidate(book_id: str, audiobook_id: str):
    return _audiobook_review(book_id, audiobook_id, review_state="rejected")


def _audiobook_review(book_id: str, audiobook_id: str, *, review_state: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    try:
        BookAudiobookService.set_review_state(
            book, audiobook_id=audiobook_id, review_state=review_state
        )
    except AudiobookCandidateError as exc:
        flash(str(exc), "error")
    else:
        label = "confirmed" if review_state == "verified" else review_state
        flash(f"Audiobook candidate {label}.", "success")
    return redirect(url_for("books.detail", book_id=book.id))


@bp.post("/<book_id>/quotes")
@login_required
def add_quote(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    raw_page = str(request.form.get("page") or "").strip()
    try:
        BookService.add_quote(
            book,
            text=str(request.form.get("text") or ""),
            page=int(raw_page) if raw_page else None,
            note=str(request.form.get("note") or ""),
        )
    except ValueError as exc:
        flash(str(exc), "error")
    else:
        flash("Quote added.", "success")
    return redirect(url_for("books.detail", book_id=book.id))
