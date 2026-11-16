"""CrewAI macOS Sandboxed Storage Environment and Groq Structured Output Patch.
Prevents PermissionError in sandboxed environments, suppresses event context mismatch
warnings, and enables resilient JSON-mode compatibility for Qwen models on Groq.
"""

import json
import os
from pathlib import Path
import re
import appdirs

_PATCHED = False


def ensure_crewai_patched() -> None:
    """Configures safe paths, suppresses noisy event warnings, and patches Groq structured JSON outputs."""
    global _PATCHED
    if _PATCHED:
        return

    storage_dir = Path("/tmp/crewai_storage")
    credentials_dir = Path("/tmp/crewai_credentials")
    storage_dir.mkdir(parents=True, exist_ok=True)
    credentials_dir.mkdir(parents=True, exist_ok=True)

    # 1. Patch appdirs user_data_dir
    appdirs.user_data_dir = lambda *args, **kwargs: str(storage_dir)

    # 2. Patch crewai_core token manager & paths
    try:
        import crewai_core.paths
        import crewai_core.token_manager

        crewai_core.token_manager.TokenManager._get_secure_storage_path = staticmethod(
            lambda: credentials_dir
        )
        crewai_core.paths.db_storage_path = lambda: str(storage_dir)
    except ImportError:
        pass

    # 3. Suppress interactive telemetry prompts in headless / sandboxed environments
    os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"
    try:
        import crewai.events.listeners.tracing.utils

        crewai.events.listeners.tracing.utils._prompt_can_be_shown = lambda: False
        crewai.events.listeners.tracing.utils.prompt_user_for_trace_viewing = lambda *a, **kw: False
    except ImportError:
        pass

    # 4. Suppress CrewAI event pairing mismatch warnings caused by sequential multi-agent tasks
    try:
        from crewai.events.event_context import _default_config, MismatchBehavior

        _default_config.mismatch_behavior = MismatchBehavior.SILENT
        _default_config.empty_pop_behavior = MismatchBehavior.SILENT
    except ImportError:
        pass

    # 5. Patch OpenAICompletion structured output handling for Groq Qwen compatibility
    try:
        from crewai.llms.providers.openai.completion import OpenAICompletion
        from pydantic import BaseModel

        if not getattr(OpenAICompletion, "_kairos_groq_patched", False):
            orig_handle_completion = OpenAICompletion._handle_completion

            def patched_handle_completion(
                self,
                params: dict,
                available_functions=None,
                from_task=None,
                from_agent=None,
                response_model=None,
            ):
                """Routes response_model through standard json_object mode on Groq to prevent json_validate_failed."""
                if response_model is not None:
                    client = self._get_sync_client()
                    call_params = {k: v for k, v in params.items() if k not in ("response_format",)}
                    # Groq JSON mode requires {"type": "json_object"}
                    call_params["response_format"] = {"type": "json_object"}
                    if "temperature" not in call_params or call_params["temperature"] is None:
                        call_params["temperature"] = 0.1

                    chat_completion = client.chat.completions.create(**call_params)
                    choice = chat_completion.choices[0]
                    content = (choice.message.content or "{}").strip()

                    # Strip code fences if present
                    if content.startswith("```json"):
                        content = content[7:]
                    elif content.startswith("```"):
                        content = content[3:]
                    if content.endswith("```"):
                        content = content[:-3]
                    content = content.strip()

                    try:
                        data = json.loads(content)
                    except json.JSONDecodeError as jde:
                        m = re.search(r"(\{.*\})", content, re.DOTALL)
                        if m:
                            data = json.loads(m.group(1))
                        else:
                            raise jde

                    parsed = response_model.model_validate(data)
                    if hasattr(parsed, "execution_mode"):
                        parsed.execution_mode = "LIVE_CREWAI_LLM"

                    usage = self._extract_openai_token_usage(chat_completion)
                    self._track_token_usage_internal(usage)
                    return parsed

                return orig_handle_completion(
                    self,
                    params,
                    available_functions=available_functions,
                    from_task=from_task,
                    from_agent=from_agent,
                    response_model=response_model,
                )

            OpenAICompletion._handle_completion = patched_handle_completion
            OpenAICompletion._kairos_groq_patched = True
    except ImportError:
        pass

    # 6. Patch OutputConverter to avoid redundant failing LLM roundtrips if text is already valid JSON
    try:
        from crewai.utilities.converter import Converter
        from pydantic import BaseModel

        if not getattr(Converter, "_kairos_converter_patched", False):
            orig_to_pydantic = Converter.to_pydantic

            def patched_to_pydantic(self, current_attempt: int = 1):
                try:
                    if isinstance(self.text, BaseModel):
                        return self.text
                    clean_text = (self.text or "").strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:]
                    elif clean_text.startswith("```"):
                        clean_text = clean_text[3:]
                    if clean_text.endswith("```"):
                        clean_text = clean_text[:-3]
                    clean_text = clean_text.strip()
                    m = re.search(r"(\{.*\})", clean_text, re.DOTALL)
                    if m:
                        clean_text = m.group(1)
                    data = json.loads(clean_text)
                    parsed = self.model.model_validate(data)
                    if hasattr(parsed, "execution_mode"):
                        parsed.execution_mode = "LIVE_CREWAI_LLM"
                    return parsed
                except Exception:
                    return orig_to_pydantic(self, current_attempt)

            Converter.to_pydantic = patched_to_pydantic
            Converter._kairos_converter_patched = True
    except ImportError:
        pass

    _PATCHED = True


# Run patch on module load
ensure_crewai_patched()
