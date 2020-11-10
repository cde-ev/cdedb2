(function($){
    $.fn.cdedbChangeMailinglist = function() {
        var names = ['ml_type','event_id','assembly_id'];
        var fields = {};
        for (var i = 0; i < names.length; i++) {
            fields[names[i]] = $(this).find('[name="'+ names[i] +'"]');
        }
        var boxes = $(this).find('[name="registration_stati"]');

        /**
         * Function to update visibility of selectboxes and event participant checkboxes.
         * Should be called on every update of one of the selectboxes defined in 'names'.
         */
        function update_view() {
            // Calculate visibility of event/assembly select boxes
            // numeric values from cdedb.database.constants.MailinglistTypes
            // 20 = participant list; 21 = orga list; 30 = participant list
            var visible = {
                'event_id':     (fields['ml_type'].val() == 20 || fields['ml_type'].val() == 21),
                'assembly_id':  (fields['ml_type'].val() == 30 || fields['ml_type'].val() == 32)
                                            // ml type 31 (assembly_opt_in) is not bound to a
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

            // Calculate and change visibility of participant checkboxes
            var box_visibility = fields['event_id'].val() != '';
            if (box_visibility) {
                boxes.first().closest('.form-group').show();
            } else {
                boxes.first().closest('.form-group').hide();
                boxes.prop('checked',false);
            }
        }

        // Add event handler and call function once on document load
        for (var i in fields) {
            fields[i].change(update_view);
        }
        update_view();

        return this;
    }
})(jQuery);
