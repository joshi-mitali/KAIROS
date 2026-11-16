"""MegaBull paper API adapter. Submission is only called by the approval service."""

import csv
import io
import os
from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from kairos.trading.market import normalize_symbol, exchange_for

BASE_URL = "https://api.megabull.in"


class PaperOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str
    exchange: Literal["NSE", "BSE"] = "NSE"
    side: Literal["BUY", "SELL"]
    quantity: StrictInt = Field(gt=0, lt=10000)
    duration: Literal["CNC", "MIS"] = "CNC"
    order_type: Literal["LIMIT", "MKT", "SL"] = "LIMIT"
    price: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    trigger_price: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_order(self):
        symbol = normalize_symbol(self.ticker)
        if self.ticker.upper().endswith(('.NS','.BO')) and exchange_for(symbol) != self.exchange:
            raise ValueError("Ticker suffix and selected exchange disagree.")
        self.ticker = symbol.rsplit('.',1)[0]
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("A limit order requires a positive limit price.")
        if self.order_type == "SL" and self.trigger_price is None:
            raise ValueError("A stop order requires a positive trigger price.")
        return self


class MegabullClient:
    def __init__(self, api_key: str | None = None, session: requests.Session | None = None):
        self.api_key = api_key or os.environ.get("MEGABULL_API_KEY", "")
        self.session = session or requests.Session()

    def request(self, method: str, path: str, **kwargs):
        if not self.api_key:
            raise ValueError("MegaBull paper trading is not configured.")
        try:
            response = self.session.request(
                method, BASE_URL + path, headers={"api-key": self.api_key}, timeout=20, **kwargs
            )
        except requests.RequestException:
            message = "MegaBull could not be reached. Retry the data feed later."
            if method.upper() != "GET":
                message = "MegaBull could not be reached. Check provider order history before retrying a submission."
            raise ValueError(message) from None
        if not response.ok:
            # Return provider validation messages, never request headers or credentials.
            try:
                messages = response.json().get("message", [])
                reason = "; ".join(messages) if isinstance(messages, list) else str(messages)
            except (ValueError, AttributeError):
                reason = "Paper trading provider request failed."
            raise ValueError(f"MegaBull HTTP {response.status_code}: {reason}")
        return response.json()

    def account(self):
        result = self.request("GET", "/api/user/my")
        return {key: result.get(key) for key in ("virtualMoney", "virtualMoneyBlocked", "virtualMoneyLeft", "brokerage")}

    @lru_cache(maxsize=1)
    def instruments(self) -> list[dict[str, str]]:
        result = self.request("GET", "/api/marketwatch/instruments")
        url = result.get("downloadUrl", "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "megabull-open.s3.us-east-1.amazonaws.com":
            raise ValueError("MegaBull returned an unexpected instrument download host.")
        # Do not forward the API key to the public CSV host or any redirect.
        response = requests.get(url, timeout=20, allow_redirects=False)
        response.raise_for_status()
        if len(response.content) > 20_000_000:
            raise ValueError("Instrument list exceeds the supported size.")
        return list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))

    def resolve_instrument(self, ticker: str, exchange: str = "NSE") -> str:
        ticker = normalize_symbol(ticker).rsplit('.',1)[0]
        matches = [row for row in self.instruments() if row.get("tradingSymbol", "").upper() == ticker
                   and (not row.get("exchange") or row["exchange"].upper() == exchange)]
        tokens = {row.get("instrumentToken") for row in matches if row.get("instrumentToken")}
        if len(tokens) != 1:
            raise ValueError(f"Cannot uniquely resolve {ticker}; review the provider instrument list.")
        return tokens.pop()

    def quote(self, instrument_token: str):
        return self.request("GET", f"/api/marketwatch/ltp/{instrument_token}")

    def orders(self):
        return self.request("GET", "/api/order/my")

    def positions(self):
        return self.request("GET", "/api/position/my")

    def holdings(self):
        return self.request("GET", "/api/holding/my")

    def submit(self, order: PaperOrder, instrument_token: str):
        payload = {
            "instrumentToken": instrument_token, "qty": order.quantity,
            "type": order.side, "duration": order.duration, "orderType": order.order_type,
        }
        if order.order_type == "LIMIT":
            payload["price"] = order.price
        if order.order_type == "SL":
            payload["triggerPrice"] = order.trigger_price
        return self.request("POST", "/api/order/buysell", json=payload)
