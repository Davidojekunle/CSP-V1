
from sqlmodel import Session, select, func, and_, or_, exists
from sqlalchemy import case, distinct
from datetime import datetime, date, timedelta
from app.models import User, UserRole, Gender, StudentProfile, StaffProfile, Enrollment, Invoice, InvoiceStatus, Payment, AcademicSession


def get_general_dashboard_stats(session: Session) -> dict:
    """
    Calculates general stats. Preserves the original `DashboardStatsResponse` shape.
    PERFORMANCE: Uses `func.count` for efficient counting.
    """
    total_users = session.exec(select(func.count(User.id))).one()
    active_users = session.exec(select(func.count(User.id)).where(User.is_active == True)).one()
    total_students = session.exec(select(func.count(User.id)).where(User.role == UserRole.student)).one()
    total_staff = session.exec(select(func.count(User.id)).where(User.role == UserRole.staff)).one()
    total_admins = session.exec(select(func.count(User.id)).where(User.role == UserRole.admin)).one()

    one_month_ago = datetime.utcnow() - timedelta(days=30)
    new_students = session.exec(select(func.count(User.id)).where(User.role == UserRole.student, User.created_at >= one_month_ago)).one()
    new_staff = session.exec(select(func.count(User.id)).where(User.role == UserRole.staff, User.created_at >= one_month_ago)).one()

    unenrolled_students_query = select(func.count(User.id)).where(
        User.role == UserRole.student,
        User.is_active == True,
        ~exists().where(and_(Enrollment.student_id == User.id, Enrollment.is_active == True))
    )
    unenrolled_students = session.exec(unenrolled_students_query).one()
    
    return {
        "totalUsers": total_users,
        "activeUsers": active_users,
        "totalStudents": total_students,
        "totalStaff": total_staff,
        "totalAdmins": total_admins,
        "newStudentsLast30Days": new_students,
        "newStaffLast30Days": new_staff,
        "unenrolledStudents": unenrolled_students
    }

def get_student_dashboard_stats(session: Session) -> dict:
    """Calculates student-specific stats."""
    total_students = session.exec(select(func.count(User.id)).where(User.role == UserRole.student)).one()
    active_students = session.exec(select(func.count(User.id)).where(User.role == UserRole.student, User.is_active == True)).one()
    
    first_day_of_month = date.today().replace(day=1)
    new_this_month = session.exec(select(func.count(User.id)).where(User.role == UserRole.student, User.created_at >= first_day_of_month)).one()

    male_students = session.exec(select(func.count(User.id)).where(User.role == UserRole.student, User.gender == Gender.male)).one()
    female_students = session.exec(select(func.count(User.id)).where(User.role == UserRole.student, User.gender == Gender.female)).one()

    return {
        "total_students": total_students,
        "active_students": active_students,
        "inactive_students": total_students - active_students,
        "new_this_month": new_this_month,
        "male_students": male_students,
        "female_students": female_students
    }

def get_staff_dashboard_stats(session: Session) -> dict:
    """Calculates staff-specific stats."""
    staff_admin_roles = [UserRole.staff, UserRole.admin]
    total_staff_and_admins = session.exec(select(func.count(User.id)).where(User.role.in_(staff_admin_roles))).one()
    administrators = session.exec(select(func.count(User.id)).where(User.role == UserRole.admin)).one()
    active_staff_and_admins = session.exec(select(func.count(User.id)).where(User.role.in_(staff_admin_roles), User.is_active == True)).one()
    
    first_day_of_month = date.today().replace(day=1)
    new_this_month = session.exec(select(func.count(User.id)).where(User.role.in_(staff_admin_roles), User.created_at >= first_day_of_month)).one()
    
    return {
        "total_staff_and_admins": total_staff_and_admins,
        "administrators": administrators,
        "active_staff_and_admins": active_staff_and_admins,
        "new_this_month": new_this_month
    }
    
def get_fee_collection_overview(session: Session) -> dict:
    """Calculates fee collection overview stats."""
    paid_amount = session.exec(select(func.coalesce(func.sum(Invoice.total_amount), 0.0)).where(Invoice.status == InvoiceStatus.paid)).one()
    pending_amount = session.exec(select(func.coalesce(func.sum(Invoice.total_amount), 0.0)).where(Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.partial]))).one()
    overdue_amount = session.exec(select(func.coalesce(func.sum(Invoice.total_amount), 0.0)).where(Invoice.status == InvoiceStatus.overdue)).one()

    return {
        "paid_amount": paid_amount,
        "pending_amount": pending_amount,
        "overdue_amount": overdue_amount
    }

def get_enrollment_stats_by_session(db: Session) -> list:
    """
    PERFORMANCE OPTIMIZED: Gets unique student enrollment counts grouped by academic session
    using a single, efficient database query.
    """
    # This query is identical to your original high-performance version.
    query = (
        select(
            AcademicSession.id,
            AcademicSession.name,
            func.count(distinct(Enrollment.student_id)).label("total_students"),
            func.count(
                distinct(case((Enrollment.is_active == True, Enrollment.student_id), else_=None))
            ).label("active_students")
        )
        .join(Enrollment, AcademicSession.id == Enrollment.session_id)
        .group_by(AcademicSession.id, AcademicSession.name)
        .order_by(AcademicSession.name.desc()) # Order by name descending to show newest first
    )
    
    results = db.exec(query).all()
    
    # The data is already in the shape we need, just map it.
    stats = [
        {
            "session_id": row.id,
            "session_name": row.name,
            "total_students": row.total_students,
            "active_students": row.active_students
        }
        for row in results
    ]
    
    return stats