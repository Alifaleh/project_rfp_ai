/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

publicWidget.registry.RfpPortalInteractions = publicWidget.Widget.extend({
    selector: '.rfp-portal-wrapper', // Specific selector for the new wrapper
    events: {
        'click .btn-suggestion': '_onSuggestionClick',
        'click .btn-irrelevant-toggle': '_onIrrelevantToggle', // Menu item
        'click .btn-irrelevant-cancel': '_onIrrelevantToggle', // Cancel button in box
        'change .rfp-input-group input, .rfp-input-group select, .rfp-input-group textarea': '_onInputChange',
        'submit form': '_onSubmit',
    },

    start: function () {
        this._super.apply(this, arguments);
        console.log("RFP Portal Interactions Loaded");
        this._checkDependencies(); // Initial check
        this._checkSpecifyTriggers();
    },

    // --- Event Handlers ---

    _onSubmit: function (ev) {
        // Show loading overlay
        $('#rfp_loading_overlay').removeClass('d-none');
        // We do NOT prevent default, we want the form to submit.
        // The overlay will just stay until the new page loads.
    },

    _onSuggestionClick: function (ev) {
        ev.preventDefault();
        const $badge = $(ev.currentTarget);
        const value = $badge.data('value');
        const targetKey = $badge.data('target');
        
        // Find target input
        const $input = this.$el.find(`[name="${targetKey}"]`);
        
        if ($input.length) {
            $input.val(value);
            // Trigger change to update any dependencies
            $input.trigger('change');
        }
    },

    _onIrrelevantToggle: function (ev) {
        ev.preventDefault();
        const $btn = $(ev.currentTarget);
        const targetId = $btn.data('target'); // ID of the irrelevant box
        const $box = this.$el.find(`#${targetId}`);
        const fieldKey = targetId.replace('irrelevant_', '');
        const $flag = this.$el.find(`[name="is_irrelevant_${fieldKey}"]`);
        const $inputGroup = $btn.closest('.rfp-input-group');
        
        // Determine action: Hide if cancel button clicked, otherwise Toggle
        let shouldShow = false;
        
        if ($btn.hasClass('btn-irrelevant-cancel')) {
            shouldShow = false;
        } else {
            // Toggle
            shouldShow = $box.hasClass('d-none');
        }

        if (shouldShow) {
            // Show it (Mark as Irrelevant)
            $box.removeClass('d-none');
            $flag.val('true');
            
            // Focus the reason input for better UX
            $box.find('input[type="text"]').focus();
            
        } else {
            // Hide it (Cancel)
            $box.addClass('d-none');
            $flag.val('false');
        }
    },

    _onInputChange: function () {
        this._checkDependencies();
    },

    // --- Logic ---

    _checkDependencies: function () {
        const self = this;
        // Iterate over all input groups that have dependencies
        this.$el.find('.rfp-input-group[data-depends-on]').each(function () {
            const $group = $(this);
            const dependsData = $group.data('depends-on'); // Should be JSON object
            
            if (!dependsData || $.isEmptyObject(dependsData)) {
                return;
            }

            // dependsData format: { "field_key": "some_value" }
            // Currently assuming single dependency for simplicity based on schema
            const depKey = dependsData.field_key;
            const depValue = dependsData.value;

            if (depKey && depValue) {
                // Find value of dependency field
                const $depInput = self.$el.find(`[name="${depKey}"]`);
                let currentValue = "";

                if ($depInput.is(':radio')) {
                    currentValue = self.$el.find(`[name="${depKey}"]:checked`).val();
                } else if ($depInput.is(':checkbox')) {
                    // Start simple: Checkbox group or boolean
                    if ($depInput.length > 1) {
                         // Multiselect checkbox group? 
                         // Logic: if ANY checked value matches? 
                         // For now let's assume simple exact match logic isn't fully robust for multiselect
                         // but standard boolean or single select is fine.
                         // Only checking if AT LEAST one with that value is checked
                         if (self.$el.find(`[name="${depKey}"][value="${depValue}"]:checked`).length > 0) {
                             currentValue = depValue;
                         }
                    } else {
                        // Boolean
                        currentValue = $depInput.is(':checked') ? 'yes' : 'no'; 
                    }
                } else {
                    currentValue = $depInput.val();
                }

                // Comparison
                // Loose comparison to handle number vs string
                if (currentValue == depValue) {
                    $group.removeClass('d-none');
                } else {
                    $group.addClass('d-none');
                }
            }
        });

        this._checkSpecifyTriggers();
    },

    /**
     * Checks if any inputs (Radio) trigger a "Specify" text field.
     */
    _checkSpecifyTriggers: function () {
        const self = this;
        this.$el.find('.rfp-input-group[data-specify-triggers]').each(function () {
            const $group = $(this);
            const fieldKey = $group.data('field-key');
            let triggers = $group.data('specify-triggers');
            
            // Safety parsing if it's a string (though Odoo usually parses data- attributes if valid JSON, otherwise string)
            if (typeof triggers === 'string') {
                try {
                    triggers = JSON.parse(triggers);
                } catch (e) {
                    triggers = [];
                }
            }
            
            if (!triggers || !triggers.length) return;

            // Find current value
            let currentValue = "";
            const $radio = self.$el.find(`input[name="${fieldKey}"]:checked`);
            if ($radio.length) {
                currentValue = $radio.val();
            }

            // Find Specify Input
            const $specifyInput = self.$el.find(`input[name="${fieldKey}_specify"]`);
            
            // Check match
            if (triggers.includes(currentValue)) {
                $specifyInput.removeClass('d-none');
                $specifyInput.prop('required', true); // Require if shown
            } else {
                $specifyInput.addClass('d-none');
                $specifyInput.prop('required', false);
                $specifyInput.val(''); // Clear value when hidden
            }
        });
    }
});
