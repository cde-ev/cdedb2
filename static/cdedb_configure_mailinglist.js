(function($){
    $.fn.cdedbChangeMailinglist = function(part_specific_inputs_url) {
        var names = ['ml_type','event_id','assembly_id'];
        var fields = {};
        for (var i = 0; i < names.length; i++) {
            fields[names[i]] = $(this).find('[name="'+ names[i] +'"]');
        }
        var part_id_container = $(this).find('#event-part-id-container');
        var part_group_id_container = $(this).find('#event-part-group-id-container');

        /**
         * Function to update visibility of selectboxes and event participant checkboxes.
         * Should be called on every update of one of the selectboxes defined in 'names'.
         */
        function update_view() {
            // Calculate visibility of event/assembly select boxes
            // from cdedb.database.constants.MailinglistTypes
            var visible = {
                'event_id':     (
                    fields['ml_type'].val() == "MailinglistTypes.event_associated" ||
                    fields['ml_type'].val() == "MailinglistTypes.event_orga"),
                'assembly_id':  (
                    fields['ml_type'].val() == "MailinglistTypes.assembly_associated" ||
                    fields['ml_type'].val() == "MailinglistTypes.assembly_presider")
                                            // "MailinglistTypes.assembly_opt_in" is not bound to a
                                            // concrete assembly, so an assembly_id must not be specified for this type
            };

            // Change visibility of event/assembly select boxes and clear boxes
            for (var i in visible) {
                if (visible[i]) {
                    fields[i].closest('.form-group').show();
                } else {
                    fields[i].closest('.form-group').hide();
                    fields[i].val('');
                }
            }
        }

        // Add event handler and call function once on document load
        for (var i in fields) {
            fields[i].change(update_view);
        }
        update_view();

        let form = $(this);

        function update_part_specific_inputs() {
            let event_specific_inputs = form.find('.event-specific');
            if (fields['event_id'].val() !== '') {
                event_specific_inputs.closest('.form-group').show();
                $.get(part_specific_inputs_url, {'event_id': fields['event_id'].val()}, (response) => {
                    part_id_container.html(response['event_part_id']);
                    part_group_id_container.html(response['event_part_group_id']);
                });
            } else {
                event_specific_inputs.closest('.form-group').hide();
                if (event_specific_inputs.is(':checkbox')) {
                    event_specific_inputs.prop('checked',false);
                }
            }
        }
        fields['event_id'].change(update_part_specific_inputs);

        return this;
    }
})(jQuery);
