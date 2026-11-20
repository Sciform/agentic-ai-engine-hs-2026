"""Agent repository – central registry of all available agents."""

from .agent_registry import AGENT_REGISTRY, get_agent, list_agents
from .greeting_agent import greeting_agent

__all__ = [
	"greeting_agent",
	"AGENT_REGISTRY",
	"get_agent",
	"list_agents",
]
