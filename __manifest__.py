# -*- coding: utf-8 -*-
{
    'name': "AI-Driven RFP Generator",
    'summary': """Automated Project Specification & RFP Creation via AI""",
    'description': """
        AI-Driven RFP Generator
        =======================
        A system to reverse-engineer project requirements and generate professional RFP documents.
        
        Features:
        - Dynamic Gap Analysis (Interviewer Agent)
        - Project-Agnostic Context Gathering
        - Automatic Document Generation (Writer Agent)
    """,
    'author': "Antigravity",
    'website': "https://www.odoo.com",
    'category': 'Services/Project',
    'version': '18.0.1.0.0',
    'depends': ['base', 'web', 'project', 'portal', 'website', 'queue_job'],
    'data': [
        'security/ir.model.access.csv',
        'security/rfp_security.xml',
        'views/rfp_project_views.xml',
        'views/rfp_form_input_views.xml',
        'views/rfp_document_section_views.xml',
        'views/knowledge_base_views.xml',
        'views/rfp_prompt_views.xml',
        'views/rfp_custom_field_views.xml',
        'views/res_config_settings_views.xml',
        'views/menu_views.xml',
        'views/ai_model_views.xml',
        'views/rfp_ai_log_views.xml',
        'data/queue_data.xml',
        'data/ai_model_data.xml',
        'data/rfp_prompt_data.xml',
        'data/queue_job_data.xml',
        'data/rfp_custom_field_data.xml',
        'views/portal_templates.xml',
        'views/report_rfp.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'project_rfp_ai/static/src/js/rfp_portal.js',
        ],
    },
    'license': 'LGPL-3',
    'installable': True,
    'application': True,
}