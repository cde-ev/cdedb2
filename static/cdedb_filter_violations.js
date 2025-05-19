(function($) {
    /**
     *
     */
    $.fn.cdedbFilterViolations = function(
            results_selector,
            select_event_url='',
            event_options=[],
            violation_severity_to_int={},
            violation_kind_to_int={},
    ) {
        // Turn radio groups into buttongroups.
        $(this).find('.row[role=radiogroup]')
            .attr('data-toggle', 'buttons')
            .addClass('btn-group')
            .removeClass('row')
            .children().each(function () {
                $(this).find('label:has(:input:checked)').addClass('active');
                $(this).replaceWith($(this).find('label').addClass('btn btn-primary'));
            });

        // Find severity filter inputs.
        let min_severity_input = $(this).find(':input[name="min_severity"]');
        let violation_kind_input = $(this).find(':input[name="violation_kind"]');
        // Find event filter inputs.
        let event_ids_input = $(this).find(':input[name="event_ids"]');
        let is_archived_input = $(this).find(':input[name="is_archived"]');
        let is_balanced_input = $(this).find(':input[name="is_balanced"]');
        let is_concluded_input = $(this).find(':input[name="is_concluded"]');

        if (event_ids_input.length) {
            // Activate event selectize.
            event_ids_input.removeAttr('placeholder').cdedbSearchEvent(
                select_event_url,
                event_options,
                true,
            );
        }

        let update_results = function () {
            // Extract severity $(this) values if possible.
            let min_severity_text = min_severity_input.length ? min_severity_input.val() : "";
            let min_severity_val = min_severity_text ? violation_severity_to_int[min_severity_text.split('.', 2)[1]] ?? -1 : -1;
            let violation_kind_text = violation_kind_input.length ? violation_kind_input.val() : "";
            let violation_kind_val = violation_kind_text ? violation_kind_to_int[violation_kind_text.split('.', 2)[1]] ?? -1 : -1;
            // Extract event $(this) values if possible.
            let event_ids_list = event_ids_input.length ? event_ids_input.val().split(',').filter(Boolean) : [];
            let is_archived_val = is_archived_input.length ? parseInt(is_archived_input.filter(':checked').val()) : -1;
            let is_balanced_val = is_balanced_input.length ? parseInt(is_balanced_input.filter(':checked').val()) : -1;
            let is_concluded_val = is_concluded_input.length ? parseInt(is_concluded_input.filter(':checked').val()) : -1;

            // Unhide all events, then...
            $(results_selector).find('div.event').each(function () {
                $(this).removeClass('softhide');

                // ... hide those not in the list, if the list isn't empty, ...
                if (event_ids_list.length && !event_ids_list.includes(String($(this).data("event_id")))) {
                    console.log("Hiding ", $(this).data("event_id"), " due to event_ids.")
                    $(this).addClass('softhide');
                }
                // ... hide those that don't match the selected archival state, ...
                if (is_archived_val !== -1 && $(this).hasClass('event-is-archived') !== Boolean(is_archived_val)) {
                    console.log("Hiding ", $(this).data("event_id"), " due to is-archived.")
                    $(this).addClass('softhide');
                }
                // ... hide those that don't match the selected balance state, ...
                if (is_balanced_val !== -1 && $(this).hasClass('event-is-balanced') !== Boolean(is_balanced_val)) {
                    console.log("Hiding ", $(this).data("event_id"), " due to is-balanced.")
                    $(this).addClass('softhide');
                }
                // ... hide those that don't match the selected conlusion state.
                if (is_concluded_val !== -1 && $(this).hasClass('event-is-concluded') !== Boolean(is_concluded_val)) {
                    console.log("Hiding ", $(this).data("event_id"), " due to is-concluded.")
                    $(this).addClass('softhide');
                }
            })

            // Unhide all violations, then ...
            $(results_selector).find('.violations').removeClass('softhide').each(function () {
                // ... if min_severity is given ...
                if (min_severity_val !== -1) {
                    // ... hide those that don't match the min, ...
                    if ($(this).data('max_severity') < min_severity_val) {
                        $(this).addClass('softhide');
                    }
                    // ... then show the correct version of the label, depending on min_severity, ...
                    $(this).find('.violations-only').addClass('softhide').each(function () {
                        if ($(this).data('severity') === min_severity_val) {
                            $(this).removeClass('softhide');
                            let enclosing_link = $(this).closest('a');
                            let new_url = new URL(enclosing_link.attr('href'), window.location.origin);
                            new_url.searchParams.set('min_severity', min_severity_text);
                            enclosing_link.attr('href', new_url.toString());
                        }
                    })
                }
                // ... hide those that match the given kind (if given).
                if (violation_kind_val !== -1 && $(this).data('violation_kind') !== violation_kind_val) {
                    $(this).addClass('softhide');
                }
            });

            // Replace the current url in the history with the new filter.
            history.replaceState(null, "", window.location.pathname + "?" + $(this).closest('form').serialize() + window.location.hash);
        }
        $(this).find(':input').on('change', update_results);
        // Submit currently active tab to keep it active.
        if (typeof $().cdedbGetActiveTab !== "undefined") {
            $(this).on("submit", function (event) {
                event.preventDefault();
                $(this).append($('<input />', {
                    "type": "hidden",
                    "name": "nav_tab_active",
                    "value": $().cdedbGetActiveTab(),
                }));
                this.submit();
            })
        }
    };
})(jQuery);
