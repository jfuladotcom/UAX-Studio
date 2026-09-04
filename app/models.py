import uuid
from datetime import datetime, timezone

from sqlalchemy import UniqueConstraint

from app.extensions import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


class TimestampMixin:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Project(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    name = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), nullable=False, unique=True)
    description = db.Column(db.Text, default="", nullable=False)
    workflow_name = db.Column(db.String(160), default="", nullable=False)
    target_user = db.Column(db.String(240), default="", nullable=False)
    desired_outcome = db.Column(db.Text, default="", nullable=False)
    stage = db.Column(db.String(40), default="draft", nullable=False)
    status = db.Column(db.String(40), default="active", nullable=False)
    archived_at = db.Column(db.DateTime(timezone=True), nullable=True)

    source_documents = db.relationship(
        "SourceDocument", back_populates="project", cascade="all, delete-orphan"
    )
    synthesis_items = db.relationship(
        "SynthesisItem", back_populates="project", cascade="all, delete-orphan"
    )
    contracts = db.relationship(
        "ExperienceContract",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ExperienceContract.version_number",
    )
    workflows = db.relationship(
        "Workflow", back_populates="project", cascade="all, delete-orphan", order_by="Workflow.version_number"
    )
    review_runs = db.relationship("ReviewRun", back_populates="project", cascade="all, delete-orphan")
    findings = db.relationship("Finding", back_populates="project", cascade="all, delete-orphan")
    exports = db.relationship("ExportRecord", back_populates="project", cascade="all, delete-orphan")
    activity_events = db.relationship(
        "ActivityEvent",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="desc(ActivityEvent.created_at)",
    )

    @property
    def active_contract(self):
        return self.contracts[-1] if self.contracts else None

    @property
    def active_workflow(self):
        return self.workflows[-1] if self.workflows else None


class SourceDocument(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, default="", nullable=False)
    source_type = db.Column(db.String(40), nullable=False)
    original_filename = db.Column(db.String(260), default="", nullable=False)
    stored_filename = db.Column(db.String(260), default="", nullable=False)
    mime_type = db.Column(db.String(120), default="", nullable=False)
    file_size = db.Column(db.Integer, default=0, nullable=False)
    extracted_text = db.Column(db.Text, default="", nullable=False)
    edited_text = db.Column(db.Text, default="", nullable=False)
    extraction_status = db.Column(db.String(40), default="ready", nullable=False)
    extraction_error = db.Column(db.Text, default="", nullable=False)

    project = db.relationship("Project", back_populates="source_documents")
    synthesis_items = db.relationship("SynthesisItem", back_populates="source_document")


class SynthesisItem(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    text = db.Column(db.Text, nullable=False)
    source_document_id = db.Column(
        db.String(36), db.ForeignKey("source_document.id", ondelete="SET NULL"), nullable=True
    )
    source_locator = db.Column(db.String(240), nullable=True)
    is_inference = db.Column(db.Boolean, default=False, nullable=False)
    confidence = db.Column(db.String(40), default="medium", nullable=False)
    inclusion_status = db.Column(db.String(40), default="included", nullable=False)
    # Kept for databases created before inclusion_status replaced approval flags.
    is_approved = db.Column(db.Boolean, default=True, nullable=False)

    project = db.relationship("Project", back_populates="synthesis_items")
    source_document = db.relationship("SourceDocument", back_populates="synthesis_items")


class ExperienceContract(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    version_number = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(40), default="draft", nullable=False)
    content_json = db.Column(db.JSON, default=dict, nullable=False)

    project = db.relationship("Project", back_populates="contracts")

    __table_args__ = (UniqueConstraint("project_id", "version_number", name="uq_contract_version"),)


class Workflow(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    version_number = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(40), default="draft", nullable=False)
    viewport_json = db.Column(db.JSON, default=dict, nullable=False)

    project = db.relationship("Project", back_populates="workflows")
    nodes = db.relationship(
        "WorkflowNode", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowNode.created_at"
    )
    edges = db.relationship(
        "WorkflowEdge", back_populates="workflow", cascade="all, delete-orphan", order_by="WorkflowEdge.priority"
    )

    __table_args__ = (UniqueConstraint("project_id", "version_number", name="uq_workflow_version"),)


class WorkflowNode(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    workflow_id = db.Column(db.String(36), db.ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False)
    node_type = db.Column(db.String(60), nullable=False)
    label = db.Column(db.String(160), nullable=False)
    description = db.Column(db.Text, default="", nullable=False)
    actor = db.Column(db.String(80), default="", nullable=False)
    configuration_json = db.Column(db.JSON, default=dict, nullable=False)
    position_x = db.Column(db.Float, default=0, nullable=False)
    position_y = db.Column(db.Float, default=0, nullable=False)

    workflow = db.relationship("Workflow", back_populates="nodes")
    outgoing_edges = db.relationship(
        "WorkflowEdge",
        foreign_keys="WorkflowEdge.source_node_id",
        back_populates="source_node",
        cascade="all, delete-orphan",
    )
    incoming_edges = db.relationship(
        "WorkflowEdge",
        foreign_keys="WorkflowEdge.target_node_id",
        back_populates="target_node",
        cascade="all, delete-orphan",
    )


class WorkflowEdge(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    workflow_id = db.Column(db.String(36), db.ForeignKey("workflow.id", ondelete="CASCADE"), nullable=False)
    source_node_id = db.Column(
        db.String(36), db.ForeignKey("workflow_node.id", ondelete="CASCADE"), nullable=False
    )
    target_node_id = db.Column(
        db.String(36), db.ForeignKey("workflow_node.id", ondelete="CASCADE"), nullable=False
    )
    condition_label = db.Column(db.String(160), default="Next", nullable=False)
    priority = db.Column(db.Integer, default=0, nullable=False)
    is_default = db.Column(db.Boolean, default=False, nullable=False)

    workflow = db.relationship("Workflow", back_populates="edges")
    source_node = db.relationship(
        "WorkflowNode", foreign_keys=[source_node_id], back_populates="outgoing_edges"
    )
    target_node = db.relationship(
        "WorkflowNode", foreign_keys=[target_node_id], back_populates="incoming_edges"
    )


class ReviewRun(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    reviewer_type = db.Column(db.String(80), nullable=False)
    contract_version = db.Column(db.Integer, default=1, nullable=False)
    workflow_version = db.Column(db.Integer, default=1, nullable=False)
    status = db.Column(db.String(40), default="complete", nullable=False)
    provider_name = db.Column(db.String(80), default="deterministic", nullable=False)
    error_message = db.Column(db.Text, default="", nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    project = db.relationship("Project", back_populates="review_runs")
    findings = db.relationship("Finding", back_populates="review_run", cascade="all, delete-orphan")


class Finding(TimestampMixin, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    review_run_id = db.Column(db.String(36), db.ForeignKey("review_run.id", ondelete="CASCADE"), nullable=False)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    severity = db.Column(db.String(40), default="observation", nullable=False)
    title = db.Column(db.String(200), nullable=False)
    explanation = db.Column(db.Text, default="", nullable=False)
    evidence = db.Column(db.Text, default="", nullable=False)
    related_contract_section = db.Column(db.String(120), default="", nullable=False)
    related_workflow_node_id = db.Column(
        db.String(36), db.ForeignKey("workflow_node.id", ondelete="SET NULL"), nullable=True
    )
    recommendation = db.Column(db.Text, default="", nullable=False)
    status = db.Column(db.String(40), default="open", nullable=False)
    resolution_note = db.Column(db.Text, default="", nullable=False)

    review_run = db.relationship("ReviewRun", back_populates="findings")
    project = db.relationship("Project", back_populates="findings")
    related_workflow_node = db.relationship("WorkflowNode")


class ExportRecord(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    contract_version = db.Column(db.Integer, default=1, nullable=False)
    workflow_version = db.Column(db.Integer, default=1, nullable=False)
    export_type = db.Column(db.String(40), default="zip", nullable=False)
    local_path = db.Column(db.String(520), nullable=False)
    manifest_json = db.Column(db.JSON, default=dict, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    project = db.relationship("Project", back_populates="exports")


class ActivityEvent(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=new_uuid)
    project_id = db.Column(db.String(36), db.ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    event_type = db.Column(db.String(80), nullable=False)
    summary = db.Column(db.String(260), nullable=False)
    metadata_json = db.Column(db.JSON, default=dict, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)

    project = db.relationship("Project", back_populates="activity_events")
