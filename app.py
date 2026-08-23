"""ParcelPilot Streamlit application entrypoint."""

from __future__ import annotations

import streamlit as st

from src.config import settings
from src.ui.integration import (
    available_users,
    confirm_pending,
    confirmation_details,
    get_user,
    reject_pending,
    prepare_issue_escalation,
    scan_issues,
    start_investigation,
    user_changed,
)


st.set_page_config(page_title="ParcelPilot AI", page_icon="P", layout="wide")


def _initialize_state() -> None:
    if "authenticated_user" not in st.session_state:
        st.session_state.authenticated_user = available_users()[0]
    for key, default in {
        "conversation": [],
        "current_agent_state": {},
        "pending_confirmation": None,
        "confirmation_id": None,
        "last_action_result": None,
        "operational_issues": None,
        "selected_user_id": st.session_state.authenticated_user.user_id,
    }.items():
        st.session_state.setdefault(key, default)


def _render_sidebar() -> None:
    with st.sidebar:
        st.title("ParcelPilot AI")
        users = available_users()
        labels = {user.user_id: user for user in users}
        selected_id = st.selectbox(
            "Authenticated user",
            options=list(labels),
            index=list(labels).index(st.session_state.selected_user_id),
            format_func=lambda value: labels[value].role.replace("_", " ").title(),
        )
        if user_changed(st.session_state.selected_user_id, selected_id):
            st.session_state.selected_user_id = selected_id
            st.session_state.authenticated_user = get_user(selected_id)
            st.session_state.pending_confirmation = None
            st.session_state.confirmation_id = None
            st.session_state.current_agent_state = {}
            st.session_state.last_action_result = None
            st.session_state.operational_issues = None
            st.rerun()

        user = st.session_state.authenticated_user
        st.caption(f"User: {user.user_id}")
        st.caption(f"Role: {user.role}")
        st.caption("Permissions")
        for permission in sorted(user.permissions):
            st.write(f"- {permission}")
        if st.button("Clear conversation", use_container_width=True):
            st.session_state.conversation = []
            st.session_state.current_agent_state = {}
            st.session_state.pending_confirmation = None
            st.session_state.confirmation_id = None
            st.session_state.last_action_result = None
            st.session_state.operational_issues = None
            st.rerun()
        if st.button("Scan for Issues", use_container_width=True):
            st.session_state.operational_issues = scan_issues(st.session_state.authenticated_user)
            st.rerun()


def _render_evidence(sources: list[dict]) -> None:
    if not sources:
        return
    with st.expander("Evidence", expanded=False):
        for source in sources:
            st.markdown(
                f"**{source.get('document', 'Unknown document')}** · page {source.get('page', '?')}  "
                f"· {source.get('source_type', 'unknown')} · {source.get('status', 'unknown')}  "
                f"· authority {source.get('authority', '?')}"
            )
            st.caption(source.get("text", "")[:320])


def _render_data(tool_results: list[dict]) -> None:
    if not tool_results:
        return
    with st.expander("Data", expanded=False):
        tools_used = list(dict.fromkeys(item.get("tool") for item in tool_results if item.get("tool")))
        if tools_used:
            st.markdown("**Tools used:**")
            for tool in tools_used:
                st.write(f"- {tool}")
        records = [item for item in tool_results if item.get("tool", "").startswith("lookup_")]
        for record in records:
            st.json(record.get("result", {}), expanded=False)


def _render_issues() -> None:
    issues = st.session_state.get("operational_issues")
    if issues is None:
        return
    st.subheader("Proactive Issues")
    if isinstance(issues, dict) and issues.get("error"):
        st.error(issues["error"])
        return
    if not issues:
        st.success("No operational issues detected.")
        return
    for issue in issues:
        st.warning(f"{issue['severity'].upper()}: {issue['title']}")
        st.write(issue["description"])
        affected = [
            f"{label}: {issue[key]}"
            for label, key in (("Account", "account_id"), ("Order", "order_id"), ("Ticket", "ticket_id"))
            if issue.get(key)
        ]
        if affected:
            st.caption(" · ".join(affected))
        with st.expander("Issue evidence", expanded=False):
            st.json(issue.get("evidence", {}), expanded=False)
        if issue.get("recommended_action") == "create_escalation":
            st.info("Recommended action: Create escalation. Review the finding in the chat before requesting confirmation.")
            if issue.get("ticket_id") and st.button("Review / Prepare Escalation", key=f"prepare_{issue['issue_id']}"):
                result = prepare_issue_escalation(issue, st.session_state.authenticated_user)
                if result.get("confirmation_id"):
                    st.session_state.current_agent_state = {
                        "pending_action": result["pending_action"],
                        "confirmation_required": True,
                        "confirmation_status": result["confirmation_status"],
                        "confirmation_id": result["confirmation_id"],
                    }
                    st.session_state.pending_confirmation = result["pending_action"]
                    st.session_state.confirmation_id = result["confirmation_id"]
                    st.rerun()
                else:
                    st.error(result.get("message", result.get("error", "Could not prepare escalation.")))


def _render_confirmation() -> None:
    details = confirmation_details(st.session_state.current_agent_state)
    if not details:
        return
    st.warning("Action requires confirmation")
    st.write(f"Action: {details.get('action')}")
    st.write(f"Ticket ID: {details.get('ticket_id')}")
    st.write(f"Reason: {details.get('reason')}")
    st.write(f"Priority: {details.get('priority')}")
    st.write(f"Confirmation ID: {details.get('confirmation_id')}")
    st.write(f"Requesting user: {details.get('requested_by')}")
    confirm, reject = st.columns(2)
    with confirm:
        if st.button("Confirm", type="primary", key="confirm_action"):
            result = confirm_pending(
                st.session_state.confirmation_id,
                st.session_state.authenticated_user,
            )
            st.session_state.last_action_result = result
            status = result.get("confirmation_status")
            if status:
                st.session_state.current_agent_state["confirmation_status"] = status
            st.rerun()
    with reject:
        if st.button("Reject", key="reject_action"):
            result = reject_pending(
                st.session_state.confirmation_id,
                st.session_state.authenticated_user,
            )
            st.session_state.last_action_result = result
            status = result.get("confirmation_status")
            if status:
                st.session_state.current_agent_state["confirmation_status"] = status
            st.rerun()


def main() -> None:
    _initialize_state()
    _render_sidebar()
    user = st.session_state.authenticated_user
    st.title("ParcelPilot AI")
    st.caption("Internal support and operations investigation")
    _render_issues()

    if not settings.llm_provider or not settings.llm_model or not settings.llm_api_key:
        st.info("LLM is not configured. Set LLM_PROVIDER, LLM_MODEL, and LLM_API_KEY to enable investigations.")

    for message in st.session_state.conversation:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                _render_evidence(message.get("sources", []))
                _render_data(message.get("tool_results", []))

    _render_confirmation()

    question = st.chat_input("Ask ParcelPilot about an account, order, ticket, or policy")
    if question:
        st.session_state.conversation.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        result = start_investigation(question, user)
        if "error" in result:
            st.session_state.conversation.append({"role": "assistant", "content": result["error"]})
            with st.chat_message("assistant"):
                st.error(result["error"])
            return

        st.session_state.current_agent_state = result
        st.session_state.pending_confirmation = result.get("pending_action")
        st.session_state.confirmation_id = result.get("confirmation_id")
        st.session_state.conversation.append(
            {
                "role": "assistant",
                "content": result.get("final_answer", "No answer was produced."),
                "sources": result.get("sources", []),
                "tool_results": result.get("tool_results", []),
            }
        )
        st.rerun()

    if st.session_state.last_action_result:
        result = st.session_state.last_action_result
        if result.get("error"):
            st.error(result.get("message", result["error"]))
        elif result.get("confirmation_status") == "used":
            st.success("Escalation created successfully.")
        elif result.get("confirmation_status") == "rejected":
            st.info("Escalation rejected. No action was taken.")
        elif result.get("confirmation_status") == "expired":
            st.warning("Confirmation expired. Please request the action again.")


if __name__ == "__main__":
    main()
