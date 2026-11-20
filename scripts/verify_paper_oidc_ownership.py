#!/usr/bin/env python3
"""Provider-backed two-identity PAPER ownership acceptance.

Creates one persistent account with fictional capital for identity A, then
verifies identity B cannot discover or operate on it. It never opens trades,
connects to an exchange account, or submits exchange orders.

Run only against a dedicated PAPER acceptance database.
"""
from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import requests


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Falta la variable obligatoria {name}")
    return value


def expect_status(label: str, response: requests.Response, expected: int) -> None:
    if response.status_code != expected:
        detail = response.text[:500].replace("\n", " ")
        raise RuntimeError(
            f"{label}: esperado HTTP {expected}, recibido {response.status_code}: {detail}"
        )
    print(f"PASS {label}: HTTP {expected}")


def api_request(
    session: requests.Session,
    base_url: str,
    method: str,
    path: str,
    *,
    token: str | None = None,
    payload: dict | None = None,
) -> requests.Response:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    return session.request(
        method,
        f"{base_url}{path}",
        headers=headers,
        json=payload,
        timeout=15,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Comprueba aislamiento de dos identidades OIDC en la API PAPER."
    )
    parser.add_argument(
        "--confirm-create",
        action="store_true",
        help="Confirma que se puede crear una cuenta PAPER persistente de prueba.",
    )
    args = parser.parse_args()

    if not args.confirm_create:
        parser.error("Añade --confirm-create solo después de confirmar que usas una DB PAPER de pruebas.")

    if required_env("AI_TRADER_ACCEPTANCE_DB_CONFIRMED") != "YES":
        raise ValueError(
            "Define AI_TRADER_ACCEPTANCE_DB_CONFIRMED=YES solo para una base de datos PAPER dedicada."
        )

    base_url = os.environ.get(
        "AI_TRADER_BASE_URL", "http://127.0.0.1:8000"
    ).strip().rstrip("/")
    token_a = required_env("AI_TRADER_TEST_USER_A_TOKEN")
    token_b = required_env("AI_TRADER_TEST_USER_B_TOKEN")
    opening_capital = required_env("AI_TRADER_TEST_OPENING_CAPITAL")
    quote_currency = required_env("AI_TRADER_TEST_QUOTE_CURRENCY").upper()

    try:
        capital = Decimal(opening_capital)
    except InvalidOperation:
        raise ValueError("AI_TRADER_TEST_OPENING_CAPITAL debe ser un decimal válido.") from None
    if not capital.is_finite() or capital <= 0:
        raise ValueError("El capital ficticio debe ser positivo y finito.")
    if not quote_currency.isalnum() or not 3 <= len(quote_currency) <= 8:
        raise ValueError("AI_TRADER_TEST_QUOTE_CURRENCY no es válida.")
    if token_a == token_b:
        raise ValueError("Las dos variables deben contener tokens distintos de dos identidades.")

    session = requests.Session()
    session.headers.update({"User-Agent": "ai-trader-paper-oidc-acceptance/1.0"})

    health = api_request(session, base_url, "GET", "/health")
    expect_status("health", health, 200)

    anonymous = api_request(session, base_url, "GET", "/api/paper/accounts")
    expect_status("PAPER sin token rechaza acceso", anonymous, 401)

    opening_key = f"oidc-two-user-acceptance-{uuid4()}"
    created = api_request(
        session,
        base_url,
        "POST",
        "/api/paper/accounts",
        token=token_a,
        payload={
            "name": "OIDC two-user acceptance",
            "quote_currency": quote_currency,
            "opening_capital": str(capital),
            "idempotency_key": opening_key,
        },
    )
    expect_status("identity A creates fictional PAPER account", created, 201)
    created_payload = created.json()
    account = created_payload.get("account") or {}
    account_id = account.get("id")
    if not account_id:
        raise RuntimeError("La API no devolvió account.id al crear la cuenta.")
    if created_payload.get("live_trading_authorized") is not False:
        raise RuntimeError("La API no confirmó live_trading_authorized=false.")
    print(f"Cuenta de aceptación creada: {account_id}")

    owner_a_read = api_request(
        session, base_url, "GET", f"/api/paper/accounts/{account_id}", token=token_a
    )
    expect_status("identity A reads its account", owner_a_read, 200)
    account_payload = owner_a_read.json()
    for field in ("balance", "equity", "free_cash"):
        try:
            actual = Decimal(str(account_payload[field]))
        except (KeyError, InvalidOperation):
            raise RuntimeError(f"Respuesta de cuenta sin valor decimal válido: {field}") from None
        if actual != capital:
            raise RuntimeError(
                f"{field} inicial esperado {capital}, recibido {actual}; no se continúa."
            )
    print("PASS capital, balance, equity y free cash coinciden con el capital ficticio inicial")

    owner_a_list = api_request(
        session, base_url, "GET", "/api/paper/accounts", token=token_a
    )
    expect_status("identity A lists accounts", owner_a_list, 200)
    if account_id not in {
        item.get("id") for item in owner_a_list.json().get("accounts", [])
    }:
        raise RuntimeError("La cuenta recién creada no aparece en el listado de identity A.")

    owner_b_list = api_request(
        session, base_url, "GET", "/api/paper/accounts", token=token_b
    )
    expect_status("identity B lists only its own accounts", owner_b_list, 200)
    if account_id in {
        item.get("id") for item in owner_b_list.json().get("accounts", [])
    }:
        raise RuntimeError("FALLO: identity B puede descubrir la cuenta de identity A.")

    account_path = f"/api/paper/accounts/{account_id}"
    blocked_requests = [
        ("identity B cannot read account", "GET", account_path, None),
        ("identity B cannot list trades", "GET", f"{account_path}/trades", None),
        ("identity B cannot read risk", "GET", f"{account_path}/risk", None),
        ("identity B cannot read events", "GET", f"{account_path}/events", None),
        (
            "identity B cannot fund account",
            "POST",
            f"{account_path}/funding",
            {
                "event_type": "DEPOSIT",
                "amount": "1",
                "idempotency_key": f"unauthorized-funding-{uuid4()}",
            },
        ),
        (
            "identity B cannot open a trade",
            "POST",
            f"{account_path}/trades",
            {
                "symbol": "BTCUSDT",
                "strategy": "ownership-acceptance",
                "side": "LONG",
                "stop_price": "1",
                "idempotency_key": f"unauthorized-open-{uuid4()}",
                "risk_fraction": "0.01",
            },
        ),
        (
            "identity B cannot halt account",
            "POST",
            f"{account_path}/halt",
            {"reason": "negative ownership acceptance test"},
        ),
        (
            "identity B cannot reset account",
            "POST",
            f"{account_path}/reset",
            {"confirmed": True},
        ),
        (
            "identity B cannot close a trade in account",
            "POST",
            f"{account_path}/trades/00000000-0000-0000-0000-000000000000/close",
            {"exit_fee": "0", "exit_reason": "negative ownership acceptance test"},
        ),
    ]

    for label, method, path, payload in blocked_requests:
        response = api_request(
            session, base_url, method, path, token=token_b, payload=payload
        )
        expect_status(label, response, 404)

    owner_a_after = api_request(
        session, base_url, "GET", account_path, token=token_a
    )
    expect_status("identity A retains access after identity B attempts", owner_a_after, 200)
    after_payload = owner_a_after.json()
    if Decimal(str(after_payload["balance"])) != capital:
        raise RuntimeError("FALLO: balance cambió tras los intentos no autorizados de identity B.")
    if after_payload.get("open_positions"):
        raise RuntimeError("FALLO: esta prueba de autorización no debía abrir posiciones.")

    print("\nRESULTADO: PASS — aislamiento HTTP entre dos identidades OIDC.")
    print("La cuenta de prueba queda guardada en la base PAPER persistente.")
    print("No se abrieron operaciones y no se enviaron órdenes a ningún exchange.")
    print(f"ACCOUNT_ID={account_id}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, requests.RequestException) as error:
        print(f"RESULTADO: FAIL — {error}", file=sys.stderr)
        raise SystemExit(1)
