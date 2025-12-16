import pytest
from fastapi.testclient import TestClient


class TestAuthEndpointContracts:
    """Test authentication endpoint response contracts"""
    
    def test_login_response_structure(self, client: TestClient, test_admin):
        """Verify login response has exact same structure"""
        response = client.post(
            "/auth/token",
            data={"username": "testadmin@test.com", "password": "testpass123"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # CRITICAL: Verify exact field names and types
        assert set(data.keys()) == {
            "access_token", "token_type", "user_type", "user_id", "full_name"
        }
        assert isinstance(data["access_token"], str)
        assert data["token_type"] == "bearer"
        assert data["user_type"] == "admin"
        assert isinstance(data["user_id"], str)
        assert data["full_name"] == "Test Admin"
    
    def test_me_endpoint_response_structure(
        self, client: TestClient, test_admin, admin_token
    ):
        """Verify /me endpoint response structure"""
        response = client.get(
            "/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # CRITICAL: Verify exact field names
        assert set(data.keys()) == {
            "id", "email", "username", "first_name", 
            "last_name", "role", "is_active"
        }
        assert data["email"] == "testadmin@test.com"
        assert data["username"] == "testadmin"
        assert data["role"] == "admin"
        assert data["is_active"] is True
    
    def test_change_password_response(
        self, client: TestClient, test_admin, admin_token
    ):
        """Verify change password response structure"""
        response = client.post(
            "/auth/change-password",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"old_password": "testpass123", "new_password": "newpass123"}
        )
        
        assert response.status_code == 200
        data = response.json()
        
        assert set(data.keys()) == {"message"}
        assert data["message"] == "Password changed successfully"
    
    def test_logout_response(self, client: TestClient):
        """Verify logout response structure"""
        response = client.post("/auth/logout")
        
        assert response.status_code == 200
        data = response.json()
        
        assert set(data.keys()) == {"message"}
        assert data["message"] == "Successfully logged out"
    
    def test_invalid_credentials_error_format(self, client: TestClient):
        """Verify error response format is preserved"""
        response = client.post(
            "/auth/token",
            data={"username": "wrong@test.com", "password": "wrong"}
        )
        
        assert response.status_code == 401
        data = response.json()
        
        assert "detail" in data
        assert data["detail"] == "Incorrect username/email or password"