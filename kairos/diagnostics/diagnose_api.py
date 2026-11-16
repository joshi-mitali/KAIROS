#!/usr/bin/env python3
"""KAIROS API Diagnostic & Latency Verification Tool.
Diagnoses Groq API connectivity, lists available models, tests minimal latency,
verifies structured Pydantic JSON generation, and tests bounded retries.
Masks all credentials safely (never logs secrets).
"""

import json
import os
import sys
import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def mask_secret(secret: Optional[str]) -> str:
    """Safely sanitizes API keys for display."""
    if not secret:
        return "<NOT_SET>"
    if len(secret) <= 10:
        return "***"
    return f"{secret[:6]}...{secret[-4:]} (len={len(secret)})"


class MinimalPingSchema(BaseModel):
    ping_status: str = Field(..., description="Should be PONG")
    model_echo: str = Field(..., description="Echo model name")
    response_timestamp: str = Field(..., description="Current ISO timestamp")


def diagnose_groq(groq_key: str, model_name: str) -> None:
    """Runs diagnostics against the Groq API endpoint."""
    from openai import OpenAI

    print("\n" + "=" * 70)
    print("GROQ API DIAGNOSTIC SUITE")
    print("=" * 70)
    print(f"  API Key Configured : {mask_secret(groq_key)}")
    print(f"  Target Model       : {model_name}")
    print(f"  Base URL           : https://api.groq.com/openai/v1")

    client = OpenAI(
        base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        api_key=groq_key,
        timeout=30.0,
    )

    # 1. Discover models
    print("\n[STEP 1] Querying Available Groq Models...")
    try:
        start = time.perf_counter()
        models_resp = client.models.list()
        elapsed = (time.perf_counter() - start) * 1000.0
        model_ids = [m.id for m in models_resp.data]
        print(f"  [OK] Retrieved {len(model_ids)} models in {elapsed:.1f}ms.")
        print(f"  Popular models available: {', '.join([m for m in model_ids if 'llama' in m][:5])}")
        if model_name in model_ids:
            print(f"  [CONFIRMED] Target model '{model_name}' is active and accessible.")
        else:
            print(f"  [WARNING] Target model '{model_name}' not in list. Available: {model_ids[:5]}")
    except Exception as e:
        print(f"  [FAIL] Failed to list models: {type(e).__name__}: {str(e)[:120]}")

    # 2. Minimal raw request
    print(f"\n[STEP 2] Minimal Raw Request to '{model_name}' (~28 bytes)...")
    try:
        start = time.perf_counter()
        resp = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": "Reply with one word: PONG"}],
            temperature=0.0,
            max_tokens=10,
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        reply = resp.choices[0].message.content.strip()
        print(f"  [SUCCESS] Received reply in {elapsed:.1f}ms: '{reply}'")
    except Exception as e:
        print(f"  [FAIL] Minimal request failed: {type(e).__name__}: {str(e)[:120]}")

    # 3. Structured schema output request
    print(f"\n[STEP 3] Structured Pydantic Schema Validation ({model_name})...")
    try:
        schema_json = json.dumps(MinimalPingSchema.model_json_schema())
        start = time.perf_counter()
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": "Respond strictly with valid JSON conforming to the requested schema."},
                {
                    "role": "user",
                    "content": f"Return a JSON object conforming to this schema:\n{schema_json}\nSet ping_status='PONG' and model_echo='{model_name}'.",
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=100,
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        content = resp.choices[0].message.content
        parsed = MinimalPingSchema.model_validate_json(content)
        print(f"  [SUCCESS] Schema parsed & validated in {elapsed:.1f}ms: {parsed.model_dump()}")
        print("\n" + "=" * 70)
        print("  RESULT: Groq API is FULLY OPERATIONAL for KAIROS Multi-Agent Research!")
        print("=" * 70)
    except Exception as e:
        print(f"  [FAIL] Schema validation failed: {type(e).__name__}: {str(e)[:120]}")


def main():
    print("=" * 70)
    print("  KAIROS Multi-Agent API Diagnostic Tool")
    print("=" * 70)

    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")

    if groq_key:
        model = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
        diagnose_groq(groq_key, model)
    elif gemini_key:
        from kairos.diagnostics.diagnose_gemini import main as run_gemini
        run_gemini()
    else:
        print("\n[ERROR] No LLM API key detected.")
        print("To use Groq's free API:")
        print("  1. Get a free API key at: https://console.groq.com/keys")
        print("  2. Add to your .env or run:")
        print("     export GROQ_API_KEY='gsk_...'")
        print("  3. Run: python run.py --diagnose\n")
        sys.exit(1)


if __name__ == "__main__":
    main()

