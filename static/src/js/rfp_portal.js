/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.RfpPortalInteractions = publicWidget.Widget.extend({
    selector: '.rfp-portal-wrapper', // Simplified to prevent double instantiation on nested matches
    events: {
        // Gap Analysis Events (Standard Odoo events usually work fine here, but manual binding is safer if we see issues)
        'click .btn-suggestion': '_onSuggestionClick',
        'click .btn-irrelevant-toggle': '_onIrrelevantToggle',
        'click .btn-irrelevant-cancel': '_onIrrelevantToggle',
        'change .rfp-input-group input, .rfp-input-group select, .rfp-input-group textarea': '_onInputChange',
        'submit form': '_onSubmit',

        // Structure Actions
        'click #btn_add_section': '_onAddSection',
        'click .btn-delete-section': '_onDeleteSection',
        'click #btn_confirm_structure': '_onConfirmStructure',
        'click #btn_save_structure': '_onSaveStructure',

        // Content Review Actions
        'click #btn_save_content': '_onSaveContent',
        'click #btn_submit_content': '_onSubmitContent',
    },

    // Custom RPC implementation to avoid module dependency issues in frontend
    _rpc: async function (options) {
        const response = await fetch(options.route, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params: options.params || {},
                id: Math.floor(Math.random() * 1000000000)
            })
        });

        if (!response.ok) {
            throw new Error("HTTP error " + response.status);
        }

        const data = await response.json();
        if (data.error) {
            throw new Error(data.error.data ? data.error.data.message : data.error.message);
        }
        return data.result;
    },

    start: function () {
        this._super.apply(this, arguments);
        console.log("RFP Portal Interactions: Widget Started for selector", this.selector);

        // 3. Drag and Drop (Native Events)
        // We bind native events to a container (e.g. tbody)
        const list = this.el.querySelector('#rfp_section_list');
        if (list) {
            list.addEventListener('dragstart', this._onDragStart.bind(this), false);
            list.addEventListener('dragover', this._onDragOver.bind(this), false);
            list.addEventListener('drop', this._onDrop.bind(this), false);
            list.addEventListener('dragleave', this._onDragLeave.bind(this), false);
            list.addEventListener('dragend', this._onDragEnd.bind(this), false);
        }

        // Initial checks for Gap Analysis
        if (this.$('.rfp-input-group').length) {
            this._checkDependencies();
            this._checkSpecifyTriggers();
        }

        // Auto-Start Polling if on Generating Page
        if (this.$('#rfp_generation_progress').length) {
            this._startGenerationPolling();
        }

        // Initialize Quill Editors
        this._initQuillEditors();
    },

    // --- PHASE 2: STRUCTURE EDITOR ---

    _onAddSection: function (ev) {
        ev.preventDefault();
        const $tbody = this.$('#rfp_section_list');
        const count = $tbody.find('tr').length;
        const newSeq = (count + 1) * 10;

        // Create internal ID for UI tracking (starts with new_)
        const tempId = `new_${Date.now()}`;

        const rowHtml = `
            <tr class="rfp-section-row" data-section-id="${tempId}" draggable="true">
                <td class="align-middle text-center" style="cursor: move;">
                    <i class="fa fa-bars text-muted handle"/>
                    <input type="hidden" class="section-seq" value="${newSeq}"/>
                </td>
                <td>
                    <input type="text" class="form-control section-title" placeholder="New Section"/>
                </td>
                <td class="text-end">
                    <button class="btn btn-sm btn-outline-danger btn-delete-section">
                        <i class="fa fa-trash"></i>
                    </button>
                </td>
            </tr>
        `;
        $tbody.append(rowHtml);
    },

    _onDeleteSection: function (ev) {
        ev.preventDefault();
        $(ev.currentTarget).closest('tr').remove();
    },

    // Drag and Drop Handlers
    _onDragStart: function (ev) {
        // Check target
        const target = ev.target.closest('tr');
        if (!target) return;

        this.draggedRow = target;
        ev.dataTransfer.effectAllowed = 'move';
        // Simple visual feedback
        target.classList.add('opacity-50');
    },

    _onDragOver: function (ev) {
        ev.preventDefault();
        ev.dataTransfer.dropEffect = 'move';

        const targetRow = ev.target.closest('tr');
        if (targetRow && targetRow !== this.draggedRow) {
            // Visual feedback: line
            // Determine if top or bottom
            // We'll just underline the row for now to show "it will go near here"
            // Or better: Use a simple border-bottom on targetRow
            this._clearDragVisuals();

            if (this._isBefore(this.draggedRow, targetRow)) {
                // Dragging UP (Target is above Dragged) -> Place BEFORE Target
                targetRow.style.borderTop = "2px solid #0dcaf0";
            } else {
                // Dragging DOWN (Target is below Dragged) -> Place AFTER Target
                targetRow.style.borderBottom = "2px solid #0dcaf0";
            }
            targetRow.classList.add('rfp-drop-target');
        }
    },

    _onDragLeave: function (ev) {
        // We only clear if leaving the row? 
        // Logic is tricky because of children. 
        // Simplest is to clear everything on Drop/End.
    },

    _onDragEnd: function (ev) {
        this._clearDragVisuals();
        if (this.draggedRow) {
            this.draggedRow.classList.remove('opacity-50');
            this.draggedRow = null;
        }
    },

    _clearDragVisuals: function () {
        // Iterate all rows and remove styles
        const rows = this.el.querySelectorAll('.rfp-section-row');
        rows.forEach(r => {
            r.style.borderTop = "";
            r.style.borderBottom = "";
            r.classList.remove('rfp-drop-target');
        });
    },

    _onDrop: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        this._clearDragVisuals();

        const targetRow = ev.target.closest('tr');
        if (this.draggedRow && targetRow && this.draggedRow !== targetRow) {
            // Check position
            if (this._isBefore(this.draggedRow, targetRow)) {
                // Dragging UP -> Insert Before
                targetRow.parentNode.insertBefore(this.draggedRow, targetRow);
            } else {
                // Dragging DOWN -> Insert After
                targetRow.parentNode.insertBefore(this.draggedRow, targetRow.nextSibling);
            }
        }
    },

    _isBefore: function (el1, el2) {
        if (el2.parentNode === el1.parentNode) {
            for (let cur = el1.previousSibling; cur; cur = cur.previousSibling) {
                if (cur === el2) return true;
            }
        }
        return false;
    },

    // Unified Save Function logic
    _saveStructure: async function (projectId, generate) {
        // 1. Collect Data & Recalculate Sequence
        const sections = [];
        let seqCounter = 10;

        this.$('.rfp-section-row').each(function () {
            const $row = $(this);
            const id = $row.data('section-id'); // int or "new_..."
            const title = $row.find('.section-title').val() || "New Section";

            // Overwrite stored sequence with new position-based sequence
            sections.push({
                id: id,
                sequence: seqCounter,
                section_title: title
            });
            seqCounter += 10;
        });

        if (!sections.length) {
            alert("You must have at least one section.");
            return null;
        }

        return await this._rpc({
            route: `/rfp/structure/save_and_generate/${projectId}`,
            params: {
                sections_data: sections,
                generate: generate
            }
        });
    },

    _onSaveStructure: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = this.$('#rfp_structure_editor').data('project-id');
        const originalText = $btn.html();

        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');

        try {
            const result = await this._saveStructure(projectId, false);
            if (result && result.status === 'success') {
                // Update IDs if necessary?
                // Ideally we'd replace the rows with returned clean IDs but reloading is simpler if we want to be pure.
                // For now, simple success feedback.
                $btn.addClass('btn-success').removeClass('btn-secondary');
                setTimeout(() => {
                    $btn.removeClass('btn-success').addClass('btn-secondary').html(originalText).prop('disabled', false);
                    // Reload to get real IDs? Not strictly needed for UX unless they delete immediately.
                    // A reload is safer to sync IDs.
                    window.location.reload();
                }, 1000);
            } else {
                alert("Error saving.");
                $btn.prop('disabled', false).html(originalText);
            }
        } catch (e) {
            console.error(e);
            $btn.prop('disabled', false).html(originalText);
        }
    },

    _onConfirmStructure: async function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = this.$('#rfp_structure_editor').data('project-id');

        // Disable Button
        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');

        // RPC Call
        try {
            const result = await this._saveStructure(projectId, true);

            if (result && result.status === 'success') {
                window.location.href = result.redirect;
            } else {
                alert("Error saving: " + (result ? result.error : 'Unknown'));
                $btn.prop('disabled', false).text('Generate Content');
            }
        } catch (e) {
            console.error(e);
            alert("Connection Error");
            $btn.prop('disabled', false).text('Generate Content');
        }
    },

    // --- PHASE 3: GENERATION POLLING ---

    _startGenerationPolling: function () {
        const $progressBar = this.$('#rfp_generation_progress');
        const projectId = $progressBar.data('project-id');
        const self = this;

        const interval = setInterval(async () => {
            try {
                const result = await self._rpc({
                    route: `/rfp/status/${projectId}`,
                    params: {}
                });

                // Update UI
                const pct = result.progress;
                $progressBar.css('width', pct + '%').text(pct + '%');

                if (result.status === 'completed' || result.status === 'completed_with_errors') {
                    clearInterval(interval);
                    $progressBar.removeClass('progress-bar-animated').addClass('bg-success');
                    self.$('#rfp_completion_area').removeClass('d-none');
                    self.$('h2').text("Generation Complete!");
                    self.$('.lead').text("Content is ready for your review.");
                }
            } catch (e) {
                console.error("Polling error", e);
            }
        }, 3000); // 3 seconds
    },

    // --- PHASE 4: CONTENT REVIEW ---

    _initQuillEditors: function () {
        if (typeof Quill === 'undefined') return;

        this.quillInstances = {};
        const self = this;

        this.$('.rfp-quill-editor').each(function () {
            const $el = $(this);
            const sectionId = $el.attr('id').replace('editor_', '');

            // Basic Toolbar
            const toolbarOptions = [
                [{ 'header': [2, 3, false] }],
                ['bold', 'italic', 'underline', 'strike'],
                [{ 'list': 'ordered' }, { 'list': 'bullet' }],
                ['clean']
            ];

            const quill = new Quill(this, {
                theme: 'snow',
                modules: {
                    toolbar: toolbarOptions
                }
            });

            self.quillInstances[sectionId] = quill;
        });
    },

    _onSaveContent: function (ev) {
        this._saveContentAction(ev, false);
    },

    _onSubmitContent: function (ev) {
        if (confirm("Are you sure you want to finalize? This will lock the document.")) {
            this._saveContentAction(ev, true);
        }
    },

    _saveContentAction: async function (ev, finish) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const projectId = $btn.data('project-id');
        const originalText = $btn.html();

        // 1. Collect Data From Quill
        const contentMap = {};

        if (this.quillInstances) {
            for (const [sectionId, quill] of Object.entries(this.quillInstances)) {
                // Get HTML
                const html = quill.root.innerHTML;
                contentMap[sectionId] = html;
            }
        } else {
            // Fallback if Quill failed to load
            this.$('.section-html-input').each(function () {
                const id = $(this).data('section-id');
                contentMap[id] = $(this).val(); // This is likely empty if Quill didn't init, logic fallback
            });
        }

        // 2. UI Feedback
        $btn.prop('disabled', true).html('<i class="fa fa-spinner fa-spin"></i>');

        // 3. RPC
        try {
            const result = await this._rpc({
                route: `/rfp/content/save/${projectId}`,
                params: {
                    sections_content: contentMap,
                    finish: finish
                }
            });

            if (result.status === 'success') {
                if (finish && result.redirect) {
                    window.location.href = result.redirect;
                } else {
                    // Flash success
                    $btn.addClass('btn-success').removeClass('btn-secondary');
                    setTimeout(() => {
                        $btn.removeClass('btn-success').addClass('btn-secondary').html(originalText).prop('disabled', false);
                    }, 1000);
                }
            } else {
                alert("Error: " + result.error);
                $btn.prop('disabled', false).html(originalText);
            }
        } catch (e) {
            console.error(e);
            alert("Error saving content.");
            $btn.prop('disabled', false).html(originalText);
        }
    },

    // --- GAP ANALYSIS (Original Logic Preserved) ---

    _onSubmit: function (ev) {
        if (this.$('#rfp_loading_overlay').length) {
            $('#rfp_loading_overlay').removeClass('d-none');
        }
    },

    _onSuggestionClick: function (ev) {
        ev.preventDefault();
        const $badge = $(ev.currentTarget);
        const value = $badge.data('value');
        const targetKey = $badge.data('target');
        const $input = this.$el.find(`[name="${targetKey}"]`);
        if ($input.length) {
            $input.val(value).trigger('change');
        }
    },

    _onIrrelevantToggle: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const targetId = $btn.data('target');
        const $box = this.$el.find(`#${targetId}`);
        const fieldKey = targetId.replace('irrelevant_', '');
        const $flag = this.$el.find(`[name="is_irrelevant_${fieldKey}"]`);
        const $inputGroup = $btn.closest('.rfp-input-group');
        let shouldShow = false;

        if ($btn.hasClass('btn-irrelevant-cancel')) {
            shouldShow = false;
        } else {
            shouldShow = $box.hasClass('d-none');
        }

        const $inputs = $inputGroup.find('input:not([type="hidden"]), select, textarea').not('.irrelevant-box input');

        if (shouldShow) {
            $box.removeClass('d-none');
            $flag.val('true');
            $inputs.each(function () {
                const $el = $(this);
                if ($el.prop('required')) {
                    $el.data('was-required', true);
                    $el.prop('required', false);
                }
            });
            $box.find('input[type="text"]').focus();
        } else {
            $box.addClass('d-none');
            $flag.val('false');
            $inputs.each(function () {
                const $el = $(this);
                if ($el.data('was-required')) {
                    $el.prop('required', true);
                    $el.removeData('was-required');
                }
            });
        }
    },

    _onInputChange: function () {
        this._checkDependencies();
        this._checkSpecifyTriggers();
    },

    _checkDependencies: function () {
        const self = this;
        this.$el.find('.rfp-input-group[data-depends-on]').each(function () {
            const $group = $(this);
            const dependsData = $group.data('depends-on');
            if (!dependsData || $.isEmptyObject(dependsData)) return;

            const depKey = dependsData.field_key;
            const depValue = dependsData.value;

            if (depKey && depValue) {
                const $depInput = self.$el.find(`[name="${depKey}"]`);
                let currentValue = "";

                if ($depInput.is(':radio')) {
                    currentValue = self.$el.find(`[name="${depKey}"]:checked`).val();
                } else if ($depInput.is(':checkbox')) {
                    if ($depInput.length > 1) {
                        if (self.$el.find(`[name="${depKey}"][value="${depValue}"]:checked`).length > 0) {
                            currentValue = depValue;
                        }
                    } else {
                        currentValue = $depInput.is(':checked') ? 'yes' : 'no';
                    }
                } else {
                    currentValue = $depInput.val();
                }

                const $inputs = $group.find('input:not([type="hidden"]), select, textarea').not('.irrelevant-box input');

                if (currentValue == depValue) {
                    $group.removeClass('d-none');
                    $inputs.each(function () {
                        const $el = $(this);
                        if ($el.data('dep-was-required')) {
                            $el.prop('required', true);
                            $el.removeData('dep-was-required');
                        }
                    });
                } else {
                    $group.addClass('d-none');
                    $inputs.each(function () {
                        const $el = $(this);
                        if ($el.prop('required')) {
                            $el.data('dep-was-required', true);
                            $el.prop('required', false);
                        }
                    });
                }
            }
        });
        this._checkSpecifyTriggers();
    },

    _checkSpecifyTriggers: function () {
        const self = this;
        this.$el.find('.rfp-input-group[data-specify-triggers]').each(function () {
            const $group = $(this);
            const fieldKey = $group.data('field-key');
            let triggers = $group.data('specify-triggers');
            if (typeof triggers === 'string') {
                try { triggers = JSON.parse(triggers); } catch (e) { triggers = []; }
            }
            if (!triggers || !triggers.length) return;

            let selectedValues = [];
            const $inputs = self.$el.find(`input[name="${fieldKey}"]:checked`);
            $inputs.each(function () { selectedValues.push($(this).val()); });

            const $specifyInput = self.$el.find(`input[name="${fieldKey}_specify"]`);
            const isMatch = selectedValues.some(val => triggers.includes(val));

            if (isMatch) {
                $specifyInput.removeClass('d-none').prop('required', true);
            } else {
                $specifyInput.addClass('d-none').prop('required', false).val('');
            }
        });
    }
});
