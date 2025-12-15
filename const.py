# -*- coding: utf-8 -*-

# Project Stages
STAGE_DRAFT = 'draft'
STAGE_INITIALIZED = 'initialized'
STAGE_INFO_GATHERED = 'info_gathered'
STAGE_PRACTICES_REFINED = 'practices_refined'
STAGE_SPECIFICATIONS_GATHERED = 'specifications_gathered'
STAGE_PRACTICES_GAP_GATHERED = 'practices_gap_gathered'
STAGE_SECTIONS_GENERATED = 'sections_generated'
STAGE_GENERATING_CONTENT = 'generating_content'
STAGE_CONTENT_GENERATED = 'content_generated'
STAGE_GENERATING_IMAGES = 'generating_images'
STAGE_IMAGES_GENERATED = 'images_generated'
STAGE_DOCUMENT_LOCKED = 'document_locked'
STAGE_COMPLETED_WITH_ERRORS = 'completed_with_errors'
STAGE_COMPLETED = 'completed'

# Prompt Codes
PROMPT_PROJECT_INITIALIZER = 'project_initializer'
PROMPT_RESEARCH_INITIAL = 'research_initial'
PROMPT_INTERVIEWER_PROJECT = 'interviewer_project' # Was interviewer_main / interviewer_project
PROMPT_RESEARCH_REFINEMENT = 'research_refinement'
PROMPT_INTERVIEWER_PRACTICES = 'interviewer_practices'
PROMPT_WRITER_TOC_ARCHITECT = 'writer_toc_architect'
PROMPT_WRITER_SECTION = 'writer_section_content'

# Generation Status
STATUS_PENDING = 'pending'
STATUS_QUEUED = 'queued'
STATUS_GENERATING = 'generating'
STATUS_SUCCESS = 'success'
STATUS_FAILED = 'failed'

# AI Request Status
AI_STATUS_DRAFT = 'draft'
AI_STATUS_SENDING = 'sending'
AI_STATUS_SUCCESS = 'success'
AI_STATUS_ERROR = 'error'
AI_STATUS_RATE_LIMIT = 'rate_limit'

# Default Configuration
DEFAULT_GEMINI_MODEL = "gemini-1.5-flash"
