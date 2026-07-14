from __future__ import annotations

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from app.books.repositories import BookRepository
from app.books.services import BookService, book_detail, book_item

bp = Blueprint("books", __name__, url_prefix="/books")


@bp.get("")
@login_required
def index():
    q = str(request.args.get("q") or "")
    status = str(request.args.get("status") or "")
    view = str(request.args.get("view") or "grid")
    if view not in {"grid", "list"}:
        view = "grid"
    books = BookRepository.list(q=q, status=status)
    return render_template(
        "books/index.html",
        active_module="books",
        books=[book_item(book) for book in books],
        q=q,
        status=status,
        view=view,
    )


@bp.get("/<book_id>")
@login_required
def detail(book_id: str):
    book = BookRepository.get(book_id)
    if book is None:
        abort(404)
    return render_template(
        "books/detail.html", active_module="books", book=book_detail(book)
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
