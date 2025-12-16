# app/utils/grade_calculator.py
# This is a direct copy of your original grade_utils.py content.
from pydantic import BaseModel
from typing import Optional, Tuple

class GradeConfig(BaseModel):
    a_min: float = 70.0
    b_min: float = 60.0
    c_min: float = 50.0
    d_min: float = 45.0
    e_min: float = 40.0

def calculate_grade(
    total_score: Optional[float],
    grade_config: GradeConfig = GradeConfig()
) -> Tuple[Optional[str], Optional[str]]:
    """
    Calculate letter grade and remark from total score
    based on a 5-point grading scale.

    Args:
        total_score (float | None): The student's total score.
        grade_config (GradeConfig): Configurable grade boundaries.

    Returns:
        tuple: (Letter grade, Remark) or (None, None) if score is None.
    """
    if total_score is None:
        return None, None

    if total_score >= grade_config.a_min:
        return "A", "Excellent"
    elif total_score >= grade_config.b_min:
        return "B", "Very Good"
    elif total_score >= grade_config.c_min:
        return "C", "Good"
    elif total_score >= grade_config.d_min:
        return "D", "Satisfactory"
    elif total_score >= grade_config.e_min:
        return "E", "Fair"
    else:
        return "F", "Fail"


def calculate_detailed_grade(
    total_score: Optional[float]
) -> Tuple[Optional[str], Optional[str]]:
    """
    Calculate a detailed letter grade and remark
    based on a 9-point grading scale (WAEC style).

    Args:
        total_score (float | None): The student's total score.

    Returns:
        tuple: (Letter grade, Remark) or (None, None) if score is None.
    """
    if total_score is None:
        return None, None

    if total_score >= 75:
        return "A1", "EXCELLENT"
    elif total_score >= 70:
        return "B2", "VERY GOOD"
    elif total_score >= 65:
        return "B3", "GOOD"
    elif total_score >= 60:
        return "C4", "CREDIT"
    elif total_score >= 55:
        return "C5", "CREDIT"
    elif total_score >= 50:
        return "C6", "CREDIT"
    elif total_score >= 45:
        return "D7", "PASS"
    elif total_score >= 40:
        return "E8", "PASS"
    else:
        return "F9", "FAIL"
 

def _get_rank_suffix(rank: int) -> str:
    if 11 <= rank <= 13:
        return 'th'
    return {1: 'st', 2: 'nd', 3: 'rd'}.get(rank % 10, 'th')
