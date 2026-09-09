# UAX Studio Tutorial

UAX Studio is a local-first Flask app for turning product ideas, workflow notes, source files, and reviewer feedback into an AI-ready build brief. The main output is an export bundle centered on `AI_BUILD_BRIEF.md`, with supporting Markdown, JSON, Mermaid workflow data, and a manifest.

This tutorial walks through the full app from first launch to export.

## Table of Contents

1. [Start the App](#start-the-app)
2. [Choose a Workflow](#choose-a-workflow)
3. [Create a Simple Project](#create-a-simple-project)
4. [Create a Full Project](#create-a-full-project)
5. [Add Sources](#add-sources)
6. [Review the Brief](#review-the-brief)
7. [Generate and Edit Build Instructions](#generate-and-edit-build-instructions)
8. [Build the Workflow Canvas](#build-the-workflow-canvas)
9. [Connect Workflow Nodes](#connect-workflow-nodes)
10. [Run Reviews](#run-reviews)
11. [Export the Build Brief](#export-the-build-brief)
12. [Manage Projects](#manage-projects)
13. [Configure Providers](#configure-providers)
14. [Recommended End-to-End Flow](#recommended-end-to-end-flow)
15. [Troubleshooting](#troubleshooting)

## Start the App

Open a terminal in the folder containing `run.py` (the cloned or downloaded `UAX-Studio` repository).

If the virtual environment already exists:

```powershell
.\.venv\Scripts\Activate.ps1
python run.py
```

For a fresh Windows setup:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

For macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Open:

```text
http://127.0.0.1:5000
```

## Choose a Workflow

UAX Studio has two practical starting points.

Use `Simple Mode` when you want UAX Studio to draft the project from one brief. This creates Background Information, Build Instructions, and a starter workflow.

Use the project dashboard when you want more control. A full project lets you save Background Information, generate and edit Build Instructions, model the workflow, run reviewers, and export when ready.

## Create a Simple Project

1. Open `/simple`.
2. Enter a project name.
3. Choose or type the build type, such as `Website`, `AI agent`, `Automation workflow`, or `Application`.
4. Add the target user.
5. Describe the desired outcome.
6. Paste the build brief.
7. Click `Draft my agent`.

Good brief content includes:

- What should be built.
- Who will use it.
- The main tasks or screens.
- Data, files, integrations, or content it needs.
- Review or confirmation checkpoints.
- Things the product must not do.
- What success looks like.

After creation, the Brief page shows seven editable modules. Open a saved agent from the Agents page to view its Overview, then use the navigation to reach Brief, Workflow, or Export.

## Create a Full Project

1. Open the dashboard at `/projects`.
2. Fill in the project name, description, workflow name, target user, and desired outcome.
3. Optionally attach a starter document.
4. Click `Create project`.

The project opens in the Brief workspace. You can move between project areas through the top navigation and direct project URLs:

```text
/projects/<project_id>/sources
/projects/<project_id>/contract
/projects/<project_id>/workflow
/projects/<project_id>/reviews
/projects/<project_id>/export
```

## Add Sources

Background Information contains the saved notes and uploaded documents used to generate Build Instructions.

1. Open Background Information under Advanced Editing on the Brief page.
2. Paste source text or upload a supported file.
3. Give the source a clear title.
4. Save it.
5. Edit extracted text if needed.

Supported uploads include:

- `.txt`
- `.md`
- `.json`
- `.csv`
- `.pdf`
- `.docx`

Provider output is saved as editable suggestions. Uploaded filenames are sanitized for local storage.

## Review the Brief

Original Idea spans the full first row. Six more cards follow in three equal-height pairs: Product Foundation with Audience and User Outcomes; Core Experience and Features with Data and Integrations; Constraints and Risks with Acceptance Criteria. On smaller mobile screens, all seven cards form one column in the same order.

Every `Edit section` button opens a panel on the right without leaving Brief. The panel loads that module's saved fields. Use `Save changes` to update the Brief immediately, or `Cancel`, the close button, or Escape to close it. Unsaved edits trigger a discard warning. The panel fills the available width on mobile. Shared values use the existing project and Build Instructions fields, so edits persist after reopening the agent.

Health details and `Auto correct` are available on Overview. Edit workflow steps directly in Workflow using Step Details. Advanced Editing stays visible below the Brief cards and links to Background Information and Build Instructions. Brief no longer includes a health summary or Workflow preview.

## Generate and Edit Build Instructions

Build Instructions are the structured specification for the target product. They contain product intent, build target, implementation plan, responsibilities, autonomy controls, confidence behavior, data rules, trust expectations, recovery behavior, and definition of done.

1. Add and save Background Information.
2. Click `Generate Build Instructions` on Background Information or Build Instructions. All saved documents are analyzed automatically and used immediately to draft instructions.
3. Edit text fields and list items directly.
4. Add list items when the spec needs more detail.
5. Remove list items that should not guide the build.
6. Click `Save version` when you want a snapshot.

Instruction sections include:

- `Product intent`: problem, user, goal, outcome, objectives, measures, constraints, risks, and unresolved assumptions.
- `Build target`: artifact type, platform, surfaces, features, data, integrations, roles, environment, and quality.
- `Implementation plan`: build steps, routes, data flow, acceptance tests, out-of-scope items, and AI builder instructions.
- `Responsibility model`: AI, human, shared, and prohibited responsibilities.
- `Autonomy controls`: automatic actions, review actions, confirmation actions, and high-impact actions.
- `Confidence behavior`: what the system should do at high, medium, low, or unknown confidence.
- `Data and memory`: what can be read, created, retained, or deleted.
- `Transparency and trust`: activity history, source display, explanations, generated-content labels, change previews, and undo expectations.
- `Escalation and recovery`: missing information, conflicts, tool failure, partial completion, incorrect action, and stopping conditions.
- `Definition of done`: UX checks, functional checks, and open questions.

## Build the Workflow Canvas

The workflow canvas models the path a user, system, AI agent, tool, or review step follows.

Open:

```text
/projects/<project_id>/workflow
```

Use the toolbar to add nodes. Node types include:

- `start`
- `user_action`
- `agent_action`
- `tool_call`
- `data_lookup`
- `decision`
- `confidence_check`
- `error`
- `end`

Select a node to edit its details in the inspector. Useful node details include:

- Label.
- Description.
- Actor.
- Expected output.
- Data accessed.
- Permission level.
- Recovery behavior.
- Position.

## Connect Workflow Nodes

Connections describe how the workflow moves from one node to another.

1. Click a node on the canvas.
2. A small `connect +` control appears above the selected node.
3. Hover the control to read the tooltip directions.
4. Click `connect +` to enter connection mode.
5. Click another node to create an edge.
6. Use the visible connection-mode control to turn the mode off when you are done.

After an edge is created, edit its condition label, priority, and default-path setting in the edge table.

Use clear edge labels such as:

- `Next`
- `Complete`
- `Needs edits`
- `Low confidence`
- `Tool unavailable`
- `Confirmed`

## Run Reviews

Reviews inspect the contract and workflow for quality issues.

Open:

```text
/projects/<project_id>/reviews
```

Available reviewers include:

- Interaction architect.
- Trust and safety critic.
- Accessibility reviewer.
- Technical feasibility reviewer.

Run one reviewer or all reviewers. Findings appear with severity, evidence, recommendation, and status. Update a finding when you have handled it.

## Export the Build Brief

Open:

```text
/projects/<project_id>/export
```

The export preview shows `AI_BUILD_BRIEF.md`, the main handoff document for an AI builder or engineering team.

To export:

1. Review the preview.
2. Choose whether to include source files.
3. Click `Download ZIP`. The package is generated and downloaded in one action.

Export bundles include:

- `README.md`
- `product_intent.md`
- `build_contract.md`
- `agent_experience_contract.md`
- `workflow.md`
- `workflow.mmd`
- `workflow.json`
- `findings.md`
- `acceptance_criteria.md`
- `implementation_manifest.json`
- `AI_BUILD_BRIEF.md`

Sources are excluded unless `Include my source files` is selected. When selected, the ZIP includes original uploads and editable text copies.

## Manage Projects

From the dashboard you can:

- Open active projects.
- Duplicate a project.
- Archive a project.
- Restore an archived project.
- Permanently delete a project after typing its exact name.
- Reset the GalleryFlow demo from Settings.

Duplicating a project copies its saved background, Build Instructions, workflow, and project details.

## Configure Providers

UAX Studio works without an API key through the deterministic provider.

In Settings you can also configure Ollama:

1. Choose `Ollama local provider`.
2. Enter the local base URL.
3. Enter the model name.
4. Set the timeout.
5. Run the connection test.

If Ollama fails or returns invalid structured JSON, UAX Studio records a visible fallback notice and uses the deterministic provider.

## Recommended End-to-End Flow

1. Enter and save Background Information (or start with a guided draft).
2. Generate Build Instructions.
3. Review and edit Build Instructions, including unresolved assumptions and questions.
4. Build or adjust the Workflow and its Step Details.
5. Run a Quality Check and resolve findings.
6. Export and hand `AI_BUILD_BRIEF.md` to your builder.

## Troubleshooting

### The App Does Not Start

Confirm the virtual environment is active and dependencies are installed:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python run.py
```

If port 5000 is busy, set a different port:

```powershell
$env:AX_PORT="5001"
python run.py
```

### Build Instructions Do Not Generate

Add and save Background Information first. Empty projects show a prompt to add it. Existing projects with saved background analysis can still generate instructions when their original documents are unavailable.

### Export Looks Too Vague

Improve Background Information and Build Instructions first. The export is strongest when users, surfaces, features, data, constraints, recovery behavior, and acceptance checks are explicit.

### Ollama Is Not Used

Open Settings, select Ollama as the active provider, test the connection, and confirm the local model is running.

## Glossary

`Source`: Pasted or uploaded material that describes the target product.

`Build Instructions`: Editable implementation guidance, assumptions, and questions for the target product.

`Workflow`: A node-and-edge model of how the target product behaves.

`Review Finding`: A quality, safety, accessibility, or feasibility note from a reviewer.

`Export`: A ZIP bundle containing Markdown, workflow data, manifest hashes, and the AI build brief.
