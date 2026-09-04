from __future__ import annotations

import copy
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from app.extensions import db
from app.models import (
    ExperienceContract,
    ExportRecord,
    Finding,
    Project,
    SourceDocument,
    SynthesisItem,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    utcnow,
)
from app.schemas import ContractSuggestion, ProviderFailure, SynthesisResult, dump_model
from app.services.contract_service import (
    CONTRACT_BLUEPRINT,
    ensure_contract_shape,
    merge_contract_suggestions,
)
from app.services.export_service import (
    build_export,
    compose_export_files,
    discard_export_artifacts,
)
from app.services.extraction import extract_text, normalize_pasted_text, preview_jsonish_text
from app.services.project_service import (
    archive_project,
    auto_correct_attention,
    brief_health,
    brief_review_sections,
    completion,
    create_project,
    duplicate_project,
    permanently_delete_project,
    record_activity,
    restore_project,
    seed_demo_project,
    update_project_stage,
    workflow_attention_node,
)
from app.services.prompt_service import get_prompt
from app.services.providers import (
    OLLAMA_DISCOVERY_TIMEOUT,
    OLLAMA_PROVIDER_PREFIX,
    DeterministicDemoProvider,
    get_provider,
    list_ollama_models,
    provider_selection_value,
    resolve_ollama_model_name,
    test_ollama_connection,
)
from app.services.review_service import REVIEWERS, run_all_reviews, run_review
from app.services.security import (
    ensure_within_directory,
    remove_tree_safely,
    safe_display_filename,
    save_upload,
)
from app.services.settings import load_settings, save_settings
from app.services.simple_mode import create_simple_project, simple_project_snapshot
from app.services.workflow_service import (
    NODE_TYPES,
    create_workflow_edge,
    create_workflow_node,
    edge_to_dict,
    node_to_dict,
    serialize_workflow,
    update_node_from_payload,
)

bp = Blueprint("main", __name__)


def json_ok(data=None, message: str = "", status: int = 200):
    return jsonify({"ok": True, "message": message, "data": data or {}}), status


def json_error(message: str, status: int = 400):
    return jsonify({"ok": False, "error": {"message": message}}), status


def project_or_404(project_id: str) -> Project:
    return Project.query.filter_by(id=project_id).first_or_404()


def project_context(project: Project, section: str) -> dict:
    update_project_stage(project)
    health = brief_health(project)
    return {
        "project": project,
        "section": section,
        "completion": completion(project),
        "brief_health": health,
        "open_findings": Finding.query.filter_by(project_id=project.id, status="open").count(),
    }


@bp.get("/")
def index():
    return render_template("simple.html", settings=load_settings())


@bp.get("/projects")
@bp.get("/agents")
def projects():
    active = Project.query.filter_by(status="active").order_by(Project.updated_at.desc()).all()
    archived = Project.query.filter_by(status="archived").order_by(Project.updated_at.desc()).all()
    return render_template(
        "projects/dashboard.html",
        active_project_cards=[_project_card(project) for project in active],
        archived_project_cards=[_project_card(project) for project in archived],
        active_projects=active,
        archived_projects=archived,
    )


@bp.get("/simple")
@bp.get("/agent/new")
def simple_mode_page():
    return render_template("simple.html", settings=load_settings())


@bp.post("/simple/projects")
@bp.post("/agents")
def create_simple_project_route():
    action = request.form.get("action", "draft_brief")
    brief = _compose_new_brief_text(request.form)
    try:
        if action == "save_draft":
            name = request.form.get("name", "").strip() or "Untitled agent"
            project = create_project(
                name=name,
                description=brief,
                workflow_name=request.form.get("build_type", ""),
                target_user=request.form.get("target_user", ""),
                desired_outcome=request.form.get("desired_outcome", ""),
            )
            upload = request.files.get("starter_document")
            if upload and upload.filename:
                _create_source_from_upload(project, upload, upload.filename)
            record_activity(project, "draft_saved", "Agent draft saved from New agent.")
            update_project_stage(project)
            result = {"project": project, "providers": ["deterministic"], "notice": ""}
        else:
            result = create_simple_project(
                name=request.form.get("name", ""),
                brief=brief,
                build_type=request.form.get("build_type", ""),
                target_user=request.form.get("target_user", ""),
                desired_outcome=request.form.get("desired_outcome", ""),
            )
            upload = request.files.get("starter_document")
            if upload and upload.filename:
                _create_source_from_upload(result["project"], upload, upload.filename)
                update_project_stage(result["project"])
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        flash(str(exc), "error")
        return redirect(url_for("main.simple_mode_page"))
    project = result["project"]
    provider_label = ", ".join(_friendly_provider_name(provider) for provider in result["providers"])
    if result["notice"]:
        flash(result["notice"], "error")
    message = "Agent draft saved locally." if action == "save_draft" else f"Agent plan created with {provider_label}."
    flash(message, "success")
    return redirect(url_for("main.project_simple", project_id=project.id))


@bp.post("/projects")
def create_project_route():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Name is required.", "error")
        return redirect(url_for("main.projects"))
    project = create_project(
        name=name,
        description=request.form.get("description", ""),
        workflow_name=request.form.get("workflow_name", ""),
        target_user=request.form.get("target_user", ""),
        desired_outcome=request.form.get("desired_outcome", ""),
    )
    upload = request.files.get("starter_document")
    if upload and upload.filename:
        try:
            _create_source_from_upload(project, upload, request.form.get("starter_title") or upload.filename)
        except ValueError as exc:
            flash(str(exc), "error")
    update_project_stage(project)
    db.session.commit()
    flash("Agent created locally.", "success")
    return redirect(url_for("main.project_simple", project_id=project.id))


@bp.post("/projects/<project_id>/duplicate")
@bp.post("/agents/<project_id>/duplicate")
def duplicate_project_route(project_id):
    project = project_or_404(project_id)
    duplicate = duplicate_project(project)
    db.session.commit()
    flash("Agent duplicated.", "success")
    return redirect(url_for("main.project_simple", project_id=duplicate.id))


@bp.post("/projects/<project_id>/archive")
@bp.post("/agents/<project_id>/archive")
def archive_project_route(project_id):
    project = project_or_404(project_id)
    archive_project(project)
    db.session.commit()
    flash("Agent archived.", "success")
    return redirect(url_for("main.projects"))


@bp.post("/projects/<project_id>/restore")
@bp.post("/agents/<project_id>/restore")
def restore_project_route(project_id):
    project = project_or_404(project_id)
    restore_project(project)
    db.session.commit()
    flash("Agent restored.", "success")
    return redirect(url_for("main.project_simple", project_id=project.id))


@bp.post("/projects/<project_id>/delete")
@bp.post("/agents/<project_id>/delete")
def delete_project_route(project_id):
    project = project_or_404(project_id)
    if request.form.get("confirm_name", "") != project.name:
        flash("Type the agent name exactly to permanently delete it.", "error")
        return redirect(url_for("main.project_overview", project_id=project.id))
    permanently_delete_project(project)
    db.session.commit()
    flash("Agent permanently deleted.", "success")
    return redirect(url_for("main.projects"))


@bp.get("/projects/<project_id>")
@bp.get("/agents/<project_id>")
def project_overview(project_id):
    project = project_or_404(project_id)
    context = project_context(project, "overview")
    high_findings = (
        Finding.query.filter(
            Finding.project_id == project.id,
            Finding.status == "open",
            Finding.severity.in_(["critical", "high"]),
        )
        .order_by(Finding.created_at.desc())
        .all()
    )
    open_questions = [
        item
        for item in project.synthesis_items
        if item.category == "open_questions" and item.inclusion_status == "included"
    ]
    context.update({"high_findings": high_findings, "open_questions": open_questions})
    return render_template("projects/overview.html", **context)


@bp.get("/projects/<project_id>/simple")
@bp.get("/agents/<project_id>/brief")
def project_simple(project_id):
    project = project_or_404(project_id)
    attention_node = workflow_attention_node(project)
    return render_template(
        "projects/simple.html",
        attention_node=attention_node,
        brief_sections=brief_review_sections(project),
        snapshot=simple_project_snapshot(project),
        settings=load_settings(),
        **project_context(project, "simple"),
    )


@bp.get("/projects/<project_id>/sources")
@bp.get("/agents/<project_id>/background")
def sources_page(project_id):
    project = project_or_404(project_id)
    return render_template("projects/sources.html", **project_context(project, "sources"))


@bp.post("/api/projects/<project_id>/sources")
def create_source_api(project_id):
    project = project_or_404(project_id)
    try:
        upload = request.files.get("file")
        if upload and upload.filename:
            source = _create_source_from_upload(project, upload, request.form.get("title") or upload.filename)
        else:
            payload = request.get_json(silent=True) or request.form
            text = normalize_pasted_text(payload.get("text", ""))
            if not text:
                return json_error("Paste background information or choose a supported file.")
            source = SourceDocument(
                project=project,
                title=(payload.get("title") or "Pasted background info").strip()[:200],
                description=(payload.get("description") or "").strip(),
                source_type="pasted_text",
                original_filename="",
                stored_filename="",
                mime_type="text/plain",
                file_size=len(text.encode("utf-8")),
                extracted_text=text,
                edited_text=preview_jsonish_text(text),
                extraction_status="ready",
            )
            db.session.add(source)
        record_activity(project, "source_added", f"Background information added: {source.title}")
        update_project_stage(project)
        db.session.commit()
        return json_ok({"source": _source_to_dict(source)}, "Background information saved.", 201)
    except ValueError as exc:
        db.session.rollback()
        return json_error(str(exc))


@bp.post("/api/projects/<project_id>/attention/auto-correct")
@bp.post("/api/agents/<project_id>/attention/auto-correct")
def auto_correct_attention_api(project_id):
    project = project_or_404(project_id)
    try:
        result = auto_correct_attention(project)
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return json_error(str(exc))
    if result["corrected_count"]:
        message = (
            f"Auto correct updated {result['corrected_count']} attention "
            f"item{'s' if result['corrected_count'] != 1 else ''}."
        )
    else:
        message = "Nothing needs attention right now."
    return json_ok(result, message)


@bp.patch("/api/sources/<source_id>")
def update_source_api(source_id):
    source = db.get_or_404(SourceDocument, source_id)
    payload = request.get_json(silent=True) or {}
    for field in ["title", "description", "edited_text"]:
        if field in payload:
            setattr(source, field, str(payload[field]))
    source.updated_at = utcnow()
    record_activity(source.project, "source_updated", f"Background information updated: {source.title}")
    update_project_stage(source.project)
    db.session.commit()
    return json_ok({"source": _source_to_dict(source)}, "Background information updated.")


@bp.delete("/api/sources/<source_id>")
def delete_source_api(source_id):
    source = db.get_or_404(SourceDocument, source_id)
    project = source.project
    if source.stored_filename:
        remove_tree_safely(current_app.config["AX_UPLOAD_DIR"], current_app.config["AX_UPLOAD_DIR"] / source.stored_filename)
    db.session.delete(source)
    record_activity(project, "source_removed", f"Background information removed: {source.title}")
    update_project_stage(project)
    db.session.commit()
    return json_ok(message="Background information removed.")


@bp.post("/api/projects/<project_id>/synthesize")
def synthesize_api(project_id):
    project = project_or_404(project_id)
    text = "\n\n".join(source.edited_text or source.extracted_text for source in project.source_documents)
    if not text.strip():
        return json_error("Add background information before creating key details.")
    provider = get_provider()
    fallback_notice = ""
    try:
        result = provider.generate_structured(
            task_name="intake_synthesis",
            system_prompt=get_prompt("intake_synthesis"),
            user_prompt=text,
            response_model=SynthesisResult,
        )
    except ProviderFailure as exc:
        fallback_notice = f"{exc.message} The built-in draft helper was used instead."
        provider = DeterministicDemoProvider()
        result = provider.generate_structured(
            task_name="intake_synthesis",
            system_prompt=get_prompt("fallback_synthesis"),
            user_prompt=text,
            response_model=SynthesisResult,
        )
    for item in list(project.synthesis_items):
        db.session.delete(item)
    db.session.flush()
    first_source = project.source_documents[0] if project.source_documents else None
    for item in dump_model(result)["items"]:
        db.session.add(
            SynthesisItem(
                project=project,
                category=item["category"],
                text=item["text"],
                source_document=first_source if first_source and not item["is_inference"] else None,
                source_locator=item["source_reference"],
                is_inference=item["is_inference"],
                confidence=item["confidence"],
                inclusion_status="included",
            )
        )
    record_activity(project, "synthesis_generated", "Key details generated.", {"provider": provider.name})
    update_project_stage(project)
    db.session.commit()
    return json_ok({"notice": fallback_notice, "provider": provider.name}, "Key details created.")


@bp.get("/projects/<project_id>/synthesis")
@bp.get("/agents/<project_id>/details")
def synthesis_page(project_id):
    project = project_or_404(project_id)
    groups = {}
    for item in project.synthesis_items:
        groups.setdefault(item.category, []).append(item)
    return render_template("projects/synthesis.html", groups=groups, **project_context(project, "synthesis"))


@bp.patch("/api/synthesis-items/<item_id>")
def update_synthesis_item_api(item_id):
    item = db.get_or_404(SynthesisItem, item_id)
    payload = request.get_json(silent=True) or {}
    if "text" in payload:
        item.text = str(payload["text"]).strip()
    if "inclusion_status" in payload:
        item.inclusion_status = "included" if payload["inclusion_status"] == "included" else "excluded"
    if "confidence" in payload and payload["confidence"] in {"high", "medium", "low", "unknown"}:
        item.confidence = payload["confidence"]
    update_project_stage(item.project)
    db.session.commit()
    return json_ok({"item": _synthesis_to_dict(item)}, "Key detail saved.")

@bp.get("/projects/<project_id>/contract")
@bp.get("/agents/<project_id>/instructions")
def contract_page(project_id):
    project = project_or_404(project_id)
    contract = project.active_contract
    contract.content_json = ensure_contract_shape(contract.content_json)
    versions = list(project.contracts)
    return render_template(
        "projects/contract.html",
        contract=contract,
        versions=versions,
        blueprint=CONTRACT_BLUEPRINT,
        **project_context(project, "contract"),
    )


@bp.patch("/api/contracts/<contract_id>")
def update_contract_api(contract_id):
    contract = db.get_or_404(ExperienceContract, contract_id)
    payload = request.get_json(silent=True) or {}
    content = payload.get("content_json")
    if not isinstance(content, dict):
        return json_error("Build instructions must be structured.")
    contract.content_json = content
    contract.status = payload.get("status", contract.status)
    contract.updated_at = utcnow()
    record_activity(contract.project, "contract_saved", f"Build instructions v{contract.version_number} saved.")
    update_project_stage(contract.project)
    db.session.commit()
    return json_ok({"updated_at": contract.updated_at.isoformat()}, "Build instructions saved.")


@bp.post("/api/contracts/<contract_id>/suggest")
def suggest_contract_api(contract_id):
    contract = db.get_or_404(ExperienceContract, contract_id)
    project = contract.project
    included_items = [item for item in project.synthesis_items if item.inclusion_status == "included"]
    if not included_items:
        return json_error("Include at least one key detail before creating build instructions.")
    context = "\n".join(item.text for item in included_items)
    provider = get_provider()
    fallback_notice = ""
    try:
        result = provider.generate_structured(
            task_name="contract_suggestions",
            system_prompt=get_prompt("contract_suggestions"),
            user_prompt=context,
            response_model=ContractSuggestion,
        )
    except ProviderFailure as exc:
        fallback_notice = f"{exc.message} The built-in draft helper was used instead."
        provider = DeterministicDemoProvider()
        result = provider.generate_structured(
            task_name="contract_suggestions",
            system_prompt=get_prompt("fallback_contract"),
            user_prompt=context,
            response_model=ContractSuggestion,
        )
    contract.content_json = merge_contract_suggestions(
        contract.content_json or {}, dump_model(result)["content_json"]
    )
    contract.updated_at = utcnow()
    record_activity(project, "contract_suggested", "Build instruction suggestions merged from key details.")
    update_project_stage(project)
    db.session.commit()
    return json_ok({"content_json": contract.content_json, "notice": fallback_notice}, "Build instructions updated.")


@bp.post("/api/contracts/<contract_id>/versions")
def create_contract_version_api(contract_id):
    contract = db.get_or_404(ExperienceContract, contract_id)
    project = contract.project
    new_version = ExperienceContract(
        project=project,
        version_number=(project.contracts[-1].version_number if project.contracts else 0) + 1,
        status="draft",
        content_json=copy.deepcopy(contract.content_json),
    )
    db.session.add(new_version)
    record_activity(project, "contract_version_created", f"Build instructions v{new_version.version_number} created.")
    update_project_stage(project)
    db.session.commit()
    return json_ok({"contract_id": new_version.id, "version": new_version.version_number}, "Version saved.", 201)


@bp.get("/projects/<project_id>/workflow")
@bp.get("/agents/<project_id>/workflow")
def workflow_page(project_id):
    project = project_or_404(project_id)
    workflow = project.active_workflow
    return render_template(
        "projects/workflow.html",
        workflow=workflow,
        workflow_data=serialize_workflow(workflow),
        node_types=NODE_TYPES,
        **project_context(project, "workflow"),
    )


@bp.get("/api/workflows/<workflow_id>")
def get_workflow_api(workflow_id):
    workflow = db.get_or_404(Workflow, workflow_id)
    return json_ok({"workflow": serialize_workflow(workflow)})


@bp.post("/api/workflows/<workflow_id>/nodes")
def create_workflow_node_api(workflow_id):
    workflow = db.get_or_404(Workflow, workflow_id)
    payload = request.get_json(silent=True) or {}
    try:
        node = create_workflow_node(
            workflow,
            payload.get("node_type", "agent_action"),
            payload.get("label", ""),
            float(payload.get("position_x", 120)),
            float(payload.get("position_y", 120)),
        )
    except ValueError as exc:
        return json_error(str(exc))
    record_activity(workflow.project, "workflow_node_created", f"Step created: {node.label}")
    update_project_stage(workflow.project)
    db.session.commit()
    return json_ok({"node": node_to_dict(node)}, "Step added.", 201)


@bp.patch("/api/workflow-nodes/<node_id>")
def update_workflow_node_api(node_id):
    node = db.get_or_404(WorkflowNode, node_id)
    payload = request.get_json(silent=True) or {}
    try:
        update_node_from_payload(node, payload)
    except ValueError as exc:
        return json_error(str(exc))
    record_activity(node.workflow.project, "workflow_node_updated", f"Step updated: {node.label}")
    update_project_stage(node.workflow.project)
    db.session.commit()
    return json_ok({"node": node_to_dict(node)}, "Step saved.")


@bp.delete("/api/workflow-nodes/<node_id>")
def delete_workflow_node_api(node_id):
    node = db.get_or_404(WorkflowNode, node_id)
    project = node.workflow.project
    WorkflowEdge.query.filter(
        (WorkflowEdge.source_node_id == node.id) | (WorkflowEdge.target_node_id == node.id)
    ).delete(synchronize_session=False)
    db.session.delete(node)
    record_activity(project, "workflow_node_deleted", f"Step deleted: {node.label}")
    update_project_stage(project)
    db.session.commit()
    return json_ok(message="Step deleted.")


@bp.post("/api/workflows/<workflow_id>/edges")
def create_workflow_edge_api(workflow_id):
    workflow = db.get_or_404(Workflow, workflow_id)
    payload = request.get_json(silent=True) or {}
    try:
        edge = create_workflow_edge(
            workflow,
            payload.get("source_node_id", ""),
            payload.get("target_node_id", ""),
            payload.get("condition_label", "Next"),
            int(payload.get("priority", 0)),
            bool(payload.get("is_default", False)),
        )
    except ValueError as exc:
        return json_error(str(exc))
    record_activity(workflow.project, "workflow_edge_created", "Step connection created.")
    update_project_stage(workflow.project)
    db.session.commit()
    return json_ok({"edge": edge_to_dict(edge)}, "Connection added.", 201)


@bp.patch("/api/workflow-edges/<edge_id>")
def update_workflow_edge_api(edge_id):
    edge = db.get_or_404(WorkflowEdge, edge_id)
    payload = request.get_json(silent=True) or {}
    if "condition_label" in payload:
        edge.condition_label = str(payload["condition_label"])[:160] or "Next"
    if "priority" in payload:
        edge.priority = int(payload["priority"])
    if "is_default" in payload:
        edge.is_default = bool(payload["is_default"])
    update_project_stage(edge.workflow.project)
    db.session.commit()
    return json_ok({"edge": edge_to_dict(edge)}, "Connection saved.")


@bp.delete("/api/workflow-edges/<edge_id>")
def delete_workflow_edge_api(edge_id):
    edge = db.get_or_404(WorkflowEdge, edge_id)
    project = edge.workflow.project
    db.session.delete(edge)
    record_activity(project, "workflow_edge_deleted", "Step connection deleted.")
    update_project_stage(project)
    db.session.commit()
    return json_ok(message="Connection deleted.")


@bp.get("/projects/<project_id>/reviews")
@bp.get("/agents/<project_id>/quality")
def reviews_page(project_id):
    project = project_or_404(project_id)
    return render_template("projects/reviews.html", reviewers=REVIEWERS, **project_context(project, "reviews"))


@bp.post("/api/projects/<project_id>/reviews")
def run_review_api(project_id):
    project = project_or_404(project_id)
    payload = request.get_json(silent=True) or {}
    reviewer = payload.get("reviewer_type", "all")
    try:
        runs = run_all_reviews(project) if reviewer == "all" else [run_review(project, reviewer)]
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return json_error(str(exc))
    return json_ok({"run_ids": [run.id for run in runs]}, "Quality check completed.")


@bp.patch("/api/findings/<finding_id>")
def update_finding_api(finding_id):
    finding = db.get_or_404(Finding, finding_id)
    payload = request.get_json(silent=True) or {}
    if payload.get("status") in {"open", "accepted", "resolved", "dismissed"}:
        finding.status = payload["status"]
    if "resolution_note" in payload:
        finding.resolution_note = str(payload["resolution_note"])
    update_project_stage(finding.project)
    db.session.commit()
    return json_ok({"finding": _finding_to_dict(finding)}, "Quality note updated.")


@bp.get("/projects/<project_id>/export")
@bp.get("/agents/<project_id>/export")
def export_page(project_id):
    project = project_or_404(project_id)
    preview = compose_export_files(project, utcnow())["AI_BUILD_BRIEF.md"]
    return render_template(
        "projects/export.html",
        preview=preview,
        **project_context(project, "export"),
    )


@bp.post("/api/projects/<project_id>/exports")
def create_export_api(project_id):
    project = project_or_404(project_id)
    payload = request.get_json(silent=True) or {}
    record = None
    try:
        record = build_export(project, include_sources=bool(payload.get("include_sources", False)))
        db.session.commit()
    except Exception:
        db.session.rollback()
        if record is not None:
            discard_export_artifacts(record)
        raise
    return json_ok({"export": _export_to_dict(record)}, "Export package ready.", 201)


@bp.get("/downloads/<export_id>")
def download_export(export_id):
    record = db.get_or_404(ExportRecord, export_id)
    zip_path = ensure_within_directory(current_app.config["AX_EXPORT_DIR"], Path(record.local_path))
    filename = request.args.get("file")
    if not filename:
        return send_file(zip_path, as_attachment=True, download_name=zip_path.name, mimetype="application/zip")
    bundle_dir = zip_path.with_suffix("")
    target = ensure_within_directory(bundle_dir, bundle_dir / filename)
    if not target.exists() or not target.is_file():
        abort(404)
    return send_file(target, as_attachment=True, download_name=target.name)


@bp.get("/settings")
def settings_page():
    settings = load_settings()
    ollama_models = list_ollama_models(
        settings["ollama_base_url"],
        _ollama_discovery_timeout(settings.get("ollama_timeout")),
    )
    return render_template(
        "settings.html",
        settings=settings,
        ollama_models=ollama_models,
        selected_provider=provider_selection_value(settings, ollama_models),
        ollama_provider_prefix=OLLAMA_PROVIDER_PREFIX,
    )


@bp.patch("/api/settings")
def update_settings_api():
    payload = request.get_json(silent=True) or {}
    payload, notice = _normalize_settings_payload(payload)
    try:
        settings = save_settings(payload)
    except (OSError, ValueError) as exc:
        return json_error(f"Could not update local settings: {exc}")
    return json_ok({"settings": settings}, notice or "Settings saved.")


@bp.post("/api/settings/providers/ollama/models")
def list_ollama_models_api():
    payload = request.get_json(silent=True) or {}
    settings = load_settings()
    candidate = dict(settings)
    candidate.update({key: value for key, value in payload.items() if key in settings})
    models = list_ollama_models(
        candidate["ollama_base_url"],
        _ollama_discovery_timeout(candidate.get("ollama_timeout")),
    )
    if models:
        message = f"Detected {len(models)} local Ollama model{'s' if len(models) != 1 else ''}."
    else:
        message = "No local Ollama models were detected. The built-in draft helper remains active."
    return json_ok(
        {"models": models, "selected_provider": provider_selection_value(candidate, models)},
        message,
    )


@bp.post("/api/settings/providers/ollama/test")
def test_ollama_api():
    payload = request.get_json(silent=True) or {}
    settings = load_settings()
    model = payload["ollama_model"] if "ollama_model" in payload else settings["ollama_model"]
    ok, message = test_ollama_connection(
        payload.get("ollama_base_url") or settings["ollama_base_url"],
        model,
        int(payload.get("ollama_timeout") or settings["ollama_timeout"]),
    )
    return json_ok({"connected": ok}, message, 200 if ok else 400)


@bp.post("/api/settings/demo/reset")
def reset_demo_api():
    project = seed_demo_project(reset=True)
    db.session.commit()
    return json_ok({"project_id": project.id}, "Demo project reset.")


def _create_source_from_upload(project: Project, upload, title: str) -> SourceDocument:
    stored_name, size = save_upload(upload, current_app.config["AX_UPLOAD_DIR"])
    original = safe_display_filename(upload.filename)
    path = current_app.config["AX_UPLOAD_DIR"] / stored_name
    text, error = extract_text(path, original)
    status = "error" if error else "ready"
    source = SourceDocument(
        project=project,
        title=(title or original)[:200],
        description=request.form.get("description", ""),
        source_type="upload",
        original_filename=original,
        stored_filename=stored_name,
        mime_type=upload.mimetype or "",
        file_size=size,
        extracted_text=text,
        edited_text=text,
        extraction_status=status,
        extraction_error=error,
    )
    db.session.add(source)
    return source


def _ollama_discovery_timeout(value: object) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = OLLAMA_DISCOVERY_TIMEOUT
    return max(1, min(timeout, OLLAMA_DISCOVERY_TIMEOUT))


def _normalize_settings_payload(payload: dict) -> tuple[dict, str]:
    current = load_settings()
    data = dict(payload)
    provider_choice = str(data.pop("provider_choice", "") or "").strip()
    if provider_choice == "deterministic":
        data["active_provider"] = "deterministic"
    elif provider_choice.startswith(OLLAMA_PROVIDER_PREFIX):
        data["active_provider"] = "ollama"
        data["ollama_model"] = provider_choice.removeprefix(OLLAMA_PROVIDER_PREFIX)

    if data.get("active_provider") not in {"deterministic", "ollama"}:
        data.pop("active_provider", None)

    if data.get("active_provider") != "ollama":
        return data, ""

    base_url = data.get("ollama_base_url") or current["ollama_base_url"]
    timeout = _ollama_discovery_timeout(data.get("ollama_timeout") or current["ollama_timeout"])
    models = list_ollama_models(base_url, timeout)
    model = resolve_ollama_model_name(data.get("ollama_model", ""), models)
    if model:
        data["ollama_model"] = model
        return data, ""

    data["active_provider"] = "deterministic"
    return data, "No local Ollama model was detected, so the built-in draft helper is active."


def _friendly_provider_name(name: str) -> str:
    if name == "deterministic":
        return "the built-in draft helper"
    if name == "ollama":
        return "your local Ollama model"
    return name


def _project_card(project: Project) -> dict:
    update_project_stage(project)
    return {
        "project": project,
        "completion": completion(project),
        "brief_health": brief_health(project),
    }


def _compose_new_brief_text(form) -> str:
    sections = [
        ("What to build", form.get("brief", "")),
        ("Features or pages", form.get("features_or_pages", "")),
        ("Data and integrations", form.get("data_integrations", "")),
        ("Constraints and things to avoid", form.get("constraints", "")),
        ("Target platform or stack", form.get("target_platform", "")),
        ("Deployment environment", form.get("deployment_environment", "")),
        ("Examples or references", form.get("examples", "")),
    ]
    return "\n\n".join(f"{label}: {value.strip()}" for label, value in sections if value and value.strip())


def _source_to_dict(source: SourceDocument) -> dict:
    return {
        "id": source.id,
        "title": source.title,
        "description": source.description,
        "source_type": source.source_type,
        "original_filename": source.original_filename,
        "file_size": source.file_size,
        "extracted_text": source.extracted_text,
        "edited_text": source.edited_text,
        "extraction_status": source.extraction_status,
        "extraction_error": source.extraction_error,
    }


def _synthesis_to_dict(item: SynthesisItem) -> dict:
    return {
        "id": item.id,
        "category": item.category,
        "text": item.text,
        "source_reference": item.source_locator or ("Inference" if item.is_inference else ""),
        "is_inference": item.is_inference,
        "confidence": item.confidence,
        "inclusion_status": item.inclusion_status,
    }


def _finding_to_dict(finding: Finding) -> dict:
    return {
        "id": finding.id,
        "category": finding.category,
        "severity": finding.severity,
        "title": finding.title,
        "explanation": finding.explanation,
        "evidence": finding.evidence,
        "related_contract_section": finding.related_contract_section,
        "related_workflow_node_id": finding.related_workflow_node_id,
        "recommendation": finding.recommendation,
        "status": finding.status,
        "resolution_note": finding.resolution_note,
    }


def _export_to_dict(record: ExportRecord) -> dict:
    return {
        "id": record.id,
        "contract_version": record.contract_version,
        "workflow_version": record.workflow_version,
        "created_at": record.created_at.isoformat(),
        "manifest": record.manifest_json,
        "download_url": url_for("main.download_export", export_id=record.id),
    }
