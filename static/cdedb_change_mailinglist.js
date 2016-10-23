(function($){
    $.fn.cdedbChangeMailinglist = function() {
        var names = ['audience_policy','event_id','assembly_id','gateway'];
        var fields = {};
        for (var i in names) {
            fields[names[i]] = $(this).find('[name="'+ names[i] +'"]');
        }
        var boxes = $(this).find('[name="registration_stati"]');

        /**
         * Function to update visiblity of selectboxes and event participant checkboxes.
         * Should be called on every update of one of the selectboxes defined in 'names'.
         */
        function update_view() {
            // Calculate visibility of event/assembly/gateway select boxes
            var visible = {
                'event_id':     (fields['audience_policy'].val() == 1 && fields['assembly_id'].val() == ''
                                    || fields['audience_policy'].val() == 3)
                                && fields['gateway'].val() == '',
                'assembly_id':  (fields['audience_policy'].val() == 1 && fields['event_id'].val() == ''
                                    || fields['audience_policy'].val() == 2)
                                && fields['gateway'].val() == '',
                'gateway':      fields['event_id'].val() == ''
                                    && fields['assembly_id'].val() == ''
            };

            // Change visibility of event/assembly/gateway select boxes and clear boxes
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
})(jQuery)
