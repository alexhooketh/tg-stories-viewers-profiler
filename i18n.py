from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict


def _detect_locale() -> str:
    """Detect the desired UI language.

    Priority:
    1. The APP_LANG env-var, if set (e.g. "es", "ru").
    2. The system LANG env-var (first two letters).
    3. Fallback to "en".
    """
    env_lang = os.getenv("APP_LANG") or os.getenv("LANG", "en")
    # LANG can be like "en_US.UTF-8" – we only want the language code.
    return env_lang.split(".")[0][:2]


_LOCALE: str = _detect_locale()
_LOCALES_DIR: Path = Path(__file__).with_name("locales")


def _load_translations(locale: str) -> Dict[str, str]:
    """Load the given locale JSON file. Silently falls back to an empty dict."""
    json_path = _LOCALES_DIR / f"{locale}.json"
    if json_path.exists():
        try:
            with json_path.open(encoding="utf-8") as fp:
                data = json.load(fp)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
        except Exception:
            # Malformed file – ignore but keep default behaviour
            pass
    return {}


_TRANSLATIONS: Dict[str, str] = _load_translations(_LOCALE)


def t(message: str, **kwargs) -> str:  # noqa: D401  (simple wrapper)
    """Translate *message* using the loaded locale, formatting placeholders.

    Any keyword arguments are forwarded to ``str.format`` so that placeholders
    inside *message* (e.g. "{count}") are substituted. If a placeholder is
    missing the original template is returned unchanged.
    """
    template = _TRANSLATIONS.get(message, message)
    if kwargs:
        try:
            return template.format(**kwargs)
        except Exception:
            # Fall back to the unformatted template if substitution fails
            return template
    return template
