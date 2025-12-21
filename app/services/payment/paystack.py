# app/services/payment/paystack.py
"""
Service for handling all interactions with the Paystack API.
"""
import requests
import hmac
import hashlib
from typing import Dict, Optional

from app.core.config import settings

class PaystackService:
    def __init__(self):
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.base_url = "https://api.paystack.co"
        if not self.secret_key:
            print("WARNING: PAYSTACK_SECRET_KEY is not set. Payment features will fail.")

    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}

    def initialize_transaction(self, email: str, amount: float, reference: str, callback_url: Optional[str], metadata: dict) -> dict:
        url = f"{self.base_url}/transaction/initialize"
        payload = {
            "email": email,
            "amount": int(amount * 100),  # Amount in kobo
            "reference": reference,
            "currency": "NGN",
            "metadata": metadata
        }
        if callback_url:
            payload["callback_url"] = callback_url
        
        response = requests.post(url, headers=self._get_headers(), json=payload)
        response.raise_for_status()
        return response.json()

    def verify_transaction(self, reference: str) -> dict:
        url = f"{self.base_url}/transaction/verify/{reference}"
        response = requests.get(url, headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        if not self.secret_key: return False
        expected_signature = hmac.new(self.secret_key.encode('utf-8'), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected_signature, signature)

# Create a singleton instance for the app to use
paystack_service = PaystackService()