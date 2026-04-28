from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .config import OpenproviderConfig, RegistrationConfig
from .domain import DomainName


class OpenproviderError(RuntimeError):
    pass


class OpenproviderClient:
    def __init__(self, config: OpenproviderConfig, timeout_seconds: int = 30):
        self.config = config
        self.timeout_seconds = timeout_seconds
        self._token: str | None = None

    def check_domains(self, domains: list[DomainName]) -> list[dict[str, Any]]:
        response = self._request("POST", "/domains/check", build_check_payload(domains), retry_auth=True)
        _raise_for_api_error(response)
        return list((response.get("data") or {}).get("results") or [])

    def create_domain(
        self,
        domain: DomainName,
        registration: RegistrationConfig,
        check_result: dict[str, Any],
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/domains",
            build_create_payload(domain, registration, check_result),
            retry_auth=True,
        )
        _raise_for_api_error(response)
        return response

    def _login(self) -> str:
        payload = {
            "username": self.config.username,
            "password": self.config.password,
            "ip": self.config.ip,
        }
        response = self._request("POST", "/auth/login", payload, authenticated=False, retry_auth=False)
        _raise_for_api_error(response)
        token = ((response.get("data") or {}).get("token") or "").strip()
        if not token:
            raise OpenproviderError("Openprovider login did not return a token")
        self._token = token
        return token

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any],
        authenticated: bool = True,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        if authenticated and not self._token:
            self._login()
        url = f"{self.config.base_url}{path}"
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if authenticated and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if authenticated and retry_auth and exc.code in {401, 403}:
                self._token = None
                self._login()
                return self._request(method, path, payload, authenticated=True, retry_auth=False)
            detail = exc.read().decode("utf-8", errors="replace")
            raise OpenproviderError(f"HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise OpenproviderError(str(exc.reason)) from exc


def build_check_payload(domains: list[DomainName]) -> dict[str, Any]:
    return {
        "domains": [{"name": domain.name, "extension": domain.extension} for domain in domains],
        "with_price": True,
    }


def build_create_payload(
    domain: DomainName,
    registration: RegistrationConfig,
    check_result: dict[str, Any],
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "domain": {"name": domain.name, "extension": domain.extension},
        "period": registration.period,
        "autorenew": registration.autorenew,
        "owner_handle": registration.owner_handle,
        "admin_handle": registration.admin_handle,
        "tech_handle": registration.tech_handle,
        "billing_handle": registration.billing_handle,
    }
    if registration.ns_group:
        payload["ns_group"] = registration.ns_group
    if registration.name_servers:
        payload["name_servers"] = registration.name_servers
    if registration.provider:
        payload["provider"] = registration.provider
    _validate_create_price(check_result, registration.max_create_price)
    if check_result.get("is_premium"):
        fee = (((check_result.get("premium") or {}).get("price") or {}).get("create"))
        if fee is None:
            raise ValueError("Premium domain has no known create price")
        payload["accept_premium_fee"] = fee
    return payload


def _validate_create_price(check_result: dict[str, Any], max_create_price: float | None) -> None:
    if max_create_price is None:
        return

    price = _extract_create_price(check_result)
    if price is None:
        raise ValueError("Domain create price is unknown")
    if price > max_create_price:
        raise ValueError(f"Domain create price {price} exceeds configured limit {max_create_price}")


def _extract_create_price(check_result: dict[str, Any]) -> float | None:
    price = check_result.get("price") or {}
    reseller = price.get("reseller") or {}
    return _to_float(reseller.get("price"))


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _raise_for_api_error(response: dict[str, Any]) -> None:
    code = response.get("code", 0)
    if code not in (0, None):
        desc = response.get("desc") or response.get("data") or "Openprovider API error"
        raise OpenproviderError(f"{code}: {desc}")
