# AI-Driven RFP Generator (`project_rfp_ai`)

**Version**: 18.0.1.0.0  
**Odoo Version**: 18.0  
**Author**: Antigravity  
**License**: LGPL-3  
**Category**: Services/Project

## 1. Executive Summary

This module implements an **Agentic AI System** that automates the requirements engineering phase of software projects. It acts as an intelligent intermediary that interviews stakeholders to gather functional requirements, then autonomously architects and writes a professional Request for Proposal (RFP) document. The module is fully integrated into Odoo and provides both backend management and a customer-facing portal interface.

**Key Capabilities:**
*   **14-Stage Research-Driven Workflow**: Sophisticated pipeline from Draft through Initialized, Information Gathered, Best Practices Refined, Specifications Gathered, Practices Gap Gathered, Sections Generated, Generating Content, Content Generated, Generating Images, Images Generated, Document Locked, to Completed (or Completed With Errors).
*   **Three AI Agent Roles**:
    *   **Interviewer Agent**: Conducts multi-round gap analysis interviews, dynamically generating questions based on user answers with active listening and irrelevance detection.
    *   **Architect Agent**: Designs the document Table of Contents structure based on gathered context.
    *   **Writer Agent**: Generates semantic HTML5 content for each section with awareness of global document structure for coherence. Can also propose diagrams (Mermaid or illustration).
*   **Multi-Provider AI Support**: Google Gemini (Flash, Pro), Google Imagen (4.0, 4.0 Ultra), OpenAI (GPT-4o, GPT-4o Mini, o3-mini, o4-mini), DALL-E 3. Each prompt is bound to a specific model for cost/performance optimization.
*   **Document Import & Auto-Fill**: Upload existing RFP documents (PDF/DOCX). The system extracts text, sends it to AI for structured extraction (project name, description, domain, field values), and auto-fills form inputs with confidence levels (high/medium).
*   **Knowledge Base System**: Upload documents or link completed projects to build a reusable knowledge base. Two-step AI analysis: structure extraction then content generalization. Smart KB selection: AI ranks relevant KBs for each project.
*   **Dynamic Custom Fields**: Configurable custom fields for initialization and post-gathering phases with rich types (text, textarea, select with grouped options, radio, checkboxes), suggested answers, specify triggers (for "Other" options), and required/validation flags -- all without code changes.
*   **Asynchronous Content Generation**: Uses OCA `queue_job` for parallel section generation with Fibonacci retry backoff (60s, 180s, 300s, 300s) and channel-based concurrency control (`root.rfp_generation:1`).
*   **Diagram & Image System**: AI-generated Mermaid diagrams (rendered via Kroki.io API) and illustrations (via Imagen 4.0 or DALL-E 3). Diagrams are stored as child records of sections with binary image files.
*   **Vendor Proposal Management**: Publish RFPs with public access tokens, receive vendor proposals, and get AI-powered proposal analysis with coverage scoring, strengths/weaknesses, risk assessment, and recommendations.
*   **Evaluation Criteria Engine**: AI interviews stakeholders to determine evaluation priorities. Generates structured criteria with categories (technical, commercial, experience, compliance, timeline, methodology, support, innovation), weights, must-have flags, and scoring guidance.
*   **Portal User Experience**: Gold-themed responsive UI with dynamic form rendering, dependency logic (conditional visibility), suggested answer badges, unified document editor with drag-and-drop structure reordering, Quill.js rich text editing, AI-powered text editing ("rewrite this section"), image regeneration, and PDF/Word export.
*   **Full AI Audit Trail**: Every AI request is logged with system prompt, input context, raw response, duration, status (success/error/rate limit), linked prompt, and linked model -- enabling A/B testing and debugging.
*   **Resilience Features**: Rate limit handling (HTTP 429), malformed JSON retry logic, queue job automatic retries, dynamic round limits based on scope assessment (AI analyzes budget, complexity, project type), and "Revert to Edit" capability.

---

## 2. Dependencies

**Odoo Modules:**
*   `base` -- Core Odoo framework
*   `web` -- Web client
*   `project` -- Project management (inherits project icon for menu)
*   `portal` -- Customer portal for external user interaction
*   `website` -- Website framework for frontend templates
*   `queue_job` -- OCA background job processing for async AI content generation

**Python Libraries** (`requirements.txt`):
*   `google-genai` -- Google Gemini/Imagen API client
*   `openai` -- OpenAI SDK support (multi-provider)
*   `PyPDF2` -- PDF text extraction
*   `markupsafe` -- HTML sanitization

---

## 3. Models Overview

| Model | Purpose |
|---|---|
| **`rfp.project`** | Core project entity with 14-stage workflow. Central logic engine for all AI-driven analysis and generation. Inherits `mail.thread` and `mail.activity.mixin`. |
| **`rfp.form.input`** | Dynamic form inputs generated by AI during information gathering interview. Supports 7 component types (text, number, textarea, select, multiselect, radio, boolean). |
| **`rfp.practice.input`** | Similar to form_input but used for the "best practices gap analysis" phase. |
| **`rfp.document.section`** | Generated RFP document sections (TOC leaves). Stores HTML5 content and links to diagrams. |
| **`rfp.section.diagram`** | Visual diagrams per section. Two types: Mermaid (flowcharts via Kroki API) and Illustration (AI-generated images via Imagen/DALL-E). |
| **`rfp.prompt`** | Database-backed system prompt templates with unique codes. Each prompt links to a specific AI model. |
| **`rfp.ai.model`** | AI model configuration registry. Supports Google Gemini and OpenAI providers with tagging system. |
| **`rfp.ai.model.tag`** | Tags for AI models (High Speed, High Quality, English, Multilingual, Image). |
| **`rfp.ai.log`** | Centralized AI request logging for full auditability. Tracks system prompt, input, response, duration, status, and linked prompt/model. |
| **`rfp.custom.field`** | Dynamic custom field definitions for project initialization and post-gathering phases. |
| **`rfp.field.option`** | Relational options for custom field select/radio/checkbox inputs. |
| **`rfp.field.suggestion`** | Suggested answer values for custom fields. |
| **`rfp.project.domain`** | Business domain context (e.g., "Healthcare", "Software Development") used by AI for domain-aware questioning. |
| **`rfp.knowledge.base`** | Knowledge base entries created from uploaded documents or completed projects. |
| **`rfp.kb.section`** | Knowledge base sections with type classification (introduction, functional, technical, compliance, security, timeline, budget, evaluation, support, appendix). |
| **`rfp.eval.input`** | Evaluation criteria inputs gathered via AI interview for vendor proposal assessment. |
| **`rfp.evaluation.criterion`** | Structured evaluation criteria with category, weight, must-have flag, and scoring guidance. |
| **`rfp.required.document`** | Required document types that vendors must submit (e.g., Technical Proposal, Financial Proposal). |
| **`rfp.proposal`** | Vendor proposals submitted against published RFPs. Includes AI-powered proposal analysis with scoring. |
| **`rfp.proposal.document`** | Uploaded documents attached to vendor proposals. |
| **`rfp.published`** | Published/exported RFP records with public access tokens (UUID). |
| **`rfp.published.section`** | Published RFP sections (copied from project sections). |
| **`rfp.published.diagram`** | Published diagrams with rendered images. |
| **`res.config.settings`** (extended) | Adds Gemini API Key, OpenAI API Key, and generation concurrency settings. |

---

## 4. 14-Stage Workflow Pipeline

```
Draft
  ↓
Initialized (Research Done)
  ↓
Information Gathered
  ↓
Best Practices Refined
  ↓
Specifications Gathered
  ↓
Practices Gap Gathered
  ↓
Sections Generated
  ↓
Generating Content
  ↓
Content Generated
  ↓
Generating Images
  ↓
Images Generated
  ↓
Document Locked
  ↓
Completed  (or Completed With Errors)
```

**Key transitions:**
*   **Draft → Initialized**: `action_initialize_project()` -- AI refines description, selects domain, performs initial research, creates init form inputs, auto-fills from source documents.
*   **Initialized → Information Gathered**: `action_analyze_gap()` -- AI interview loop for project-specific requirements gathering.
*   **Information Gathered → Best Practices Refined**: `action_refine_practices()` -- AI refines best practices based on gathered answers.
*   **Best Practices Refined → Specifications Gathered**: `action_check_specifications()` -- Injects post-gathering custom fields.
*   **Specifications Gathered → Practices Gap Gathered**: `action_analyze_practices_gap()` -- AI interview for best practices compliance.
*   **Practices Gap Gathered → Sections Generated**: `action_generate_structure()` -- AI architect designs Table of Contents.
*   **Sections Generated → Content Generated**: `action_generate_content()` -- Async queue jobs generate HTML content for each section.
*   **Content Generated → Images Generated**: `action_generate_diagram_images()` -- Async queue jobs generate images for diagrams.
*   **Images Generated → Document Locked**: User locks the final document.
*   **Document Locked → Completed**: `action_mark_completed()` -- Marks project as completed, sends notifications.
*   **Completed → Document Locked**: `action_create_kb_from_project()` -- Exports completed project to Knowledge Base.
*   **Any stage → Completed With Errors**: Automatic fallback on unrecoverable failures.

---

## 5. Core Action Methods

### 5.1 Project Initialization
**`action_initialize_project()`** -- Phase 0
1.  Fetches `project_initializer` prompt.
2.  Input: Project Name + Raw Description + List of Available Domains.
3.  AI refines description professionally and selects the appropriate business domain.
4.  If no matching domain exists, creates a new one.
5.  Updates `description` and `domain_id`, then auto-triggers research phase.

### 5.2 Document Import
**`action_initialize_from_document()`** -- Upload existing RFP (PDF/DOCX)
1.  Extracts text via PyPDF2 (PDF) or XML parsing (DOCX).
2.  Sends to AI for structured extraction (project name, description, domain, field values).
3.  Auto-fills form inputs with confidence levels (high/medium confidence answers are pre-filled).

### 5.3 Gap Analysis Interview
**`action_analyze_gap()`** -- Phase 3
1.  Aggregates context: formats accepted answers and irrelevant flags with reasons.
2.  Fetches `interviewer_main` prompt and calls AI with structured output schema.
3.  Parses new questions and creates `rfp.form.input` records.
4.  Checks if gathering is complete; if so, triggers Best Practices Refinement.

### 5.4 Best Practices Refinement
**`action_refine_practices()`** -- Phase 4
1.  Uses `research_refinement` prompt to synthesize specific technical details based on gathered answers.
2.  Output saved to `refined_practices`.

### 5.5 Post-Gathering Custom Fields
**`action_check_specifications()`** -- Phase 4b
Injects post-gathering custom fields defined in `rfp.custom.field` into the project.

### 5.6 Practices Gap Analysis
**`action_analyze_practices_gap()`** -- Phase 5
AI interview loop specifically for best practices compliance using `rfp.practice.input` records.

### 5.7 Document Structure Generation
**`action_generate_structure()`** -- Phase 6
1.  Compiles all valid Q&A pairs into readable Markdown.
2.  Calls `writer_toc_architect` prompt to design a Table of Contents tree.
3.  Output: JSON structure (`title`, `subsections` list) saved to `ai_context_blob['toc_structure']`.

### 5.8 Content Generation
**`action_generate_content()`** -- Phase 7
1.  Iterates recursively through the JSON TOC.
2.  For each section, calls `writer_section_content` prompt with entire TOC + current section title.
3.  Dispatches each section generation as a separate queue job via `with_delay()`.
4.  Fibonacci retry backoff (60s, 180s, 300s, 300s) for transient failures.

### 5.9 Diagram Image Generation
**`action_generate_diagram_images()`** -- Phase 8
1.  **Mermaid Diagrams**: AI generates Mermaid.js code, rendered to PNG via Kroki.io API.
2.  **Illustrations**: AI generates image prompts, rendered via Imagen 4.0 or DALL-E 3.
3.  Each image generation is a separate queue job.

### 5.10 Evaluation Criteria
**`action_gather_eval_criteria()`** -- AI interview to define vendor evaluation criteria with categories, weights, must-have flags, and scoring guidance.

### 5.11 Document Locking & Completion
*   **`action_lock_document()`**: Locks the final document preventing further edits.
*   **`action_mark_completed()`**: Marks project as completed, sends email notifications.
*   **`action_create_kb_from_project()`**: Exports completed project to Knowledge Base.
*   **Revert to Edit**: Unlocks completed documents for further refinement.
*   **`action_proceed_next_stage()`**: Automated non-interactive stage transitions.

---

## 6. AI Model Management

The system is model-agnostic with a centralized registry.

*   **`rfp.ai.model`**: Stores technical names (`gemini-3-pro-preview`, `gpt-4o`, etc.) and attributes.
*   **Tagging System**: Models are tagged (e.g., "High Speed", "High Quality", "English", "Multilingual", "Image") to organize capabilities.
*   **Dynamic Selection**: Each `rfp.prompt` record links to a specific `rfp.ai.model` for cost/performance optimization.
    *   *Interviewer* uses **Gemini Flash** (low latency, high throughput).
    *   *Architect/Writer* uses **Gemini Pro** (deep reasoning, long context window).
    *   *Image Generation* uses **Imagen 4.0** or **DALL-E 3**.

**Default AI Models** (from `data/ai_model_data.xml`):
*   Gemini 3 Pro, Gemini 2.5 Flash, Gemini 3 Flash, Gemini Flash, Gemini Flash Lite
*   Imagen 4.0, Imagen 4.0 Ultra, Gemini 3 Pro Image
*   GPT-4o, GPT-4o Mini, o3-mini, o4-mini, DALL-E 3

---

## 7. Prompt Engineering

Prompts are stored in the database via `data/rfp_prompt_data.xml` (14+ templates). Key prompts:

| Prompt Code | Phase | Purpose |
|---|---|---|
| `project_initializer` | Phase 0 | Refines project description and selects business domain |
| `research_initial` | Phase 1 | Broad domain research using Google Search |
| `interviewer_main` | Phase 3 | Gap analysis interview, dynamically generating questions |
| `research_refinement` | Phase 4 | Refines best practices based on gathered answers |
| `writer_toc_architect` | Phase 6 | Designs Table of Contents structure |
| `writer_section_content` | Phase 7 | Generates HTML5 content for each section |
| `image_generator` | Phase 8 | Generates image prompts for diagrams |
| `kb_structure_extractor` | KB | Extracts structure from knowledge base documents |
| `kb_content_generalizer` | KB | Generalizes KB content for reuse |
| `kb_selector` | Project | Ranks relevant KBs for each project |
| `document_auto_filler` | Import | Auto-fills form inputs from uploaded RFP |
| `proposal_extractor` | Import | Extracts metadata from uploaded RFP documents |
| `vendor_extract_criteria` | Vendor | Extracts evaluation criteria from RFP (vendor portal) |
| `vendor_score_proposal` | Vendor | Scores vendor proposal against criteria |

Each prompt is linked to a specific AI model and uses structured output schemas for reliable JSON responses.

---

## 8. Knowledge Base System

The Knowledge Base enables reusing knowledge from completed projects and uploaded documents.

**Workflow:**
1.  **Create KB**: Link a completed project or upload documents directly.
2.  **Structure Extraction**: AI analyzes document structure and classifies sections (introduction, functional, technical, compliance, security, timeline, budget, evaluation, support, appendix).
3.  **Content Generalization**: AI generalizes specific project details into reusable best practices.
4.  **Smart Selection**: When starting a new project, AI ranks relevant KBs based on domain and context.
5.  **KB Injection**: KB content is injected into prompts to guide TOC structure, section writing, and practices analysis.

**Key Models:**
*   `rfp.knowledge.base` -- KB entry with metadata and linked project/document source.
*   `rfp.kb.section` -- Structured sections with type classification.

---

## 9. Dynamic Custom Fields

Admins can extend the project data model without code changes.

**Features:**
*   **Phased Injection**: Fields appear at `Init` (Project Creation) or `Post-Gathering` (After AI Interview).
*   **Rich Types**: Text, Textarea, Select (with grouped options), Radio, Checkboxes (multi-select).
*   **Relational Options**: `rfp.field.option` model for Label/Value pairs with drag-and-drop reordering.
*   **Suggested Answers**: `rfp.field.suggestion` provides clickable badge values.
*   **Specify Triggers**: "Other" options trigger a free-text input.
*   **Validation**: `is_required` and `default_value` enforced on frontend and backend.
*   **Conditional Visibility**: Dependency logic (`data-depends-on`) for conditional field display.

**Default Fields** (from `data/rfp_custom_field_data.xml`):
Contact info, project type (grouped dropdown with 30+ options across 10 industry verticals), target audience, budget ranges, success goals, hosting preferences, compliance requirements, user load scale, integration requirements.

---

## 10. Vendor Proposal Management

**Publishing RFPs:**
*   Completed RFPs can be published with a public access token (UUID).
*   Published RFPs are accessible via public URL with their sections and diagrams.
*   Required document types can be specified (Technical Proposal, Financial Proposal, etc.).

**Vendor Submissions:**
*   Vendors submit proposals against published RFPs.
*   Multiple documents can be attached to a single proposal.
*   Proposals are stored with `rfp.proposal` and `rfp.proposal.document` models.

**AI-Powered Analysis:**
*   **Coverage Scoring**: How well the proposal addresses the RFP content (0-100).
*   **Strengths/Weaknesses**: Identified with impact levels and severity levels.
*   **Risk Assessment**: Potential risks in the proposal.
*   **Recommendation**: Shortlist, Review, or Reject with justification.
*   **Criteria-Based Scoring**: Per-criterion scores using the evaluation criteria engine.
*   **Must-Have Failure Detection**: Flags proposals that fail mandatory requirements.
*   **Weighted Total Score**: Calculated from per-criterion scores and weights.

---

## 11. Security

**4-Tier Permission Matrix** (`security/ir.model.access.csv`):

| Model Group | Internal Users | System Admins | Portal Users | Public Users |
|---|---|---|---|---|
| Projects | Full | Full | Read-Write (own) | -- |
| Form Inputs | Full | Full | Read-Only (own) | -- |
| Document Sections | Full | Full | Read-Write (own) | Read (published) |
| Custom Fields | Read-Only | Full | Read-Only | -- |
| Prompts | Read-Only | Full | -- | -- |
| Published RFPs | Full | Full | Read-Write (own) | Read-Only |

**Record Rules** (`security/rfp_security.xml`):
*   Portal users can only see RFP projects they own (`user_id = user.id`).
*   Portal users can only see form inputs and document sections belonging to their own projects.

---

## 12. Frontend Portal

**Routes:**
*   `/rfp/start/<slug>` -- Project start page.
*   `/rfp/gather/<slug>` -- Dynamic question form rendering.
*   `/rfp/document/<slug>` -- Unified document editor (SPA).
*   `/rfp/proposal/<slug>` -- Proposal submission page.
*   `/rfp/review/<slug>` -- Proposal analysis dashboard.

**Features:**
*   **Dynamic Form Rendering**: Multi-type support (text, textarea, select, radio, checkboxes, phone with intl-tel-input).
*   **Dependency Logic**: Conditional field visibility based on `data-depends-on` attributes.
*   **Suggested Answer Badges**: Clickable badges that auto-fill input values.
*   **Loading Overlay**: Visual feedback during AI processing ("Thinking...").
*   **Unified Document Editor**: SPA-style navigation with structure drag-and-drop, Quill.js rich text editing, diagram management, AI-powered text editing, and image regeneration.
*   **Lock/Unlock Toggle**: Locks the final document or reverts to edit mode.
*   **PDF Print View**: Browser-native print with clean CSS (hides portal UI).
*   **Word Document Download**: Downloads `.doc` file with semantic HTML content.
*   **Auto-Save**: Structure and content updates are saved via AJAX endpoints.

**Client-Side JavaScript** (`static/src/js/rfp_portal.js`):
*   Dependency checking and conditional visibility.
*   Form submission with loading overlay.
*   Suggestion click handlers.
*   SPA navigation and section reordering.
*   Quill.js editor integration.

---

## 13. Configuration & Queue Job

### 13.1 Odoo Configuration (`odoo.conf`)
```ini
[options]
server_wide_modules = web,queue_job

[queue_job]
channels = root:1,root.rfp_generation:1
```

*   `root.rfp_generation:1`: Dedicates 1 concurrent worker for AI content generation to avoid API rate limits.

### 13.2 Module Settings
Go to **Settings > Technical > RFP AI**:
*   **Gemini API Key**: Configure your Google AI Studio key.
*   **OpenAI API Key**: Configure your OpenAI API key.
*   **Concurrent AI Requests**: Adjust concurrency level for the content generation queue.

### 13.3 Backend Menus
**RFP Generator** root menu with submenus:
*   **Projects** -- List of all RFP projects.
*   **Configuration**:
    *   AI Models -- Model registry with tags.
    *   AI Prompts -- System prompt templates.
    *   Init Screen Fields -- Custom fields for initialization phase.
    *   Post-Analysis Fields -- Custom fields for post-gathering phase.
    *   Knowledge Base -- Reusable knowledge entries.
    *   AI Logs -- AI request audit log.
    *   Settings -- API keys and concurrency.

---

## 14. File Structure

```text
project_rfp_ai/
├── __manifest__.py                     # Odoo Module Definition
├── __init__.py                         # Module initialization
├── README.md                           # This file
├── requirements.txt                    # Python dependencies
├── models/                             # 24 models (see Section 3)
├── views/                              # 12 XML view files + portal templates
├── controllers/
│   └── portal.py                       # /rfp/* routes
├── static/src/
│   ├── js/rfp_portal.js               # Client-side logic
│   └── lib/                            # Third-party libraries (Quill.js, intl-tel-input)
├── utils/
│   └── ai_connector.py                 # AI API wrapper (retry, error handling)
├── data/                               # 6 data files (prompts, models, fields, templates, queue)
├── security/
│   ├── ir.model.access.csv             # 4-tier permissions
│   └── rfp_security.xml                # Record rules
└── wizard/                             # (Empty)
```

---

## 15. How to Develop / Extend

### Adding a New Question Type
1.  **Backend**: Add key to `component_type` Selection in `models/form_input.py`.
2.  **Prompt**: Update the interviewer prompt/schema to let AI know it can use this type.
3.  **View**: Add a `<t t-elif="...">` block in `views/portal_templates.xml` to render the HTML.
4.  **JS**: Ensure `_onInputChange` captures the value change in `rfp_portal.js`.

### Debugging AI Responses
1.  Go to **Projects** and open a project.
2.  Look at the **"AI Context"** tab -- shows pretty-printed JSON of the last raw AI response.
3.  Check **AI Logs** for detailed request/response history with duration and status.

### Common Issues & Fixes

**Issue**: Portal Crash `AttributeError: 'str' object has no attribute 'get'`
*   *Cause*: `ai_context_blob` is a Text string, accessing it like a Dict in QWeb.
*   *Fix*: Use `rfp_project.get_context_data()` helper method in the view.

**Issue**: AI repeats the same question.
*   *Cause*: Context didn't include the previous answer.
*   *Fix*: Check `action_analyze_gap` logic. Ensure "Irrelevant" flags are passed to the context string.

**Issue**: 500 Error / Server Timeout
*   *Cause*: AI API call took too long.
*   *Fix*: Odoo HTTP workers might timeout (default 120s). Increase `limit_time_real` in `odoo.conf`.

**Issue**: Queue jobs stuck in "Pending"
*   *Cause*: Queue job channel not configured or worker not running.
*   *Fix*: Ensure `server_wide_modules = web,queue_job` in `odoo.conf` and restart Odoo.

---

## 16. Maintainers

*   **Ali Faleh**
    *   [alifaleh.netlify.app](https://alifaleh.netlify.app)
    *   [alifaleh.me@gmail.com](mailto:alifaleh.me@gmail.com)
    *   [github.com/alifaleh](https://github.com/alifaleh)

*   **Murtaja Adnan**
    *   [murtajaadnan7@gmail.com](mailto:murtajaadnan7@gmail.com)
    *   [github.com/murtaja1](https://github.com/murtaja1)
