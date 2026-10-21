# app/services/payment/paystack.py
"""
Service for handling all interactions with the Paystack API.
"""
import hashlib
import hmac
import logging
from typing import Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Paystack can be slow but should never hang a request indefinitely
_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


class PaystackService:
    def __init__(self):
        self.secret_key = settings.PAYSTACK_SECRET_KEY
        self.base_url = "https://api.paystack.co"
        if not self.secret_key:
            logger.warning("PAYSTACK_SECRET_KEY is not set. Payment features will fail.")

    def _get_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.secret_key}", "Content-Type": "application/json"}

    async def initialize_transaction(self, email: str, amount: float, reference: str, callback_url: Optional[str], metadata: dict) -> dict:
        payload = {
            "email": email,
            "amount": int(round(amount * 100)),  # Amount in kobo
            "reference": reference,
            "currency": "NGN",
            "metadata": metadata
        }
        if callback_url:
            payload["callback_url"] = callback_url

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(f"{self.base_url}/transaction/initialize", headers=self._get_headers(), json=payload)
        response.raise_for_status()
        return response.json()

    async def verify_transaction(self, reference: str) -> dict:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{self.base_url}/transaction/verify/{reference}", headers=self._get_headers())
        response.raise_for_status()
        return response.json()

    def verify_webhook_signature(self, payload: bytes, signature: Optional[str]) -> bool:
        if not self.secret_key or not signature:
            return False
        expected_signature = hmac.new(self.secret_key.encode('utf-8'), payload, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected_signature, signature)


# Create a singleton instance for the app to use
paystack_service = PaystackService()
