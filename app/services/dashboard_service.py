
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select, func, and_, or_, exists
from sqlalchemy import case, distinct
from datetime import datetime, date, timedelta
from app.models import User, UserRole, Gender, StudentProfile, StaffProfile, Enrollment, Invoice, InvoiceStatus, Payment, AcademicSession


async def get_general_dashboard_stats(session: AsyncSession) -> dict:
    """
    Calculates general stats. Preserves the original `DashboardStatsResponse` shape.
    PERFORMANCE: Uses `func.count` for efficient counting.
    """
    result = await session.execute(select(func.count(User.id)))
    total_users = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.is_active == True))
    active_users = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.student))
    total_students = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.staff))
    total_staff = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.admin))
    total_admins = result.scalar()

    one_month_ago = datetime.utcnow() - timedelta(days=30)
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.student, User.created_at >= one_month_ago))
    new_students = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.staff, User.created_at >= one_month_ago))
    new_staff = result.scalar()

    unenrolled_students_query = select(func.count(User.id)).where(
        User.role == UserRole.student,
        User.is_active == True,
        ~exists().where(and_(Enrollment.student_id == User.id, Enrollment.is_active == True))
    )
    result = await session.execute(unenrolled_students_query)
    unenrolled_students = result.scalar()
    
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

async def get_student_dashboard_stats(session: AsyncSession) -> dict:
    """Calculates student-specific stats."""
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.student))
    total_students = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.student, User.is_active == True))
    active_students = result.scalar()
    
    first_day_of_month = date.today().replace(day=1)
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.student, User.created_at >= first_day_of_month))
    new_this_month = result.scalar()

    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.student, User.gender == Gender.male))
    male_students = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.student, User.gender == Gender.female))
    female_students = result.scalar()

    return {
        "total_students": total_students,
        "active_students": active_students,
        "inactive_students": total_students - active_students,
        "new_this_month": new_this_month,
        "male_students": male_students,
        "female_students": female_students
    }

async def get_staff_dashboard_stats(session: AsyncSession) -> dict:
    """Calculates staff-specific stats."""
    staff_admin_roles = [UserRole.staff, UserRole.admin]
    result = await session.execute(select(func.count(User.id)).where(User.role.in_(staff_admin_roles)))
    total_staff_and_admins = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role == UserRole.admin))
    administrators = result.scalar()
    result = await session.execute(select(func.count(User.id)).where(User.role.in_(staff_admin_roles), User.is_active == True))
    active_staff_and_admins = result.scalar()
    
    first_day_of_month = date.today().replace(day=1)
    result = await session.execute(select(func.count(User.id)).where(User.role.in_(staff_admin_roles), User.created_at >= first_day_of_month))
    new_this_month = result.scalar()
    
    return {
        "total_staff_and_admins": total_staff_and_admins,
        "administrators": administrators,
        "active_staff_and_admins": active_staff_and_admins,
        "new_this_month": new_this_month
    }
    
async def get_fee_collection_overview(session: AsyncSession) -> dict:
    """Calculates fee collection overview stats."""
    result = await session.execute(select(func.coalesce(func.sum(Invoice.total_amount), 0.0)).where(Invoice.status == InvoiceStatus.paid))
    paid_amount = result.scalar()
    result = await session.execute(select(func.coalesce(func.sum(Invoice.total_amount), 0.0)).where(Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.partial])))
    pending_amount = result.scalar()
    result = await session.execute(select(func.coalesce(func.sum(Invoice.total_amount), 0.0)).where(Invoice.status == InvoiceStatus.overdue))
    overdue_amount = result.scalar()

    return {
        "paid_amount": paid_amount,
        "pending_amount": pending_amount,
        "overdue_amount": overdue_amount
    }

async def get_enrollment_stats_by_session(db: AsyncSession) -> list:
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
    
    result = await db.execute(query)
    results = result.all()
    
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