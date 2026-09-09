from __future__ import annotations

from app.extensions import db
from app.models import Workflow, WorkflowEdge, WorkflowNode, utcnow
from app.services.display_service import current_ui_copy

NODE_TYPES = [
    "start",
    "user_action",
    "agent_action",
    "tool_call",
    "decision",
    "confidence_check",
    "system_message",
    "escalation",
    "error",
    "end",
]


def node_to_dict(node: WorkflowNode) -> dict:
    config = node.configuration_json or {}
    return {
        "id": node.id,
        "node_type": node.node_type,
        "label": node.label,
        "description": node.description,
        "actor": node.actor,
        "expected_input": config.get("expected_input", ""),
        "expected_output": config.get("expected_output", ""),
        "data_accessed": config.get("data_accessed", ""),
        "permission_level": config.get("permission_level", ""),
        "confidence_behavior": config.get("confidence_behavior", ""),
        "user_visible_status": config.get("user_visible_status", ""),
        "recovery_behavior": config.get("recovery_behavior", ""),
        "position_x": node.position_x,
        "position_y": node.position_y,
        "created_at": node.created_at.isoformat() if node.created_at else "",
        "updated_at": node.updated_at.isoformat() if node.updated_at else "",
    }


def edge_to_dict(edge: WorkflowEdge) -> dict:
    return {
        "id": edge.id,
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "condition_label": current_ui_copy(edge.condition_label),
        "priority": edge.priority,
        "is_default": edge.is_default,
    }


def serialize_workflow(workflow: Workflow) -> dict:
    return {
        "id": workflow.id,
        "name": workflow.name,
        "version_number": workflow.version_number,
        "status": workflow.status,
        "viewport": workflow.viewport_json or {},
        "nodes": [node_to_dict(node) for node in workflow.nodes],
        "edges": [edge_to_dict(edge) for edge in workflow.edges],
    }


def update_node_from_payload(node: WorkflowNode, payload: dict) -> WorkflowNode:
    for field in ["node_type", "label", "description", "actor"]:
        if field in payload:
            setattr(node, field, str(payload[field])[:2000])
    if "position_x" in payload:
        node.position_x = float(payload["position_x"])
    if "position_y" in payload:
        node.position_y = float(payload["position_y"])
    config = dict(node.configuration_json or {})
    for field in [
        "expected_input",
        "expected_output",
        "data_accessed",
        "permission_level",
        "confidence_behavior",
        "user_visible_status",
        "recovery_behavior",
    ]:
        if field in payload:
            config[field] = str(payload[field])
    node.configuration_json = config
    node.updated_at = utcnow()
    return node


def create_workflow_node(workflow: Workflow, node_type: str, label: str, x: float, y: float) -> WorkflowNode:
    if node_type not in NODE_TYPES:
        raise ValueError("Unsupported workflow node type.")
    node = WorkflowNode(
        workflow=workflow,
        node_type=node_type,
        label=label.strip() or node_type.replace("_", " ").title(),
        actor=default_actor_for_type(node_type),
        position_x=x,
        position_y=y,
        configuration_json={
            "expected_input": "",
            "expected_output": "",
            "data_accessed": "",
            "permission_level": "review",
            "confidence_behavior": "",
            "user_visible_status": "",
            "recovery_behavior": "",
        },
    )
    db.session.add(node)
    return node


def default_actor_for_type(node_type: str) -> str:
    return {
        "start": "System",
        "user_action": "Human",
        "agent_action": "Agent",
        "tool_call": "Tool",
        "decision": "Human",
        "confidence_check": "Agent",
        "system_message": "System",
        "escalation": "Human",
        "error": "System",
        "end": "System",
    }.get(node_type, "System")


def create_workflow_edge(
    workflow: Workflow,
    source_node_id: str,
    target_node_id: str,
    condition_label: str,
    priority: int = 0,
    is_default: bool = False,
) -> WorkflowEdge:
    node_ids = {node.id for node in workflow.nodes}
    if source_node_id not in node_ids or target_node_id not in node_ids:
        raise ValueError("Both workflow nodes must exist in this workflow.")
    edge = WorkflowEdge(
        workflow=workflow,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        condition_label=condition_label.strip() or "Next",
        priority=priority,
        is_default=bool(is_default),
    )
    db.session.add(edge)
    return edge
