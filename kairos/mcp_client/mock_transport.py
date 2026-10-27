"""Mock transport providing deterministic responses matching official MCP tool schemas for tests."""

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional


class MockMCPTransport:
    """Simulates responses from existing MCP servers using their exact documented tool interfaces."""

    # Baseline closing prices for Indian benchmark stocks (in INR)
    BASE_PRICES = {
        "RELIANCE": 2750.0,
        "RELIANCE.NS": 2750.0,
        "RELIANCE.BSE": 2748.5,
        "TCS": 3950.0,
        "TCS.NS": 3950.0,
        "TCS.BSE": 3949.0,
        "INFY": 1820.0,
        "INFY.NS": 1820.0,
        "INFY.BSE": 1819.5,
        "HDFCBANK": 1680.0,
        "HDFCBANK.NS": 1680.0,
        "HDFCBANK.BSE": 1679.0,
        "ICICIBANK": 1240.0,
        "ICICIBANK.NS": 1240.0,
        "ICICIBANK.BSE": 1239.5,
    }

    def dispatch(self, server_name: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatches a tool call to the corresponding mock provider."""
        if server_name == "yfinance":
            return self._dispatch_yfinance(tool_name, arguments)
        elif server_name == "nse":
            return self._dispatch_nse(tool_name, arguments)
        elif server_name == "alphavantage":
            return self._dispatch_alphavantage(tool_name, arguments)
        elif server_name == "reddit":
            return self._dispatch_reddit(tool_name, arguments)
        else:
            raise ValueError(f"Unknown server: {server_name}")

    def _dispatch_yfinance(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        symbol = args.get("symbol", "RELIANCE.NS").upper()
        clean_sym = symbol.replace(".NS", "").replace(".BO", "")
        base_price = self.BASE_PRICES.get(symbol, self.BASE_PRICES.get(clean_sym, 1000.0))

        if tool_name == "get_historical_stock_prices":
            period = args.get("period", "10y")
            interval = args.get("interval", "1d")

            # Determine number of trading days (10 years = ~2470 trading days)
            days_count = 2470 if "10y" in period or "max" in period else (252 if "1y" in period else 100)

            bars = []
            start_dt = datetime(2014, 10, 27, tzinfo=timezone.utc)
            curr_price = base_price * 0.45  # 10 years ago starting price

            for i in range(days_count):
                dt = start_dt + timedelta(days=int(i * 1.47))
                # Skip weekends
                if dt.weekday() >= 5:
                    continue

                drift = (i % 7 - 3) * 0.008
                curr_price = max(50.0, curr_price * (1.0 + drift + 0.0003))

                op = round(curr_price * 0.998, 2)
                cl = round(curr_price, 2)
                hi = round(max(op, cl) * 1.012, 2)
                lo = round(min(op, cl) * 0.988, 2)
                adj_cl = round(cl * (0.85 + (i / days_count) * 0.15), 2)
                vol = int(1500000 + (i % 10) * 120000)

                bars.append({
                    "date": dt.strftime("%Y-%m-%d"),
                    "open": op,
                    "high": hi,
                    "low": lo,
                    "close": cl,
                    "adjusted_close": adj_cl,
                    "volume": vol,
                })

            return {
                "symbol": symbol,
                "interval": interval,
                "period": period,
                "count": len(bars),
                "bars": bars,
            }

        elif tool_name == "get_stock_info":
            return {
                "symbol": symbol,
                "shortName": f"{clean_sym} INDIA LTD",
                "currentPrice": base_price,
                "regularMarketPreviousClose": round(base_price * 0.992, 2),
                "regularMarketOpen": round(base_price * 0.995, 2),
                "regularMarketDayHigh": round(base_price * 1.015, 2),
                "regularMarketDayLow": round(base_price * 0.985, 2),
                "regularMarketVolume": 4520300,
                "currency": "INR",
                "exchange": "NSE",
                "marketState": "REGULAR",
                "quoteType": "EQUITY",
                "quoteDelay": "15_MIN_DELAYED",
            }

        elif tool_name == "get_financial_statement":
            return {
                "symbol": symbol,
                "currency": "INR",
                "statement": args.get("statement", "income"),
                "quarterly": args.get("quarterly", False),
                "financials": {
                    "TotalRevenue": 9000000000000 if clean_sym == "RELIANCE" else 2400000000000,
                    "NetIncome": 690000000000 if clean_sym == "RELIANCE" else 460000000000,
                    "TotalAssets": 16000000000000 if clean_sym == "RELIANCE" else 1500000000000,
                    "TotalLiabilities": 8200000000000 if clean_sym == "RELIANCE" else 550000000000,
                    "OperatingCashFlow": 1400000000000 if clean_sym == "RELIANCE" else 480000000000,
                },
            }

        elif tool_name == "get_news":
            return {
                "symbol": symbol,
                "news": [
                    {
                        "title": f"{clean_sym} Reports Strong Quarterly Earnings Across Retail and Enterprise Verticals",
                        "publisher": "The Economic Times",
                        "link": f"https://economictimes.indiatimes.com/markets/stocks/{clean_sym.lower()}-q2-results",
                        "providerPublishTime": int(time.time()) - 3600,
                    },
                    {
                        "title": f"FII Inflows Drive Rally in Nifty Index as {clean_sym} Rebounds",
                        "publisher": "Livemint",
                        "link": f"https://www.livemint.com/market/stock-market-news/{clean_sym.lower()}-fii-inflows",
                        "providerPublishTime": int(time.time()) - 7200,
                    },
                    {
                        "title": f"Motilal Oswal Maintains Buy Rating on {clean_sym} with Target Price Upside",
                        "publisher": "Business Standard",
                        "link": f"https://www.business-standard.com/markets/{clean_sym.lower()}-brokerage-report",
                        "providerPublishTime": int(time.time()) - 14400,
                    },
                ],
            }

        raise NotImplementedError(f"Tool {tool_name} not implemented for yfinance mock.")

    def _dispatch_nse(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        symbol = args.get("symbol", "RELIANCE").upper().replace(".NS", "").replace(".BO", "")
        base_price = self.BASE_PRICES.get(symbol, 1000.0)

        if tool_name == "stock_quote":
            return {
                "symbol": symbol,
                "lastPrice": base_price,
                "change": 14.50,
                "pChange": 0.53,
                "previousClose": round(base_price - 14.50, 2),
                "open": round(base_price - 8.0, 2),
                "dayHigh": round(base_price + 22.0, 2),
                "dayLow": round(base_price - 15.0, 2),
                "totalTradedVolume": 6842100,
                "timestamp": datetime.now(timezone.utc).strftime("%d-%b-%Y %H:%M:%S"),
                "isRealTime": True,
                "marketStatus": "Open",
            }
        elif tool_name == "market_status":
            return {
                "marketState": "Open",
                "market": "Capital Market (Equities)",
                "tradeDate": datetime.now(timezone.utc).strftime("%d-%b-%Y"),
            }
        elif tool_name == "chart_data":
            return {
                "symbol": symbol,
                "points": [
                    {"time": "09:15", "value": round(base_price * 0.995, 2)},
                    {"time": "12:00", "value": round(base_price * 1.005, 2)},
                    {"time": "15:30", "value": base_price},
                ],
            }
        raise NotImplementedError(f"Tool {tool_name} not implemented for nse mock.")

    def _dispatch_alphavantage(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        symbol = args.get("symbol", "RELIANCE.BSE").upper()
        base_price = self.BASE_PRICES.get(symbol, 1000.0)

        if tool_name == "GLOBAL_QUOTE":
            return {
                "Global Quote": {
                    "01. symbol": symbol,
                    "02. open": str(round(base_price * 0.995, 2)),
                    "03. high": str(round(base_price * 1.01, 2)),
                    "04. low": str(round(base_price * 0.99, 2)),
                    "05. price": str(base_price),
                    "06. volume": "124500",
                    "07. latest trading day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "08. previous close": str(round(base_price * 0.99, 2)),
                }
            }
        elif tool_name == "TIME_SERIES_DAILY":
            # Limited 100 days
            ts = {}
            for i in range(100):
                d = (datetime.now(timezone.utc) - timedelta(days=i + 1)).strftime("%Y-%m-%d")
                ts[d] = {
                    "1. open": str(round(base_price * 0.99, 2)),
                    "2. high": str(round(base_price * 1.01, 2)),
                    "3. low": str(round(base_price * 0.98, 2)),
                    "4. close": str(round(base_price, 2)),
                    "5. volume": "150000",
                }
            return {
                "Meta Data": {"2. Symbol": symbol, "Notice": "Compact data limited to 100 days"},
                "Time Series (Daily)": ts,
            }
        raise NotImplementedError(f"Tool {tool_name} not implemented for alphavantage mock.")

    def _dispatch_reddit(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        sub = args.get("subreddit", "IndianStockMarket")
        query = args.get("query", "RELIANCE")
        now = time.time()

        posts = [
            {
                "id": "ind_post_001",
                "title": f"Institutional buying in {query} ahead of quarterly board meeting",
                "selftext": f"Delivery percentages for {query} spiked above 65% on NSE today.",
                "score": 185,
                "num_comments": 42,
                "subreddit": sub,
                "permalink": f"/r/{sub}/comments/ind_post_001/{query.lower()}_analysis/",
                "created_utc": now - 3600,
            },
            {
                "id": "ind_post_002",
                "title": f"Technical breakout setup on {query} weekly chart",
                "selftext": "Consolidating near all-time high with expanding volumes.",
                "score": 94,
                "num_comments": 18,
                "subreddit": sub,
                "permalink": f"/r/{sub}/comments/ind_post_002/{query.lower()}_breakout/",
                "created_utc": now - 7200,
            },
            {
                "id": "ind_post_003",
                "title": f"Long-term SIP review: Weightage of {query} in large cap portfolio",
                "selftext": "Evaluating dividend yield and ROCE compared to peers.",
                "score": 240,
                "num_comments": 65,
                "subreddit": sub,
                "permalink": f"/r/{sub}/comments/ind_post_003/{query.lower()}_sip_discussion/",
                "created_utc": now - 14400,
            },
        ]
        return {"subreddit": sub, "posts": posts}
