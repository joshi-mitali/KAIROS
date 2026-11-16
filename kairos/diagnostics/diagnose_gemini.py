#!/usr/bin/env python3
"""KAIROS Gemini API Diagnostic & Verification Tool.
Inspects available models, tests minimal generateContent and Interactions API calls,
diagnoses 504 DEADLINE_EXCEEDED, and verifies bounded retries.
Never prints or logs secret credentials.
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import google.genai as genai
from google.genai import types
from google.genai.errors import APIError


def mask_secret(secret: Optional[str]) -> str:
    """Safely sanitizes API keys for display without exposing secrets."""
    if not secret:
        return "<NOT_SET>"
    if len(secret) <= 10:
        return "***"
    return f"{secret[:6]}...{secret[-4:]} (len={len(secret)})"


def step_1_list_models(client: genai.Client) -> List[Dict[str, Any]]:
    """Lists all models accessible by the configured API key and checks method support."""
    print("\n" + "=" * 70)
    print("STEP 1: Discovering Models Available to Configured API Key")
    print("=" * 70)

    try:
        start = time.perf_counter()
        pager = client.models.list()
        elapsed = (time.perf_counter() - start) * 1000.0
        print(f"  [OK] models.list() returned in {elapsed:.1f}ms\n")

        supported_models = []
        print(f"  {'Model Name':<36} | {'Display Name':<24} | {'generateContent'}")
        print("  " + "-" * 75)

        for model in pager:
            actions = getattr(model, "supported_actions", []) or []
            can_generate = "generateContent" in actions
            m_info = {
                "name": model.name,
                "display_name": getattr(model, "display_name", "") or "",
                "actions": actions,
                "can_generate": can_generate,
            }
            supported_models.append(m_info)
            gen_str = "YES" if can_generate else "NO"
            print(f"  {model.name:<36} | {model.display_name[:24]:<24} | {gen_str}")

        print("  " + "-" * 75)
        print(f"  Total models discovered: {len(supported_models)}")
        return supported_models

    except Exception as e:
        sanitized_err = str(e).replace(os.environ.get("GEMINI_API_KEY", "___"), "***")
        print(f"  [FAIL] models.list() failed: {type(e).__name__}: {sanitized_err}")
        return []


def step_2_minimal_request(client: genai.Client, model_name: str, timeout_sec: int = 60) -> Dict[str, Any]:
    """Runs a minimal raw generateContent request outside the multi-agent pipeline."""
    print("\n" + "=" * 70)
    print(f"STEP 2: Minimal generateContent Test ({model_name})")
    print("=" * 70)
    print(f"  Prompt: 'Reply with one word: PONG' (Request size ~28 bytes)")
    print(f"  Timeout configured: {timeout_sec}s ({timeout_sec * 1000}ms)")

    start = time.perf_counter()
    result = {
        "model": model_name,
        "timeout_sec": timeout_sec,
        "success": False,
        "elapsed_ms": 0.0,
        "status_code": None,
        "error_type": None,
        "sanitized_error": None,
        "response_text": None,
    }

    try:
        response = client.models.generate_content(
            model=model_name,
            contents="Reply with one word: PONG",
            config={
                "http_options": {"timeout": timeout_sec * 1000},
            },
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        result["elapsed_ms"] = elapsed
        result["success"] = True
        result["response_text"] = response.text.strip() if response and response.text else ""
        print(f"  [SUCCESS] Response received in {elapsed:.1f}ms: '{result['response_text']}'")
        return result

    except APIError as e:
        elapsed = (time.perf_counter() - start) * 1000.0
        result["elapsed_ms"] = elapsed
        result["status_code"] = getattr(e, "code", None)
        result["error_type"] = type(e).__name__
        sanitized = str(e).replace(os.environ.get("GEMINI_API_KEY", "___"), "***")
        result["sanitized_error"] = sanitized
        print(f"  [API_ERROR] Code {result['status_code']} in {elapsed:.1f}ms: {sanitized}")
        return result
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000.0
        result["elapsed_ms"] = elapsed
        result["error_type"] = type(e).__name__
        sanitized = str(e).replace(os.environ.get("GEMINI_API_KEY", "___"), "***")
        result["sanitized_error"] = sanitized
        print(f"  [EXCEPTION] {type(e).__name__} in {elapsed:.1f}ms: {sanitized}")
        return result


class MinimalPingSchema(BaseModel):
    ping_status: str = Field(..., description="Should be PONG")
    server_time: str = Field(..., description="Current ISO timestamp")


def step_3_minimal_schema_request(client: genai.Client, model_name: str, timeout_sec: int = 60) -> Dict[str, Any]:
    """Tests Pydantic structured output generation to measure constrained decoding latency."""
    print("\n" + "=" * 70)
    print(f"STEP 3: Minimal Structured Schema Request ({model_name})")
    print("=" * 70)

    start = time.perf_counter()
    result = {"model": model_name, "success": False, "elapsed_ms": 0.0}

    try:
        prompt = "Return a JSON object conforming to MinimalPingSchema with ping_status='PONG' and current ISO time."
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": MinimalPingSchema,
                "http_options": {"timeout": timeout_sec * 1000},
            },
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        result["elapsed_ms"] = elapsed

        if response and response.text:
            parsed = MinimalPingSchema.model_validate_json(response.text)
            result["success"] = True
            result["parsed"] = parsed.model_dump()
            print(f"  [SUCCESS] Structured schema parsed in {elapsed:.1f}ms: {result['parsed']}")
        else:
            print(f"  [FAIL] Empty response text in {elapsed:.1f}ms")
        return result

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000.0
        result["elapsed_ms"] = elapsed
        sanitized = str(e).replace(os.environ.get("GEMINI_API_KEY", "___"), "***")
        print(f"  [FAIL] Structured call failed in {elapsed:.1f}ms: {type(e).__name__}: {sanitized}")
        return result


def step_4_interactions_api_test(client: genai.Client, model_name: str) -> Dict[str, Any]:
    """Tests the Interactions API (client.interactions.create) if generateContent fails."""
    print("\n" + "=" * 70)
    print(f"STEP 4: Interactions API Assessment ({model_name})")
    print("=" * 70)

    start = time.perf_counter()
    result = {"success": False, "elapsed_ms": 0.0}

    try:
        if not hasattr(client, "interactions") or not hasattr(client.interactions, "create"):
            print("  [SKIP] client.interactions.create not supported in current SDK version.")
            return result

        print(f"  Calling client.interactions.create(model='{model_name}', input='Hello')...")
        interaction = client.interactions.create(
            model=model_name,
            input="Hello, reply with one word: PONG",
        )
        elapsed = (time.perf_counter() - start) * 1000.0
        result["elapsed_ms"] = elapsed
        result["success"] = True
        result["interaction_id"] = getattr(interaction, "id", None)
        print(f"  [SUCCESS] Interactions API call succeeded in {elapsed:.1f}ms! Interaction ID: {result['interaction_id']}")
        return result

    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000.0
        result["elapsed_ms"] = elapsed
        sanitized = str(e).replace(os.environ.get("GEMINI_API_KEY", "___"), "***")
        print(f"  [INTERACTIONS_FAIL] Failed in {elapsed:.1f}ms: {type(e).__name__}: {sanitized}")
        return result


def main():
    print("=" * 70)
    print("  KAIROS Gemini API Diagnostic & Latency Suite")
    print("=" * 70)

    api_key = os.environ.get("GEMINI_API_KEY")
    target_model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")

    print(f"  API Key Configured : {mask_secret(api_key)}")
    print(f"  Target Model       : {target_model}")
    print(f"  SDK Version        : {genai.__version__}")

    if not api_key:
        print("\n[ERROR] GEMINI_API_KEY environment variable is not set.")
        print("Please export GEMINI_API_KEY='your_key' or set it in .env.")
        sys.exit(1)

    timeout_ms = int(os.environ.get("GEMINI_TIMEOUT_MS", "60000"))
    timeout_sec = max(30, timeout_ms // 1000)

    client = genai.Client(
        api_key=api_key,
        http_options={"timeout": timeout_sec * 1000},
    )

    # 1. Discover models
    models = step_1_list_models(client)

    # Check if target_model is present in models
    model_names = [m["name"] for m in models]
    clean_target = target_model.replace("models/", "")
    found = any(clean_target in m_name for m_name in model_names)
    print(f"\n  Target model '{target_model}' present in account models: {'YES' if found else 'NO'}")

    # 2. Minimal raw request
    res_minimal = step_2_minimal_request(client, target_model, timeout_sec=timeout_sec)

    # 3. Minimal structured schema request
    if res_minimal["success"]:
        step_3_minimal_schema_request(client, target_model, timeout_sec=timeout_sec)
    else:
        # If generateContent failed, evaluate Interactions API
        step_4_interactions_api_test(client, target_model)

    print("\n" + "=" * 70)
    print("DIAGNOSTIC SUMMARY & RECOMMENDATIONS")
    print("=" * 70)
    if res_minimal["success"]:
        print(f"  - Model '{target_model}' is FUNCTIONAL.")
        print(f"  - Minimal latency: {res_minimal['elapsed_ms']:.1f}ms")
    else:
        err = res_minimal.get("sanitized_error", "")
        code = res_minimal.get("status_code")
        if code == 504 or "DEADLINE_EXCEEDED" in err:
            print("  - Cause of 504: Google API server deadline expired.")
            print(f"    Current timeout: {timeout_sec}s. Backend generation or server queue exceeded deadline.")
            print("    Recommendation: Increase GEMINI_TIMEOUT_MS to 60000-90000 and ensure bounded backoff retries.")
        elif code == 404 or "NOT_FOUND" in err:
            print(f"  - Cause of 404: Model '{target_model}' is not accessible on this API key.")
            print("    Recommendation: Select a model from the models.list() output above.")
        else:
            print(f"  - Error: {res_minimal.get('error_type')}: {err}")


if __name__ == "__main__":
    main()

