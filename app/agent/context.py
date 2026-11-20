"""Agent run limits and the trusted per-invoke context type."""

from datetime import datetime
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.confirmations import ConfirmationDecision
from app.agent.llm import ToolCallingChatModel
from app.models.user import User

# Each model/tool round costs about two graph supersteps. This explicit cap is
# enforced in the decision node (and a slightly larger LangGraph recursion
# limit is a second line of defence) so a looping model cannot run unbounded.
MAX_AGENT_STEPS = 12
AGENT_RECURSION_LIMIT = MAX_AGENT_STEPS * 2 + 8


class AgentContext(TypedDict, total=False):
    """Trusted per-invoke inputs from the host: dependencies, session identity,
    the authenticated actor, and the confirmation decision. Nothing here
    round-trips through AgentState."""

    db: AsyncSession
    llm: ToolCallingChatModel
    session_id: str | None
    actor: User | None
    # Patient-account conversation selection, validated by the host against
    # the account's owned records before the graph is invoked.
    selected_patient_id: int | None
    confirmation: ConfirmationDecision
    # Test/host injection only. The HTTP router never accepts this from a
    # client; production leaves it unset so the service uses the real clock.
    now: datetime | None
