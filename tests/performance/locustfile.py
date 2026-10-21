# tests/performance/locustfile.py
from locust import HttpUser, task, between
import random

# --- Test Data ---
# In a real-world scenario, you would populate these from a test DB or a CSV file.
# For now, we'll use the sample data we created on startup.
ADMIN_CREDENTIALS = ("admin@school.com", "admin123")
STAFF_CREDENTIALS = ("teacher@school.com", "teacher123")
STUDENT_CREDENTIALS = ("student@school.com", "student123")

# We need IDs from your database to test GET requests for specific items.
# Replace these with actual IDs from your test database.
TEST_STUDENT_ID = "030d5ea3-2694-472c-a1ed-02ed241ba552"
TEST_INVOICE_ID = "8fe2fd97-1e94-4bfa-97a3-17299094731f"
TEST_CLASS_ID = "c3c9320f-150a-4148-acb5-1e97513e3a5f"
TEST_SUBJECT_ID = "24bbb252-2bea-4596-82a4-ec097ff2a3e2"
TEST_SESSION_ID = "267f3bd3-f0ec-4819-ab20-537f789f3b91"
TEST_TERM_ID = "29d497b3-89aa-4ca1-85a9-4704a3f3e82e"


class BaseApiUser(HttpUser):
    """
    Base user class that handles logging in and storing the auth token.
    """
    abstract = True  # This tells Locust not to run this User class directly
    wait_time = between(1, 5)  # Users wait 1-5 seconds between tasks
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.token = None

    def on_start(self):
        """Called when a Locust user starts."""
        self.login()

    def login(self):
        # This method should be implemented by child classes
        raise NotImplementedError

    def get_auth_headers(self):
        if not self.token:
            self.login()
        return {"Authorization": f"Bearer {self.token}"}


class AdminUser(BaseApiUser):
    weight = 3 # 30% of users will be Admins

    def login(self):
        username, password = ADMIN_CREDENTIALS
        res = self.client.post(
            "/auth/token",
            data={"username": username, "password": password}
        )
        if res.status_code == 200:
            self.token = res.json().get("access_token")

    @task(5) # Higher weight = more frequent task
    def view_admin_dashboard_stats(self):
        self.client.get("/admin/dashboard/stats", headers=self.get_auth_headers(), name="/admin/dashboard/stats")

    @task(3)
    def view_paginated_students(self):
        # Simulate user browsing through pages
        skip = random.randint(0, 5) * 10
        self.client.get(
            f"/admin/students?skip={skip}&limit=10",
            headers=self.get_auth_headers(),
            name="/admin/students?skip=[skip]&limit=10" # Group similar URLs
        )
        
    @task(2)
    def view_paginated_invoices(self):
        skip = random.randint(0, 3) * 15
        self.client.get(
            f"/fees/admin/invoices?skip={skip}&limit=15&session_id={TEST_SESSION_ID}",
            headers=self.get_auth_headers(),
            name="/fees/admin/invoices?skip=[skip]&limit=15"
        )
        
    @task(1) # Lower weight = less frequent task
    def check_results_progress(self):
        self.client.get(
            f"/results/admin/results-entry-progress?session_id={TEST_SESSION_ID}&term_id={TEST_TERM_ID}",
            headers=self.get_auth_headers(),
            name="/results/admin/results-entry-progress"
        )


class StaffUser(BaseApiUser):
    weight = 2 # 20% of users will be Staff

    def login(self):
        username, password = STAFF_CREDENTIALS
        res = self.client.post(
            "/auth/token",
            data={"username": username, "password": password}
        )
        if res.status_code == 200:
            self.token = res.json().get("access_token")

    @task(5)
    def view_staff_dashboard(self):
        self.client.get("/staff/dashboard", headers=self.get_auth_headers(), name="/staff/dashboard")

    @task(3)
    def view_my_classes(self):
        self.client.get("/staff/my-classes", headers=self.get_auth_headers(), name="/staff/my-classes")
        
    @task(1)
    def view_results_marksheet(self):
        self.client.get(
            f"/staff/my-classes/{TEST_CLASS_ID}/subject/{TEST_SUBJECT_ID}/results",
            headers=self.get_auth_headers(),
            name="/staff/my-classes/{id}/subject/{id}/results"
        )


class StudentUser(BaseApiUser):
    weight = 5 # 50% of users will be Students (most common user type)

    def login(self):
        username, password = STUDENT_CREDENTIALS
        res = self.client.post(
            "/auth/token",
            data={"username": username, "password": password}
        )
        if res.status_code == 200:
            self.token = res.json().get("access_token")
    
    @task(10) # Most frequent action
    def view_student_dashboard(self):
        self.client.get("/student/dashboard", headers=self.get_auth_headers(), name="/dashboard/student/dashboard")
    
    # @task(2)
    # def view_my_invoices(self):
    #     self.client.get(f"/fees/invoices/by-student", headers=self.get_auth_headers(), name="/fees/invoices/by-student")
        
    # @task(1)
    # def view_single_invoice(self):
    #     self.client.get(f"/fees/student/invoices/{TEST_INVOICE_ID}", headers=self.get_auth_headers(), name="/fees/student/invoices/{id}")