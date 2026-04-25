# -*- coding: utf-8 -*-
from odoo import fields, models


class GlossaryTermMixin(models.AbstractModel):
    _name = 'rfp.glossary.term.mixin'
    _description = 'Glossary Term Mixin (shared by project + vendor portals)'
    _order = 'sequence, name'

    name = fields.Char(string='Term', required=True, translate=True)
    definition = fields.Text(string='Definition', required=True, translate=True)
    category = fields.Selection(
        selection=[
            ('acronym', 'Acronym'),
            ('jargon', 'Jargon / Industry Term'),
            ('tag_value', 'Tag / Score Value'),
            ('workflow_stage', 'Workflow Stage'),
            ('compliance', 'Compliance / Regulation'),
            ('metric', 'Metric / Scoring'),
            ('other', 'Other'),
        ],
        default='other',
        required=True,
    )
    examples = fields.Text(string='Examples', translate=True)
    sequence = fields.Integer(default=10)
    is_manual = fields.Boolean(
        string='Manual Entry',
        default=False,
        help='Manual entries are preserved when AI re-generates the glossary.',
    )
