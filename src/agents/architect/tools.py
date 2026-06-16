"""Deterministic helper tools for the Architect agent.

Under the project's #2 LLM-access decision the Architect does not run a
``create_react_agent`` tool-loop, so these are plain, well-typed helper
functions (not LangChain ``@tool`` objects) that the agent calls directly:

* :func:`analyze_requirements` — cheap keyword heuristic that pre-classifies the
  request (domain signals + a platform hint) to enrich the LLM prompt.
* :func:`default_folder_structure` — deterministic baseline project layout per
  framework, used as a fallback when the LLM omits the folder structure.
"""

from __future__ import annotations

from typing import Optional

from src.agents.architect.schemas import FolderEntry, FolderStructure, TechStack
from src.orchestrator.state import Platform

# Keyword -> platform bias. Flutter favored for performance/graphics-heavy apps;
# React Native favored for content/commerce/MVP-style apps.
_FLUTTER_SIGNALS = (
    "game", "gaming", "animation", "ar", "vr", "real-time", "realtime",
    "high performance", "performance-critical", "graphics", "60fps", "canvas",
)
_REACT_NATIVE_SIGNALS = (
    "e-commerce", "ecommerce", "shop", "store", "social", "feed", "chat",
    "content", "blog", "mvp", "marketplace", "booking", "delivery",
)


def analyze_requirements(prompt: str) -> dict[str, object]:
    """Heuristically pre-analyze a user request before the LLM call.

    Args:
        prompt: The raw natural-language request.

    Returns:
        A dict with ``suggested_platform`` (``Platform`` or ``None``) and the
        matched ``signals`` for each platform — surfaced to the LLM as context,
        never as a hard override.
    """
    text = prompt.lower()
    flutter_hits = [kw for kw in _FLUTTER_SIGNALS if kw in text]
    rn_hits = [kw for kw in _REACT_NATIVE_SIGNALS if kw in text]

    suggested: Optional[Platform] = None
    if len(flutter_hits) > len(rn_hits):
        suggested = "flutter"
    elif len(rn_hits) > len(flutter_hits):
        suggested = "react-native"

    return {
        "suggested_platform": suggested,
        "flutter_signals": flutter_hits,
        "react_native_signals": rn_hits,
    }


# Per-framework baseline layouts (feature-first, Clean Architecture friendly).
_RN_LAYOUT = [
    ("src/features/", "Feature modules (screens + logic per feature)."),
    ("src/components/", "Shared, reusable UI components."),
    ("src/navigation/", "React Navigation stacks/tabs."),
    ("src/services/", "API clients and external integrations."),
    ("src/store/", "Global state (Redux Toolkit / Zustand) slices."),
    ("src/hooks/", "Reusable custom hooks."),
    ("src/utils/", "Pure helpers and formatters."),
    ("src/theme/", "Design tokens, colors, typography."),
]
_FLUTTER_LAYOUT = [
    ("lib/features/", "Feature modules (presentation + domain + data)."),
    ("lib/core/", "Cross-cutting concerns: errors, network, DI."),
    ("lib/shared/widgets/", "Reusable widgets."),
    ("lib/shared/theme/", "Theme, colors, typography."),
    ("lib/services/", "API clients and platform services."),
    ("lib/routing/", "go_router / navigation configuration."),
]
_GENERIC_LAYOUT = [
    ("src/features/", "Feature modules."),
    ("src/components/", "Shared UI components."),
    ("src/services/", "External integrations."),
    ("src/utils/", "Helpers."),
]


def default_folder_structure(tech_stack: TechStack) -> FolderStructure:
    """Return a sensible baseline layout for the chosen framework.

    Used as a fallback when the LLM returns no folder structure, so the ADR is
    never missing this section.
    """
    framework = tech_stack.framework.lower()
    if "flutter" in framework or tech_stack.platform == "flutter":
        layout = _FLUTTER_LAYOUT
        description = "Feature-first Flutter layout (Clean Architecture)."
    elif "react native" in framework or tech_stack.platform == "react-native":
        layout = _RN_LAYOUT
        description = "Feature-first React Native layout."
    else:
        layout = _GENERIC_LAYOUT
        description = "Generic feature-first layout."

    return FolderStructure(
        description=description,
        entries=[FolderEntry(path=path, purpose=purpose) for path, purpose in layout],
    )
