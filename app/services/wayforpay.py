"""WayForPay async API client.

Handles payment creation, webhook verification, order status checks,
and regular (recurring) subscription management.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)


class WayForPayClient:
    """Async WayForPay API client."""

    PAYMENT_URL = "https://secure.wayforpay.com/pay"
    API_URL = "https://api.wayforpay.com/api"
    REGULAR_API_URL = "https://api.wayforpay.com/regularApi"

    def __init__(
        self,
        login: str,
        secret: str,
        domain: str,
        password: Optional[str] = None,
    ) -> None:
        self._login = login
        self._secret = secret
        self._domain = domain
        self._password = password
        self._http = httpx.AsyncClient(timeout=30)

    # ─── Signature ────────────────────────────────────────────

    def _calculate_signature(self, sign_string: str) -> str:
        """HMAC-MD5 signature used by WayForPay."""
        return hmac.new(
            self._secret.encode("utf-8"),
            sign_string.encode("utf-8"),
            hashlib.md5,
        ).hexdigest()

    # ─── Payment creation ─────────────────────────────────────

    def build_payment_params(
        self,
        order_ref: str,
        amount: float,
        currency: str,
        product_name: str,
        service_url: str,
        return_url: str,
        regular_mode: str = "monthly",
        regular_count: int = 12,
        regular_amount: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Build parameters for WayForPay payment form.

        Returns a dict suitable for query-string or HTML form submission.
        """
        order_date = int(time.time())
        regular_amount = regular_amount or amount

        sign_string = ";".join([
            self._login,
            self._domain,
            order_ref,
            str(order_date),
            str(amount),
            currency,
            product_name,
            "1",
            str(amount),
        ])
        signature = self._calculate_signature(sign_string)

        return {
            "merchantAccount": self._login,
            "merchantAuthType": "SimpleSignature",
            "merchantDomainName": self._domain,
            "merchantSignature": signature,
            "orderReference": order_ref,
            "orderDate": order_date,
            "amount": amount,
            "currency": currency,
            "productName[]": product_name,
            "productCount[]": 1,
            "productPrice[]": amount,
            "serviceUrl": service_url,
            "returnUrl": return_url,
            "regularMode": regular_mode,
            "regularAmount": regular_amount,
            "regularCount": regular_count,
            "regularBehavior": "preset",
        }

    def build_payment_url(self, params: Dict[str, Any], form_base_url: str) -> str:
        """Build the URL that redirects the user through the form-server to WayForPay."""
        return f"{form_base_url}?{urlencode(params)}"

    # ─── CHECK_STATUS ─────────────────────────────────────────

    async def check_order_status(self, order_ref: str) -> Dict[str, Any]:
        """Check payment status via the main WayForPay API."""
        sign_string = f"{self._login};{order_ref}"
        signature = self._calculate_signature(sign_string)

        payload = {
            "transactionType": "CHECK_STATUS",
            "merchantAccount": self._login,
            "orderReference": order_ref,
            "merchantSignature": signature,
            "apiVersion": 1,
        }

        try:
            resp = await self._http.post(self.API_URL, json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception("CHECK_STATUS failed for %s", order_ref)
            return {"reasonCode": -1, "reason": "request_failed"}

    # ─── Regular API (recurring) ──────────────────────────────

    async def check_regular_status(self, order_ref: str) -> Dict[str, Any]:
        """Check recurring subscription status via Regular API."""
        if not self._password:
            return {"reason": "no_merchant_password"}

        payload = {
            "requestType": "STATUS",
            "merchantAccount": self._login,
            "merchantPassword": self._password,
            "orderReference": order_ref,
            "apiVersion": 1,
        }

        try:
            resp = await self._http.post(self.REGULAR_API_URL, json=payload)
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception("Regular STATUS failed for %s", order_ref)
            return {"reasonCode": -1, "reason": "request_failed"}

    async def remove_regular(self, order_ref: str) -> Dict[str, Any]:
        """Remove recurring subscription via Regular API."""
        if not self._password:
            return {"reason": "no_merchant_password"}

        payload = {
            "requestType": "REMOVE",
            "merchantAccount": self._login,
            "merchantPassword": self._password,
            "orderReference": order_ref,
            "apiVersion": 1,
        }

        try:
            resp = await self._http.post(self.REGULAR_API_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Regular REMOVE for %s: reasonCode=%s", order_ref, data.get("reasonCode"))
            return data
        except Exception:
            logger.exception("Regular REMOVE failed for %s", order_ref)
            return {"reasonCode": -1, "reason": "request_failed"}

    # ─── Webhook verification ─────────────────────────────────

    def verify_webhook_signature(self, payload: Dict[str, Any]) -> bool:
        """Verify the HMAC signature on an incoming WayForPay webhook.

        Tries multiple signature formats because WayForPay sends different
        payloads for initial payments, recurring charges, and status updates.
        """
        received_sig = payload.get("merchantSignature", "")
        if not received_sig:
            return False

        def _get(key: str) -> str:
            return str(payload.get(key, ""))

        # Format 1: Standard transaction
        candidates = [
            ";".join([
                _get("merchantAccount"), _get("orderReference"),
                _get("amount"), _get("currency"),
                _get("authCode"), _get("cardPan"),
                _get("transactionStatus"), _get("reasonCode"),
            ]),
        ]

        # Format 2: With regular fields
        if payload.get("regularMode"):
            candidates.append(";".join([
                _get("merchantAccount"), _get("orderReference"),
                _get("amount"), _get("currency"),
                _get("authCode"), _get("cardPan"),
                _get("transactionStatus"), _get("reasonCode"),
                _get("regularMode"), _get("regularAmount"), _get("regularCount"),
            ]))

        # Format 3: Simplified (orderStatus)
        candidates.append(";".join([
            _get("merchantAccount"), _get("orderReference"),
            _get("amount"), _get("currency"),
            _get("orderStatus"),
        ]))

        # Format 4: Status update (processingDate)
        candidates.append(";".join([
            _get("merchantAccount"), _get("orderReference"),
            _get("processingDate"), _get("status"),
            _get("reasonCode"),
        ]))

        # Format 5: Status update (time)
        candidates.append(";".join([
            _get("merchantAccount"), _get("orderReference"),
            _get("time"), _get("status"),
            _get("reasonCode"),
        ]))

        for sign_string in candidates:
            calculated = self._calculate_signature(sign_string)
            if hmac.compare_digest(calculated, received_sig):
                return True

        return False

    def build_webhook_response(
        self,
        order_ref: str,
        status: str = "accept",
    ) -> Dict[str, Any]:
        """Build a signed response to acknowledge a WayForPay webhook."""
        timestamp = int(time.time())
        sign_string = f"{order_ref};{status};{timestamp}"
        signature = self._calculate_signature(sign_string)
        return {
            "orderReference": order_ref,
            "status": status,
            "time": timestamp,
            "signature": signature,
        }

    # ─── Cleanup ──────────────────────────────────────────────

    async def close(self) -> None:
        await self._http.aclose()
