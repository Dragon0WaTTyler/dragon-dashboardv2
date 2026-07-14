from app.extensions import db
from app.shared.models import Operation
from app.shared.operations import OperationService


def test_operation_service_records_safe_success(app):
    with app.app_context():
        operation = OperationService.start(kind="refresh", domain="reading")
        OperationService.complete(operation, counts={"created": 3})
        saved = OperationService.get(operation.id)

        assert saved is not None
        assert saved.status == "completed"
        assert saved.counts == {"created": 3}
        assert saved.completed_at is not None


def test_operation_service_redacts_failure_details(app):
    with app.app_context():
        operation = OperationService.start(kind="sync", domain="youtube")
        OperationService.fail(
            operation,
            r"Proxy failed at C:\private\oauth.json token=do-not-leak",
        )
        saved = db.session.get(Operation, operation.id)

        assert saved.status == "failed"
        assert "do-not-leak" not in saved.safe_error
        assert "C:\\private" not in saved.safe_error
        assert "[redacted]" in saved.safe_error
