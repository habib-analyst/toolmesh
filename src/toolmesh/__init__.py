"""toolmesh: multi-tool orchestration with dry-run effect simulation.

Public API: Registry, ToolSpec, PlannedCall, EffectSet, AgentContext,
Workspace, Orchestrator, default_registry.
"""

from .model import EffectSet, PlannedCall, ToolSpec
from .orchestrator import Orchestrator, RunOutcome
from .registry import Registry
from .resolver import Resolution, resolve
from .scopes import AgentContext
from .tools import default_registry
from .workspace import Workspace

__all__ = [
    "AgentContext",
    "EffectSet",
    "Orchestrator",
    "PlannedCall",
    "Registry",
    "Resolution",
    "RunOutcome",
    "ToolSpec",
    "Workspace",
    "default_registry",
    "resolve",
]

__version__ = "0.1.0"
