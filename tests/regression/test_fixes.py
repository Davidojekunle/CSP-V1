"""
Regression tests for bugs found while hardening the async migration.
Each test names the behaviour it protects; response shapes are the frontend contract.
"""
import hashlib
import hmac
import io
import json
from datetime import date

from sqlmodel import select

from app.core.config import normalize_async_database_url, to_sync_database_url, Settings
from app.models import (
    ClassSubject, FormTeacherRemark, Invoice, InvoiceStatus, Payment, PaymentStatus, Result, StudentProfile, User,
)
from tests.conftest import PASSWORD, auth_header


# --- Authentication -----------------------------------------------------------

def test_login_rejects_wrong_password(client, test_admin):
    r = client.post("/auth/token", data={"username": test_admin.email, "password": "not-the-password"})
    assert r.status_code == 401
    assert r.json() == {"detail": "Incorrect username/email or password"}


def test_login_accepts_username_or_email(client, test_admin):
    for identifier in (test_admin.email, test_admin.username):
        assert client.post("/auth/token", data={"username": identifier, "password": PASSWORD}).status_code == 200


def test_change_password_rejects_wrong_old_password(client, test_admin, session):
    before = test_admin.password_hash
    r = client.post("/auth/change-password", headers=auth_header(test_admin),
                    json={"old_password": "wrong", "new_password": "newpass123"})
    assert r.status_code == 400
    assert r.json() == {"detail": "Incorrect old password"}
    session.expire_all()
    assert session.get(User, test_admin.id).password_hash == before


# --- Writes that used to report success without saving ---------------------------

def test_bulk_results_are_persisted(client, school, session):
    s = school
    student = s["students"][0]
    r = client.post("/results/bulk", headers=auth_header(s["teacher"]), json={
        "session_id": s["session"].id, "term_id": s["term"].id, "class_id": s["class_a"].id,
        "subject_id": s["subject"].id, "results": [{"student_id": student.id, "ca1": 10, "ca2": 15, "exam": 50}],
    })
    assert r.status_code == 201
    assert r.json()["created"] == 1
    row = session.exec(select(Result).where(Result.student_id == student.id)).first()
    assert (row.ca1, row.ca2, row.exam, row.total) == (10, 15, 50, 75)


def test_delete_class_subject_is_persisted(client, school, session):
    assignment = session.exec(select(ClassSubject)).first()
    r = client.delete(f"/admin/academic/class-subjects/{assignment.id}", headers=auth_header(school["admin"]))
    assert r.status_code == 204
    session.expunge_all()
    assert session.exec(select(ClassSubject).where(ClassSubject.id == assignment.id)).first() is None


def _assign_school_fee(client, s):
    fee = client.post("/fees/admin/fees", headers=auth_header(s["admin"]),
                      json={"name": "Tuition", "amount": 5000, "frequency": "term"}).json()
    r = client.post("/fees/admin/fee-assignments", headers=auth_header(s["admin"]), json={
        "fee_id": fee["id"], "session_id": s["session"].id, "term_id": s["term"].id, "target_type": "SCHOOL"})
    assert r.status_code == 201
    return fee


def test_generate_invoices_persists_and_is_idempotent(client, school, session):
    s = school
    _assign_school_fee(client, s)
    body = {"due_date": "2099-01-31", "scope": "school", "session_id": s["session"].id, "term_id": s["term"].id}
    first = client.post("/fees/admin/generate-invoices", headers=auth_header(s["admin"]), json=body)
    assert first.json() == {"message": "Process complete. Created: 2, Updated: 0."}
    again = client.post("/fees/admin/generate-invoices", headers=auth_header(s["admin"]), json=body)
    assert again.json() == {"message": "Process complete. Created: 0, Updated: 0."}
    assert len(session.exec(select(Invoice)).all()) == 2


# --- Results publishing -------------------------------------------------------

def test_unpublish_message_contains_only_the_count(client, school, session):
    s = school
    session.add(Result(student_id=s["students"][0].id, class_id=s["class_a"].id, subject_id=s["subject"].id,
                       session_id=s["session"].id, term_id=s["term"].id, total=60, is_published=True))
    session.commit()
    r = client.put(f"/results/results/unpublish?session_id={s['session'].id}&term_id={s['term'].id}",
                   headers=auth_header(s["admin"]))
    assert r.status_code == 200
    assert r.json() == {"message": "Unpublished 1 results successfully"}
    assert "password" not in r.text


def test_publish_then_already_published(client, school, session):
    s = school
    session.add(Result(student_id=s["students"][0].id, class_id=s["class_a"].id, subject_id=s["subject"].id,
                       session_id=s["session"].id, term_id=s["term"].id, total=60))
    session.commit()
    url = f"/results/results/publish?session_id={s['session'].id}&term_id={s['term'].id}"
    assert client.put(url, headers=auth_header(s["admin"])).json() == {"message": "Published 1 results successfully"}
    again = client.put(url, headers=auth_header(s["admin"]))
    assert again.status_code == 400 and again.json() == {"detail": "Results are already published"}


# --- Teacher with more than one form class ---------------------------------------

def test_form_teacher_with_two_classes(client, school, session):
    s = school
    headers = auth_header(s["teacher"])
    overview = client.get("/staff/my-form-class/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["class_name"] == "JSS1 A"
    # A student in the *second* form class can still get behavioural traits
    r = client.post("/behavioral-traits/", headers=headers, json={"student_id": s["students"][1].id, "affective_domain_remarks": "ok"})
    assert r.status_code == 201
    remarks = client.post("/results/remarks/form-teacher/bulk", headers=headers, json={
        "session_id": s["session"].id, "term_id": s["term"].id, "class_id": s["class_b"].id,
        "remarks": [{"student_id": s["students"][1].id, "remark": "Excellent conduct and a positive attitude towards learning."}]})
    assert remarks.status_code == 201
    assert session.exec(select(FormTeacherRemark)).first().student_id == s["students"][1].id


# --- Payments ----------------------------------------------------------------

def _invoice(session, s, amount=5000.0):
    inv = Invoice(invoice_number=f"INV-T-{amount}", student_id=s["students"][0].id, session_id=s["session"].id,
                  term_id=s["term"].id, status=InvoiceStatus.issued, due_date=date(2099, 1, 1),
                  total_amount=amount, balance_due=amount)
    session.add(inv)
    session.commit()
    return inv


def test_pay_endpoint_body_is_optional_and_returns_paystack_shape(client, school, session, monkeypatch):
    s = school
    inv = _invoice(session, s)
    calls = {}

    async def fake_initialize(email, amount, reference, callback_url, metadata):
        calls.update(amount=amount, reference=reference)
        return {"status": True, "message": "Authorization URL created",
                "data": {"authorization_url": "https://checkout.paystack.com/x", "access_code": "x", "reference": reference}}

    from app.services.payment.paystack import paystack_service
    monkeypatch.setattr(paystack_service, "initialize_transaction", fake_initialize)

    r = client.post(f"/fees/student/pay/{inv.id}", headers=auth_header(s["students"][0]))  # no body
    assert r.status_code == 200
    body = r.json()
    assert body["status"] is True
    assert body["data"]["authorization_url"] == "https://checkout.paystack.com/x"
    assert "payment_id" in body
    assert calls["amount"] == 5000.0


def test_pay_endpoint_partial_amount_and_flat_fields_for_dashboard(client, school, session, monkeypatch):
    """The dashboard sends {amount, callback_url} and reads authorization_url at the top level."""
    s = school
    inv = _invoice(session, s)
    calls = {}

    async def fake_initialize(email, amount, reference, callback_url, metadata):
        calls.update(amount=amount, callback_url=callback_url)
        return {"status": True, "message": "ok",
                "data": {"authorization_url": "https://checkout.paystack.com/y", "access_code": "ac", "reference": reference}}

    from app.services.payment.paystack import paystack_service
    monkeypatch.setattr(paystack_service, "initialize_transaction", fake_initialize)

    r = client.post(f"/fees/student/pay/{inv.id}", headers=auth_header(s["students"][0]),
                    json={"invoice_id": inv.id, "amount": 1500, "callback_url": "https://app.example/cb"})
    body = r.json()
    assert r.status_code == 200
    assert body["authorization_url"] == "https://checkout.paystack.com/y"
    assert body["access_code"] == "ac" and body["reference"].startswith("PAY_")
    assert calls == {"amount": 1500, "callback_url": "https://app.example/cb"}


def test_manual_payment_updates_invoice(client, school, session):
    s = school
    inv = _invoice(session, s)
    r = client.post("/fees/admin/manual-payment", headers=auth_header(s["admin"]),
                    json={"invoice_id": inv.id, "amount": 2000, "payment_method": "cash"})
    assert r.status_code == 200
    assert r.json()["message"] == "Manual payment recorded successfully"
    session.expire_all()
    inv = session.get(Invoice, inv.id)
    assert (inv.paid_amount, inv.balance_due, inv.status) == (2000, 3000, InvoiceStatus.partial)


def test_manual_payment_unknown_invoice_is_404(client, school):
    r = client.post("/fees/admin/manual-payment", headers=auth_header(school["admin"]),
                    json={"invoice_id": "missing", "amount": 1, "payment_method": "cash"})
    assert r.status_code == 404


def test_webhook_rejects_missing_signature(client):
    r = client.post("/fees/webhooks/paystack", content=b'{"event": "charge.success"}')
    assert r.status_code == 400


def test_webhook_marks_payment_successful_after_verification(client, school, session, monkeypatch, db_path):
    s = school
    inv = _invoice(session, s)
    payment = Payment(invoice_id=inv.id, paystack_reference="PAY_TEST_1", amount=5000, status=PaymentStatus.pending)
    session.add(payment)
    session.commit()

    # The webhook task opens its own session: point the app's factory at the test DB
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    from app.services import payment_service
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", poolclass=NullPool)
    monkeypatch.setattr(payment_service, "AsyncSessionFactory", async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))

    async def fake_verify(reference):
        return {"status": True, "data": {"status": "success", "amount": 500000, "channel": "card", "reference": reference}}

    from app.services.payment.paystack import paystack_service
    monkeypatch.setattr(paystack_service, "verify_transaction", fake_verify)

    body = json.dumps({"event": "charge.success", "data": {"reference": "PAY_TEST_1"}}).encode()
    sig = hmac.new(b"sk_test_dummy", body, hashlib.sha512).hexdigest()
    r = client.post("/fees/webhooks/paystack", content=body, headers={"x-paystack-signature": sig})
    assert r.json() == {"status": "success"}

    session.expire_all()
    assert session.get(Payment, payment.id).status == PaymentStatus.successful
    inv = session.get(Invoice, inv.id)
    assert (inv.status, inv.balance_due) == (InvoiceStatus.paid, 0.0)


def test_payments_filters_are_applied(client, school, session):
    s = school
    inv = _invoice(session, s)
    client.post("/fees/admin/manual-payment", headers=auth_header(s["admin"]),
                json={"invoice_id": inv.id, "amount": 100, "payment_method": "cash"})
    h = auth_header(s["admin"])
    assert len(client.get("/fees/admin/payments?search=MANUAL", headers=h).json()) == 1
    assert client.get("/fees/admin/payments?search=nomatch", headers=h).json() == []
    assert client.get("/fees/admin/payments?date_from=2099-01-01", headers=h).json() == []


# --- Enrollment -----------------------------------------------------------------

def test_bulk_enroll_partial_success_returns_207_detail(client, school, session):
    s = school
    r = client.post("/admin/enrollment/bulk", headers=auth_header(s["admin"]), json={
        "class_id": s["class_a"].id, "session_id": s["session"].id, "term_id": s["term"].id,
        "student_ids": [s["students"][0].id]})  # already actively enrolled
    assert r.status_code == 207
    assert r.json()["detail"]["error_count"] == 1


def test_bulk_class_update(client, school, session):
    s = school
    student = s["students"][0]
    r = client.post("/admin/enrollment/bulk-class-update", headers=auth_header(s["admin"]), json={
        "session_id": s["session"].id, "term_id": s["term"].id,
        "student_class_mappings": [{"student_id": student.id, "new_class_id": s["class_b"].id}]})
    assert r.status_code == 200
    assert r.json()[0]["class_name"] == "SS2 A"
    session.expire_all()
    assert session.get(StudentProfile, student.id).current_class_id == s["class_b"].id


# --- Bulk upload ---------------------------------------------------------------

def test_bulk_upload_keeps_leading_zeros_and_blank_password(client, school, session):
    csv = ("first_name,last_name,email,phone,gender,date_of_birth,enrollment_date,guardian_name,guardian_phone,guardian_email,password\n"
           "Ada,Csv,ada.csv@example.com,08011112222,female,2011-02-03,2025-09-01,Mr Csv,08033334444,g.csv@example.com,\n")
    r = client.post("/admin/users/bulk-upload/students", headers=auth_header(school["admin"]),
                    files={"file": ("s.csv", io.BytesIO(csv.encode()), "text/csv")})
    assert r.json()["success_count"] == 1
    user = session.exec(select(User).where(User.email == "ada.csv@example.com")).first()
    assert user.phone == "08011112222"
    # A blank password cell must not become the literal password "nan"
    login = client.post("/auth/token", data={"username": "ada.csv@example.com", "password": "nan"})
    assert login.status_code == 401


# --- Configuration ---------------------------------------------------------------

def test_database_url_normalization():
    assert normalize_async_database_url("postgres://u:p@h:5432/db") == "postgresql+asyncpg://u:p@h:5432/db"
    assert normalize_async_database_url("postgresql://u:p@h:6543/db?sslmode=require") == "postgresql+asyncpg://u:p@h:6543/db"
    assert to_sync_database_url("postgresql+asyncpg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_async_database_url("sqlite:///x.db") == "sqlite+aiosqlite:///x.db"


def test_supabase_ssl_and_pooler_detection():
    s = Settings(SECRET_KEY="x", DATABASE_URL="postgresql://postgres.ref:pw@aws-0-eu-west-2.pooler.supabase.com:6543/postgres")
    assert s.db_ssl_required() is True
    assert s.uses_transaction_pooler() is True
    local = Settings(SECRET_KEY="x", DATABASE_URL="postgresql://u:p@localhost:5432/db")
    assert local.db_ssl_required() is False and local.uses_transaction_pooler() is False


def test_production_defaults_never_seed_demo_accounts():
    s = Settings(SECRET_KEY="x", ENVIRONMENT="production", SEED_SAMPLE_DATA=None, AUTO_CREATE_TABLES=None)
    assert s.SEED_SAMPLE_DATA is False and s.AUTO_CREATE_TABLES is False
