# AI-Driven RFP Generator (`project_rfp_ai`)

**Version**: 1.0.0
**License**: LGPL-3

## 1. Executive Summary
This Odoo module implements an **Agentic AI System** designed to automate the Requirement Engineering phase of software projects. It acts as an intelligent intermediary, interviewing stakeholders to gather functional requirements and then autonomously architecting and writing a professional Request for Proposal (RFP) document.

**Key Capabilities:**
*   **Active Listening**: The AI adaptation changes its questions based on user answers.
*   **Irrelevance Detection**: The system learns from what users *skip*, updating its internal context.
*   **Architectural Awareness**: It separates "Structure Design" (TOC) from "Content Writing" to ensure logical flow.
*   **Resilience**: Built-in handling for AI Rate Limits (429) and Malformed JSON (Retry Logic).

---

## 2. File Structure & Manifest
A quick map for AI Agents exploring the codebase.

```text
project_rfp_ai/
├── __manifest__.py                 # Odoo Module Definition (Deps: website, portal, mail)
├── odoo.conf                       # Local dev config
├── upgrade_module.sh               # Helper script to update logic without restarting service manually
├── models/
│   ├── __init__.py
│   ├── project.py                  # [CORE] Main Logic Engine (Analysis & Generation)
│   ├── form_input.py               # [DATA] Dynamic Questions Data Model
│   ├── document_section.py         # [DATA] Generated Artifacts (Markdown Content)
│   ├── prompt.py                   # [CONFIG] Database-backed System Prompts
│   ├── ai_schemas.py               # [LOGIC] JSON Schemas for AI Structured Output
│   └── ai_log.py                   # [CORE] AI Request Logging & Monitoring
├── views/
│   ├── menu_views.xml              # Backend Menu Items
│   ├── rfp_project_views.xml       # Backend Form/List Views (Project Management)
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
    └── rfp_prompt_data.xml         # [DATA] Default System Prompts (Interviewer, Architect, Writer)
```

---

## 3. Core Logic Deep Dive

### 3.1 The Brain: `models/project.py`
This file contains the two "Agent Loops".

#### A. Gap Analysis Loop (`action_analyze_gap`)
This method runs every time the user submits answers.
1.  **Context Aggregation**:
    *   Iterates through `form_input_ids`.
    *   Formats accepted answers: `Key: Value`.
    *   Formats **Irrelevant** answers: `Key: [MARKED IRRELEVANT] Reason`. *Crucial for preventing repetitive questions.*
    *   Compiles this into a JSON string `context_str`.
2.  **AI Invocation**:
    *   Fetches `interviewer_main` prompt from DB.
    *   Calls `utils.ai_connector.generate_json_response()`.
3.  **State Update**:
    *   Saves raw response to `ai_context_blob` (Text field) for transparency.
    *   Parses new questions (`form_fields`) and creates `rfp.form.input` records.
    *   Checks `is_gathering_complete`. If True -> Moves stage to `generating`.

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
    *   Output: Markdown text, saved to `rfp.document.section`.

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
*   **Performance Metrics**: Tracks execution duration to monitor latency.
*   **Status Tracking**: Distinct states for `Success`, `Error`, and `Rate Limit` to help debug production issues.

---

## 4. Prompt Engineering (`data/rfp_prompt_data.xml`)

The intelligence is defined here. We use **XML Data Files** to load these into the database. To modify a prompt, edit this file and upgrade the module.

1.  **`interviewer_main`**
    *   *Persona*: Senior Business Analyst.
    *   *Goal*: Identify gaps in requirements.
    *   *Constraint*: Must return valid JSON matching `get_interviewer_response_schema`.
    *   *Constraint*: Only ask 3-5 questions at a time.

2.  **`writer_toc_architect`**
    *   *Persona*: RFP Strategist & Information Architect.
    *   *Goal*: Structure the document.
    *   *Input*: Raw User Q&A.
    *   *Output*: JSON Tree (TOC).

3.  **`writer_section_content`**
    *   *Persona*: Technical Writer.
    *   *Input*: Complete TOC (Context) + Specific Section Title (Focus).
    *   *Output*: Markdown Content.

---

## 5. Frontend & Interaction (`rfp_portal.js` & `portal_templates.xml`)

### 5.1 Dynamic Form Rendering
The template `portal_rfp_input_field` is a reusable component.
*   If `component_type == 'select'`, renders `<select>`.
*   If `component_type == 'radio'`, renders radio groups.
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
