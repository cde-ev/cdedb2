(function($){
    $.fn.cdedbConfigureMailinglist = function(part_specific_inputs_url, subject_prefix_preview_text) {
        /**
         * Function to update visibility of event id and assembly id inputs,
         * depending on mailinglist type.
         */

        let names = ['ml_type','event_id','assembly_id'];
        let fields = {};
        for (let i = 0; i < names.length; i++) {
            fields[names[i]] = $(this).find('[name="'+ names[i] +'"]');
        }
        function update_view() {
            /**
             * Calculate visibility of event/assembly select boxes
             * from cdedb.database.constants.MailinglistTypes.
             */
            let visible = {
                'event_id':     (
                    fields['ml_type'].val() === "MailinglistTypes.event_associated" ||
                    fields['ml_type'].val() === "MailinglistTypes.event_orga"),
                'assembly_id':  (
                    fields['ml_type'].val() === "MailinglistTypes.assembly_associated" ||
                    fields['ml_type'].val() === "MailinglistTypes.assembly_presider")
            };

            // Change visibility of event/assembly select boxes and clear boxes.
            for (let key in visible) {
                if (visible[key]) {
                    fields[key].closest('.form-group').show();
                } else {
                    fields[key].closest('.form-group').hide();
                    fields[key].val('');
                }
            }
        }

        // Add event handler and call function once on document load
        for (let i in fields) {
            fields[i].change(update_view);
        }
        update_view();


        /**
         * Function to update the options for event specific inputs based on the
         * selected event.
         */

        let event_specific_input_groups = $(this).find('.event-specific');

        function update_event_specific_inputs() {

            if (fields['event_id'].val() !== '') {
                // If an event is selected, show and replace the event specific inputs.
                event_specific_input_groups.show();
                $.get(
                    part_specific_inputs_url,
                    {'event_id': fields['event_id'].val()},
                    (response) => {
                        for (let key in response) {
                            let container_id = '#' + key.replaceAll('_', '-') + '-container';
                            container = event_specific_input_groups.filter(container_id);
                            if (container) {
                                container.html(response[key]);
                            }
                        }
                });
            } else {
                // If no event is selected, hide the
                event_specific_input_groups.hide();
                let event_specific_inputs = event_specific_input_groups.find('input select');
                if (event_specific_inputs.is(':checkbox')) {
                    event_specific_inputs.prop('checked',false);
                } else {
                    event_specific_inputs.val('');
                }
            }
        }
        fields['event_id'].on('change', update_event_specific_inputs);
        if (fields['event_id'].val() === '') {
            event_specific_input_groups.hide();
        }


        /**
         * Function to update the addon of the local part field according to the selected domain.
         */

        let domain_inp = $(this).find("[name='domain']");
        let local_part_addon = $(this).find("[name='local_part'] ~ .input-group-addon");

        function update_domain() {
            local_part_addon.text(domain_inp.find(':selected').text());
        }
        domain_inp.on('change', update_domain);
        update_domain();


        /**
         * Function to display preview of subject prefix.
         */

        let subject_prefix_inp = $(this).find("[name='subject_prefix']");
        let subject_prefix_preview = subject_prefix_inp.siblings("p.help-block").first();
        subject_prefix_preview.html(subject_prefix_preview_text);


        function build_preview() {
            // If subject_prefix is empty, mailman also won't add any braces.
            subject_prefix_preview.find('#subject-prefix-preview').text(
                subject_prefix_inp.val() === '' ?
                    '' :
                    "[" + escapeHtml(subject_prefix_inp.val()) + "] "
            );
        }

        subject_prefix_inp.on('input', build_preview);
        build_preview();

        return this;
    }
})(jQuery);
