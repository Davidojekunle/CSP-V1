from locust import HttpUser, task, between
import json

class SchoolManagementUser(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        # Login to get token
        response = self.client.post("/auth/token", data={
            "username": "admin@school.com",
            "password": "admin123"
        })
        if response.status_code == 200:
            self.token = response.json()["access_token"]
            self.headers = {"Authorization": f"Bearer {self.token}"}
        else:
            self.token = None

    @task(3)
    def get_health(self):
        self.client.get("/health")

    @task(2)
    def get_users(self):
        if hasattr(self, 'token'):
            self.client.get("/admin/users", headers=self.headers)

    @task(1)
    def get_students(self):
        if hasattr(self, 'token'):
            self.client.get("/admin/students", headers=self.headers)

    @task(1)
    def get_dashboard(self):
        if hasattr(self, 'token'):
            self.client.get("/admin/dashboard", headers=self.headers)