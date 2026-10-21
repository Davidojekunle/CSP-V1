"""
Endpoints the dashboard frontend calls that were missing from the API.
Request/response shapes follow the frontend's TypeScript types.
"""
from datetime import date

from sqlmodel import select

from app.models import (
    AcademicSession, BehavioralTraits, FeeAssignment, Invoice, InvoiceStatus, Payment, PaymentStatus, Result, Subject, Term,
)
from tests.conftest import auth_header


def _result(session, s, student, total_parts=(10, 10, 40), published=True):
    r = Result(student_id=student.id, class_id=s["class_a"].id, subject_id=s["subject"].id,
               session_id=s["session"].id, term_id=s["term"].id,
               ca1=total_parts[0], ca2=total_parts[1], exam=total_parts[2], total=sum(total_parts), is_published=published)
    session.add(r)
    session.commit()
    return r


# --- Academic -------------------------------------------------------------------

def test_update_class(client, school):
    s = school
    r = client.put(f"/admin/academic/classes/{s['class_a'].id}", headers=auth_header(s["admin"]),
                   json={"level": "JSS1", "arm": "B", "name": "JSS1 B"})
    assert r.status_code == 200
    body = r.json()
    assert (body["name"], body["arm"], body["form_teacher_name"]) == ("JSS1 B", "B", "John Doe")
    assert body["students_count"] == 1 and body["subjects_count"] == 1


def test_update_class_duplicate_name_rejected(client, school):
    s = school
    r = client.put(f"/admin/academic/classes/{s['class_a'].id}", headers=auth_header(s["admin"]), json={"name": "SS2 A"})
    assert r.status_code == 400 and r.json()["detail"] == "Class name already exists"


def test_update_term_validates_dates(client, school):
    s = school
    url = f"/admin/academic/terms/{s['term'].id}"
    ok = client.put(url, headers=auth_header(s["admin"]), json={"end_date": "2024-12-15"})
    assert ok.status_code == 200 and ok.json()["end_date"] == "2024-12-15" and ok.json()["session_name"] == "2024/2025"
    outside = client.put(url, headers=auth_header(s["admin"]), json={"end_date": "2030-01-01"})
    assert outside.status_code == 400


def test_set_current_session(client, school, session):
    s = school
    other = AcademicSession(name="2025/2026", start_date=date(2025, 9, 1), end_date=date(2026, 7, 31), is_current=False)
    session.add(other)
    session.commit()
    r = client.post(f"/admin/academic/sessions/{other.id}/set-current", headers=auth_header(s["admin"]))
    assert r.json() == {"message": "Session '2025/2026' is now current."}
    session.expire_all()
    assert session.get(AcademicSession, other.id).is_current is True
    assert session.get(AcademicSession, s["session"].id).is_current is False
    assert session.get(Term, s["term"].id).is_current is False  # term of the old session


def test_update_and_delete_subject(client, school, session):
    s = school
    h = auth_header(s["admin"])
    r = client.put(f"/admin/academic/subjects/{s['subject'].id}", headers=h, json={"name": "Maths", "code": "mth2"})
    assert r.status_code == 200 and (r.json()["name"], r.json()["code"], r.json()["classes_count"]) == ("Maths", "MTH2", 1)
    # In use (assigned to a class): refuse to delete
    assert client.delete(f"/admin/academic/subjects/{s['subject'].id}", headers=h).status_code == 400
    unused = Subject(code="ART", name="Art")
    session.add(unused)
    session.commit()
    assert client.delete(f"/admin/academic/subjects/{unused.id}", headers=h).status_code == 204
    session.expunge_all()
    assert session.exec(select(Subject).where(Subject.code == "ART")).first() is None


# --- Results --------------------------------------------------------------------

def test_update_single_result_recalculates(client, school, session):
    s = school
    res = _result(session, s, s["students"][0])
    r = client.put(f"/results/{res.id}", headers=auth_header(s["teacher"]), json={"ca1": 20, "ca2": 15, "exam": 50})
    assert r.status_code == 200
    assert r.json()["total"] == 85 and r.json()["grade_letter"]
    session.expire_all()
    assert session.get(Result, res.id).total == 85


def test_available_terms(client, school, session):
    s = school
    student = s["students"][0]
    _result(session, s, student, published=False)
    admin_view = client.get(f"/results/student/{student.id}/available-terms", headers=auth_header(s["admin"])).json()
    assert admin_view["available_terms"][0]["term_id"] == s["term"].id
    # Students only see published results, and only their own
    assert client.get(f"/results/student/{student.id}/available-terms", headers=auth_header(student)).json() == {"available_terms": []}
    other = s["students"][1]
    assert client.get(f"/results/student/{student.id}/available-terms", headers=auth_header(other)).status_code == 403


def test_get_behavioral_traits(client, school, session):
    s = school
    student = s["students"][0]
    url = f"/behavioral-traits/student/{student.id}?session_id={s['session'].id}&term_id={s['term'].id}"
    h = auth_header(s["teacher"])
    assert client.get(url, headers=h).json() == {}
    client.post("/behavioral-traits/", headers=h, json={"student_id": student.id, "neatness": "A"})
    assert client.get(url, headers=h).json()["neatness"] == "A"


# --- Fees -------------------------------------------------------------------------

def _fee_assignment(client, s):
    fee = client.post("/fees/admin/fees", headers=auth_header(s["admin"]),
                      json={"name": "Tuition", "amount": 5000, "frequency": "term"}).json()
    client.post("/fees/admin/fee-assignments", headers=auth_header(s["admin"]), json={
        "fee_id": fee["id"], "session_id": s["session"].id, "term_id": s["term"].id, "target_type": "SCHOOL"})
    return fee


def test_invoice_preview_matches_generation(client, school, session):
    s = school
    _fee_assignment(client, s)
    params = f"session_id={s['session'].id}&term_id={s['term'].id}&due_date=2099-01-31&scope=school"
    preview = client.get(f"/fees/admin/invoice-generation/preview?{params}", headers=auth_header(s["admin"])).json()
    assert preview["students_to_invoice"] == 2 and preview["invoices_to_create"] == 2
    assert preview["estimated_total_amount"] == 10000
    assert {p["admission_number"] for p in preview["sample_students"]} == {"ADM000", "ADM001"}
    assert session.exec(select(Invoice)).all() == []  # preview writes nothing

    gen = client.post("/fees/admin/generate-invoices", headers=auth_header(s["admin"]), json={
        "due_date": "2099-01-31", "scope": "school", "session_id": s["session"].id, "term_id": s["term"].id})
    assert gen.json()["message"] == "Process complete. Created: 2, Updated: 0."
    after = client.get(f"/fees/admin/invoice-generation/preview?{params}", headers=auth_header(s["admin"])).json()
    assert after["students_to_invoice"] == 0


def test_invoice_preview_class_scope(client, school):
    s = school
    _fee_assignment(client, s)
    params = (f"session_id={s['session'].id}&term_id={s['term'].id}&due_date=2099-01-31"
              f"&scope=classes&target_ids={s['class_b'].id}")
    preview = client.get(f"/fees/admin/invoice-generation/preview?{params}", headers=auth_header(s["admin"])).json()
    assert preview["students_to_invoice"] == 1 and preview["sample_students"][0]["admission_number"] == "ADM001"


def test_delete_fee_assignment(client, school, session):
    s = school
    _fee_assignment(client, s)
    assignment = session.exec(select(FeeAssignment)).first()
    assert client.delete(f"/fees/admin/fee-assignments/{assignment.id}", headers=auth_header(s["admin"])).status_code == 204
    session.expunge_all()
    assert session.exec(select(FeeAssignment)).all() == []


def test_invoice_report_downloads(client, school, session):
    s = school
    _fee_assignment(client, s)
    client.post("/fees/admin/generate-invoices", headers=auth_header(s["admin"]), json={
        "due_date": "2099-01-31", "scope": "school", "session_id": s["session"].id, "term_id": s["term"].id})
    h = auth_header(s["admin"])
    xlsx = client.get("/fees/admin/invoice-report?payment_status=all&file_type=excel", headers=h)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"
    assert "attachment; filename=invoice_report_" in xlsx.headers["content-disposition"]
    pdf = client.get("/fees/admin/invoice-report?payment_status=unpaid&file_type=pdf", headers=h)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert client.get("/fees/admin/invoice-report?payment_status=bogus", headers=h).status_code == 400


def _paystack_payment(session, s, amount=5000.0):
    inv = Invoice(invoice_number="INV-VERIFY", student_id=s["students"][0].id, session_id=s["session"].id,
                  term_id=s["term"].id, status=InvoiceStatus.issued, due_date=date(2099, 1, 1),
                  total_amount=amount, balance_due=amount)
    session.add(inv)
    session.commit()
    pay = Payment(invoice_id=inv.id, paystack_reference="PAY_VERIFY_1", amount=amount, status=PaymentStatus.pending)
    session.add(pay)
    session.commit()
    return inv, pay


def test_verify_payment_success(client, school, session, monkeypatch):
    s = school
    inv, pay = _paystack_payment(session, s)

    async def fake_verify(reference):
        return {"status": True, "data": {"status": "success", "amount": 500000, "channel": "card"}}

    from app.services.payment.paystack import paystack_service
    monkeypatch.setattr(paystack_service, "verify_transaction", fake_verify)
    r = client.post(f"/fees/admin/verify-payment/{pay.id}", headers=auth_header(s["admin"]))
    assert r.status_code == 200 and r.json()["invoice_status"] == "PAID"
    session.expire_all()
    assert session.get(Payment, pay.id).status == PaymentStatus.successful
    # A second verify is a no-op
    again = client.post(f"/fees/admin/verify-payment/{pay.id}", headers=auth_header(s["admin"]))
    assert again.json()["message"] == "Payment is already verified."
    assert session.get(Invoice, inv.id).paid_amount == 5000


def test_verify_payment_amount_mismatch_marks_failed(client, school, session, monkeypatch):
    s = school
    inv, pay = _paystack_payment(session, s)

    async def fake_verify(reference):
        return {"status": True, "data": {"status": "success", "amount": 100}}  # far less than charged

    from app.services.payment.paystack import paystack_service
    monkeypatch.setattr(paystack_service, "verify_transaction", fake_verify)
    r = client.post(f"/fees/admin/verify-payment/{pay.id}", headers=auth_header(s["admin"]))
    assert r.status_code == 400
    session.expire_all()
    assert session.get(Payment, pay.id).status == PaymentStatus.failed
    assert session.get(Invoice, inv.id).paid_amount == 0


def test_student_invoice_pdf_owner_only(client, school, session):
    s = school
    inv, _ = _paystack_payment(session, s)
    own = client.get(f"/fees/student/invoice/{inv.id}/pdf", headers=auth_header(s["students"][0]))
    assert own.status_code == 200 and own.content[:4] == b"%PDF"
    assert client.get(f"/fees/student/invoice/{inv.id}/pdf", headers=auth_header(s["students"][1])).status_code == 404
