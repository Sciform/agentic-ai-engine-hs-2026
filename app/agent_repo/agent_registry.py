"""Agent registry – maps agent_id to LlmAgent instances and display metadata.

To add a new agent:
  1. Create a new sub-package under agent_repo/
  2. Import the agent here
  3. Add an entry to AGENT_REGISTRY
"""

from google.adk.agents import LlmAgent

from app.agent_repo.greeting_agent import greeting_agent


AGENT_REGISTRY: dict[str, dict] = {
    "greeting_agent": {
        "agent": greeting_agent,
        "label": "Welcome",
        "description": "Welcomes students and helps them get started.",
        "icon": "👋",
    },
}


def get_agent(agent_id: str) -> LlmAgent:
    """Look up an agent by ID. Raises KeyError if not found."""
    entry = AGENT_REGISTRY[agent_id]
    return entry["agent"]


def list_agents() -> list[dict]:
    """Return metadata for all registered agents (for the UI).

    The UI also understands the optional flags ``has_artifacts``,
    ``has_memory`` and ``has_rag``; when set to True it shows the
    corresponding panel for that agent.
    """
    return [
        {
            "id": agent_id,
            "label": meta["label"],
            "description": meta["description"],
            "icon": meta["icon"],
        }
        for agent_id, meta in AGENT_REGISTRY.items()
    ]
