# AI-Driven RFP Generator (`project_rfp_ai`)

**Version**: 1.2.0
**License**: LGPL-3

## 1. Executive Summary
This Odoo module implements an **Agentic AI System** designed to automate the Requirement Engineering phase of software projects. It acts as an intelligent intermediary, interviewing stakeholders to gather functional requirements and then autonomously architecting and writing a professional Request for Proposal (RFP) document.

**Key Capabilities:**
*   **7-Stage Research-Driven Workflow**: Implementation of a sophisticated pipeline: Initialization -> Initial Research -> Information Gathering -> Refinement -> Structuring -> Writing -> Completion.
*   **Project Initialization**: Starts the project by professionally refining the user's idea and intelligently determining the **Vendor Expertise Domain** (e.g., Software Development vs. Logistics).
*   **Active Listening**: The AI adaptation changes its questions based on user answers.
*   **Irrelevance Detection**: The system learns from what users *skip*, updating its internal context.
*   **Architectural Awareness**: It separates "Structure Design" (TOC) from "Content Writing" to ensure logical flow.
*   **Resilience**: Built-in handling for AI Rate Limits (429) and Malformed JSON, plus automatic retry for queue jobs.
*   **Flexible Workflow**: Features a robust "Revert to Edit" capability, allowing users to unlock completed documents for further refinement, and a custom finalization safety layer.
*   **AI Model Management**: Granular control over the AI engine. You can define various Gemini models (e.g., Flash for speed, Pro for reasoning) and tag them. Each system prompt is configured to use a specific model to balance cost, speed, and intelligence.
*   **Dynamic Custom Fields**: Fully configurable custom fields for both Project Initialization and Post-Gathering phases. Supports rich data types like Multi-Select Checkboxes, Radio Buttons, and Relational Options, allowing administrators to inject organization-specific data requirements seamlessly into the AI workflow.

---

## 2. File Structure & Manifest
A quick map for AI Agents exploring the codebase.

```text
project_rfp_ai/
├── __manifest__.py                 # Odoo Module Definition (Deps: queue_job, website, portal, mail)
├── odoo.conf                       # Local dev config
├── upgrade_module.sh               # Helper script to update logic without restarting service manually
├── models/
│   ├── __init__.py
│   ├── project.py                  # [CORE] Main Logic Engine (Analysis & Generation)
│   ├── ai_model.py                 # [CONFIG] AI Model Definitions & Tagging
│   ├── form_input.py               # [DATA] Dynamic Questions Data Model
│   ├── document_section.py         # [DATA] Generated Artifacts (HTML Content)
│   ├── prompt.py                   # [CONFIG] Database-backed System Prompts
│   ├── ai_schemas.py               # [LOGIC] JSON Schemas for AI Structured Output
│   ├── ai_log.py                   # [CORE] AI Request Logging & Monitoring
│   ├── custom_field.py             # [CONFIG] Custom Fields Definition (Init/Post-Gathering)
│   ├── field_option.py             # [DATA] Relational Options for Select/Radio/Checkbox
│   ├── rfp_domain.py               # [DATA] Project Domain Context Model
│   └── ai_model_views.xml          # Backend Views for AI Models
├── views/
│   ├── menu_views.xml              # Backend Menu Items
│   ├── rfp_project_views.xml       # Backend Form/List Views (Project Management)
│   ├── rfp_custom_field_views.xml  # Backend Views for Custom Fields
│   ├── rfp_form_input_views.xml    # Backend View for Specific Questions (Debug)
│   ├── rfp_document_section_views.xml # Backend View for Sections
│   ├── rfp_prompt_views.xml        # Backend View for Editing Prompts
│   ├── portal_templates.xml        # [UI] Frontend Portal Interfaces (QWeb)
│   ├── report_rfp.xml              # Checkpoint for future PDF Reports
│   └── res_config_settings_views.xml # Settings (API Keys - Placeholder)
├── controllers/
│   ├── __init__.py
│   └── portal.py                   # [HTTP] Routes /rfp/* handling form submissions
├── static/
│   └── src/
│       └── js/
│           └── rfp_portal.js       # [UI] Client-side logic (Dependencies, Loading Overlay)
├── utils/
│   ├── __init__.py
│   └── ai_connector.py             # [LIB] Google GenAI Wrapper (Retry, Error Handling)
└── data/
    ├── rfp_prompt_data.xml         # [DATA] Default System Prompts (Interviewer, Architect, Writer)
    └── ai_model_data.xml           # [DATA] Default AI Models and Tags
├── queue/                          # [LIB] OCA Queue Job Module
│   └── queue_job/
```

---

## 3. Core Logic Deep Dive

### 3.1 The Brain: `models/project.py`
This file contains the three "Agent Loops".

#### A. Initialization Loop (`action_initialize_project`)
This method runs immediately upon project creation (Phase 0).
1.  **AI Invocation**:
    *   Fetches `project_initializer` prompt.
    *   Input: Project Name + Raw Description + List of Available Domains.
    *   Goal: "Refine Description" and "Select Domain".
2.  **Domain Selection**:
    *   The AI chooses the domain representing the **Vendor's Expertise** (e.g., "Software Development").
    *   If no matching domain exists, it suggests a new one which is automatically created.
3.  **Refinement**:
    *   Rewrites the description to be professional while **strictly preserving** all specific data (dates, numbers, constraints).
4.  **State Update**:
    *   Updates `description` and `domain_id`.
    *   **Phase 2**: Automatically triggers `action_research_initial`.
    *   **Action**: Uses Google Search to find "Best Practices" for the specific domain.
    *   **Output**: Saved to `initial_research` field.
    *   Advances stage to `gathering`.

#### B. Gap Analysis Loop (`action_analyze_gap`)
This method runs every time the user submits answers.
1.  **Context Aggregation**:
    *   Iterates through `form_input_ids`.
    *   Formats accepted answers: `Key: Value`.
    *   Formats **Irrelevant** answers: `Key: [MARKED IRRELEVANT] Reason`. *Crucial for preventing repetitive questions.*
    *   Injects **Custom Field Data**: Post-gathering custom fields defined in `rfp.custom.field` are injected into the input stream automatically when the AI signals completion, ensuring all mandatory data is collected.
    *   Compiles this into a JSON string `context_str`.
2.  **AI Invocation**:
    *   Fetches `interviewer_main` prompt from DB.
    *   Calls `utils.ai_connector.generate_json_response()`.
3.  **State Update**:
    *   Saves raw response to `ai_context_blob` (Text field) for transparency.
    *   Updates context strings.
    *   **Phase 3**: Information Gathering (Interviewer).
    *   Parses new questions (`form_fields`) and creates `rfp.form.input` records.
    *   Checks `is_gathering_complete`. If True -> Triggers **Phase 4**.
    *   **Phase 4**: Best Practices Refinement (`action_refine_practices`).
    *   **Action**: Uses Google Search to refine the Initial Research based on the Gathered Answers.
    *   **Output**: Saved to `refined_practices`.
    *   Advances stage to `structuring`.

#### B. Document Generation Loop (`action_generate_document`)
This method runs once, triggered by the user after analysis.
1.  **Context Building**: Compiles all *valid* Q&A pairs into a readable Markdown list.
2.  **Phase 1: The Architect**:
    *   Calls `writer_toc_architect` prompt.
    *   Task: "Design a Table of Contents tree based on this context. Do NOT write content."
    *   Output: JSON Structure (`title`, `subsections` list).
    *   This is saved to `ai_context_blob['toc_structure']`.
3.  **Phase 2: The Writer**:
    *   Iterates recursively through the JSON TOC.
    *   For each section, calls `writer_section_content` prompt.
    *   **Context Injection**: The prompt receives the **entire TOC** + **Current Section Title**.
    *   Task: "Write the content for *this specific section* knowing it fits into *that global structure*."
    *   **Asynchronous Execution**:
        *   Uses `queue_job` (OCA) to offload content generation.
        *   Each section generation is dispatched as a separate job via `with_delay()`.
        *   **Retry Mechanism**: Configured with a Fibonacci-like backoff (60s, 180s) to handle transient AI failures automatically.
        *   Project maintains links to these jobs for status tracking ("Pending", "Queued", "Generating", "Success", "Failed").
    *   Output: Semantic HTML5 content, saved to `rfp.document.section`.

### 3.2 The Nervous System: `utils/ai_connector.py`
Functions as the resilience layer.
*   **`_call_gemini_api`**:
    *   Wraps `google.genai.models.generate_content`.
    *   **Rate Limit Handler**: Catches `ResourceExhausted` (HTTP 429). Raises custom `RateLimitError`.
*   **`generate_json_response`**:
    *   **Retry Logic**: Wraps the call in a `while` loop (default 2 retries) to handle transient network issues or malformed JSON.
    *   **JSON Repair**: Attempts `json.loads`. If it fails, logs error and retries. *Guidance: Future versions should implement fuzzy JSON repair.*

### 3.3 The Observer: `models/ai_log.py`
This model provides full visibility into the AI "Thought Process".
*   **Centralized Logging**: All requests from Gap Analysis and Document Writer flow through `execute_request`.
*   **Full Audibility**: Stores the exact `system_prompt`, `user_context`, and `response_raw`.
    *   **Traceability**: Links each request to the specific `rfp.prompt` record and `rfp.ai.model` used, allowing for A/B testing of prompt versions.
    *   **Performance Metrics**: Tracks execution duration to monitor latency.
    *   **Status Tracking**: Distinct states for `Success`, `Error`, and `Rate Limit` to help debug production issues.


### 3.4 AI Model Management: `models/ai_model.py`
The system is model-agnostic.
*   **Centralized Registry**: `rfp.ai.model` stores technical names (`gemini-2.0-flash`, `gemini-3-pro-preview`) and attributes.
*   **Tagging System**: Models are tagged (e.g., "High Speed", "Deep Reasoning", "Production") to organize them emotionally and logically.
*   **Dynamic Selection**: `rfp.prompt` records link to specific `rfp.ai.model` records.
    *   *Interviewer* uses **Gemini Flash** (Low latency, high throughput).
    *   *Architect/Writer* uses **Gemini Pro** (Deep reasoning, long context window).

### 3.5 Custom Field Engine: `models/custom_field.py`
Allows admins to extend the project data model without code changes.
*   **Phased Injection**: Fields can be set to appear at `Init` (Project Creation) or `Post-Gathering` (After AI Interview).
*   **Relational Options**: Select, Radio, and Checkbox inputs use a relational `rfp.field.option` model, allowing for explicit Label/Value pairs and drag-and-drop reordering.
*   **Advanced Data Types**: Supports `checkboxes` (Multi-Select) which are serialized as comma-separated values or JSON lists depending on the context.
*   **Validation**: Enforces `is_required` and `default_value` logic constraints on both the Frontend (Portal) and Backend.

---

## 4. Prompt Engineering (`data/rfp_prompt_data.xml`)

The intelligence is defined here. We use **XML Data Files** to load these into the database. To modify a prompt, edit this file and upgrade the module.

1.  **`project_initializer`** (Phase 0)
    *   *Persona*: Senior Business Analyst.
    *   *Goal*: Standardize the input and categorize the domain.
    *   *Constraint*: Zero Tolerance for data loss (must preserve deadlines/facts).
    *   *Constraint*: Domain must reflect Vendor Expertise.

2.  **`interviewer_main`** (Phase 1)
    *   *Persona*: Senior Business Analyst.
    *   *Goal*: Identify gaps in requirements.
    *   *Constraint*: Must return valid JSON matching `get_interviewer_response_schema`.
    *   *Constraint*: Must return valid JSON matching `get_interviewer_response_schema`.
    *   *Constraint*: Only ask 3-5 questions at a time.

3.  **`research_initial`** (Phase 2)
    *   *Persona*: Research Specialist.
    *   *Goal*: Broad domain research using Google Search.
    *   *Task*: "Find best practices and standard sections for [Domain]".

4.  **`research_refinement`** (Phase 4)
    *   *Persona*: Senior Solutions Architect.
    *   *Goal*: Specific research based on gathered answers.
    *   *Task*: "Synthesize specific technical details and standards based on user input."

5.  **`writer_toc_architect`** (Phase 5)
    *   *Persona*: RFP Strategist & Information Architect.
    *   *Goal*: Structure the document.
    *   *Input*: Raw User Q&A.
    *   *Output*: JSON Tree (TOC).

3.  **`writer_section_content`**
    *   *Persona*: Technical Writer.
    *   *Input*: Complete TOC (Context) + Specific Section Title (Focus).
    *   *Output*: HTML5 Content.

---

## 5. Configuration & Queue Job

### 5.1 Odoo Configuration (`odoo.conf`)
To enable the background job runner, your `odoo.conf` must include:

```ini
[options]
server_wide_modules = web,queue_job
# workers > 0 ensures multiprocessing, but queue_job works in threaded mode too.
# If using workers > 0, set an environment variable GEVENT_SUPPORT=True for debugging.

[queue_job]
channels = root:1,root.rfp_generation:1
```

*   `root.rfp_generation:1`: Dedicates 1 concurrent worker specifically for AI content generation to avoid API rate limits.

### 5.2 Module Settings
Go to **Settings > Technical > RFP AI**:
*   **Gemini API Key**: Configure your Google AI Studio key securely.
*   **Concurrent AI Requests**: Adjust the concurrency level for the content generation queue (e.g., increase to 2 or 4 if your API tier supports it).

### 5.3 Configuring AI Models
Go to **RFP AI > Configuration > AI Models**:
*   Define your models (e.g., update the Technical Name when Google releases a new version).
*   Add tags to easily identify model capabilities.

Go to **RFP AI > Configuration > AI Prompts**:
*   Link each prompt to the most appropriate AI Model. This allows you to upgrade the "Writer" logic to a newer model without risking the stability of the "Interviewer" logic.

### 5.4 Domain Management
Go to **RFP AI > Configuration > Project Domains**:
*   Create and manage the business domains (e.g., "Healthcare", "E-Commerce", "FinTech").
*   These are used to provide initial context to the AI Architect.

---

## 5. Frontend & Interaction (`rfp_portal.js` & `portal_templates.xml`)

### 5.1 Dynamic Form Rendering
The template `portal_rfp_input_field` is a reusable component.
*   **Multi-Type Support**: Renders Text, Number, Textarea, Select, Radio, and our new **Checkboxes** (Multi-select) widget.
*   **Structure**: Uses a defined HTML structure that integrates with `rfp_portal.js` for dependency handling.
*   **Suggested Answers**: Renders clickable badges. JS listener `_onSuggestionClick` fills the input when clicked.

### 5.2 Dependency Logic (`_checkDependencies`)
Strictly client-side visibility toggling.
*   Inputs have `data-depends-on='{"field_key": "x", "value": "y"}'`.
*   `_onInputChange` listener checks if the target field matches the value.
*   Toggles `.d-none` class on the wrapper div.

### 5.3 The Loading Overlay
Since AI processing can take 5-15 seconds:
*   **HTML**: Hidden `div#rfp_loading_overlay` in `portal_templates.xml`.
*   **JS triggers**: `_onSubmit` event listener on the form removes `.d-none` class.
*   **Effect**: Immediate visual feedback ("Thinking...") prevents user from clicking twice.

### 5.4 Document Lifecycle
*   **Structure Review**: Users can drag-and-drop sections to reorder the Table of Contents before generation begins.
*   **Content Review**: Integrated **Quill.js** rich text editor allows users to polish the AI-generated HTML content before finalization.
*   **Finalization**: Uses a Bootstrap Modal for a safe "Are you sure?" confirmation before preventing further edits.
*   **Reversion**: Includes a "Edit" button on completed documents that triggers a controller (`/rfp/revert_to_edit`) to unlock the project and return it to the 'writing' stage.
*   **Reporting**:
    *   **PDF**: Uses an optimized browser-native print view (`window.print()`) with CSS that hides the portal UI (headers, sidebars, buttons), ensuring only the clean document card is printed.
    *   **Word**: Downloads a clean `.doc` file containing the semantic HTML content, wrapped for compatibility with Microsoft Word.

---

## 6. How to Develop / Extend

### Adding a New Question Type
1.  **Backend**: Add key to `component_type` Selection in `models/form_input.py`.
2.  **Prompt**: Update `interviewer_schema.json` (or the prompt text) to let AI know it can use this type.
3.  **View**: Add a `<t t-elif="...">` block in `views/portal_templates.xml` to render the HTML.
4.  **JS**: Ensure `_onInputChange` captures the value change for this element (standard Inputs are covered).

### Debugging AI Responses
The module stores the last raw response in `rfp.project` -> `ai_context_blob`.
1.  Go to **Projects**.
2.  Open a Project.
3.  Look at the **"AI Context"** tab.
4.  It is a Text field showing pretty-printed JSON. You can see exactly why the AI made a decision or what JSON error occurred.

### Common Issues & Fixes

**Issue**: Portal Crash `AttributeError: 'str' object has no attribute 'get'`
*   *Cause*: `ai_context_blob` is a Text string, accessing it like a Dict in QWeb.
*   *Fix*: Use `rfp_project.get_context_data()` helper method in the view.

**Issue**: AI repeats the same question.
*   *Cause*: Context didn't include the previous answer.
*   *Fix*: Check `action_analyze_gap` logic. Ensure "Irrelevant" flags are passed to the Context string.

**Issue**: 500 Error / Server Timeout
*   *Cause*: Gemini API took too long.
*   *Fix*: Odoo HTTP workers might timeout (default 120s). Increase `limit_time_real` in `odoo.conf` if generating huge documents.


## 8. Maintainers

*   **Ali Faleh**
    *   [alifaleh.netlify.app](https://alifaleh.netlify.app)
    *   [alifaleh.me@gmail.com](mailto:alifaleh.me@gmail.com)
    *   [github.com/alifaleh](https://github.com/alifaleh)
