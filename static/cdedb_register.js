(function($){
    $.fn.dynamicCourseChoices = function (ccos_per_part, part_map) {
        /**
         * Function to dynamically hide both entire course choice containers and
         * individual choices depending on selected part checkboxes.
         *
         * Do nothing if no part checkboxes exist (i.e. only one part exists).
         *
         * @param ccos_per_part A map of part id to available ccos in (or implied by) this part.
         * @param part_map A map of course id to a map of track group id to a list of
         *     part ids that imply this track group for this course.
         *     In other words: A course should only be shown in a track group if
         *     at least one of these parts is active.
         */
        form = $(this);

        part_checkboxes = form.find('[type="checkbox"][name="parts"]');
        containers = form.find('.course_choice_container');

        /**
         * Map part to part selection checkbox ($-encapsulated)
         */
        part_checkbox_map = {};
        part_checkboxes.each(function(){
            part_checkbox_map[$(this).val()] = $(this);
        });

        updateCourseChoiceContainers = function() {
            /**
             * Hide everything, then for every active part show all ccos implied by the part..
             */
            containers.each(function(){
                $(this).hide();
            });
            Object.keys(ccos_per_part).forEach(function(key){
                if (part_checkbox_map[key].prop('checked'))
                    ccos_per_part[key].forEach(function(element){
                        $('#course-choice-container-' + element).show();
                    });
            });
        };

        var updateCourseChoiceOptions = function() {
            $('.choice_group_select > option').each(function() {
                /**
                 * For every option in a select in a ccs group:
                 *     If the not at least one of the implying parts for this course
                 *     and this ccs group is active, hide that choice and deselect it.
                 */
                course_id = $(this).val();
                track_group_id = $(this).parent().attr('track_group_id');
                if (!course_id || part_map[course_id][track_group_id].some(
                        (part_id) => part_checkbox_map[part_id].prop('checked'))
                ) {
                    $(this).show();
                } else {
                    $(this).hide();
                    if ($(this).parent().val() == course_id) {
                        $(this).parent().val("");
                    }
                };
            });
        }

        if (part_checkboxes.length) {
            part_checkboxes.change(updateCourseChoiceContainers);
            part_checkboxes.change(updateCourseChoiceOptions);
            updateCourseChoiceContainers();
        }

        return this;
    }

    $.fn.cdedbFeePreview = function(constants) {
        /**
         * Function to read form inputs and presend them to a special endpoint to
         * calculate a preview of the final event fee.
         */
        form = $(this);

        // Find input elements.
        part_checkboxes = form.find('[type="checkbox"][name="parts"]');
        field_checkboxes = form.find('[type="checkbox"][id^="event-input-fields"]');
        field_selects = form.find('select[id^="event-input-fields"]');

        // Find input elements for orga preview mode.
        is_orga_checkbox = form.find('#fee-precompute-is-orga');
        is_member_checkbox = form.find('#fee-precompute-is-member');

        // Find the elements that will be replaced by this function.
        fee_preview = form.find('[id="fee-preview"]');
        nonmember_surcharge = form.find('[id="nonmember-surcharge"]');
        fee_summary = form.find('[id="active-fee"]');

        updateFeePreview = function() {
            /**
             *  Gather values of checked part checkboxes.
             */
            var part_ids = [];
            if (constants['part_ids']) {
                part_ids = constants['part_ids']
            } else {
                part_checkboxes.each(function () {
                    if ($(this).prop('checked')) {
                        part_ids.push($(this).val());
                    }
                });
            }

            /**
             * Build params for sending to precompute endpoint.
             * Only send `is_orga` and `is_member` if the checkboxes exist.
             */

            params = {
                persona_id: constants['persona_id'],
                part_ids: part_ids.join(","),
                is_orga: constants['is_orga'],
                is_member: constants['is_member'],
            }

            /**
             *  Gather field ids of bool field inputs.
             *
             * Note that these might be either checkboxes or selects.
             * They are wrapped in a div, which has the field id as a data attribute.
             */

            field_checkboxes.each(function() {
                field_id = $(this).parents('[id^="field"]').data('field_id');
                params[`field.${field_id}`] = $(this).prop('checked');
            });
            field_selects.each(function() {
                field_id = $(this).parents('[id^="field"]').data('field_id');
                params[`field.${field_id}`] = $(this).val() == 'True';
            });

            if (is_orga_checkbox.length) {
                params['is_orga'] = is_orga_checkbox.prop('checked');
            }
            if (is_member_checkbox.length) {
                params['is_member'] = is_member_checkbox.prop('checked');
            }

            $.get(constants['endpoint'], params,
                function(result) {
                    /**
                     * Replace the content of the fee information with the returned string.
                     */
                    fee_preview.html(result["fee"]);
                    /**
                     * If the nonmember info should be shown replace the text and show its parent, otherwise hide it.
                     */
                    if (result["show_nonmember"]) {
                        nonmember_surcharge.html(result["nonmember"]);
                        nonmember_surcharge.parent().show();
                    }
                    else {
                        nonmember_surcharge.parent().hide();
                    }
                    /**
                     * If the more advanced summary exists, show the respective returned visual debug string in every line.
                     *
                     * Color the lines and display a deko checkbox depending on whether each fee is active or not.
                     */
                    if (fee_summary) {
                        fee_summary.each(function() {
                            $(this).find('#active-fee-condition').html(result["visual_debug"][$(this).data("fee_id")]);
                            title = $(this).find('#active-fee-title');
                            orig_title = title.data('orig-title');
                            if ($.inArray($(this).data('fee_id'), result["active_fees"]) >= 0) {
                                title.html(constants['deko_true'] + orig_title);
                                title.attr('title', constants['title_active']).removeClass('alert-danger').addClass('alert-success');
                            } else {
                                title.html(constants['deko_false'] + orig_title);
                                title.attr('title', constants['title_inactive']).removeClass('alert-success').addClass('alert-danger');
                            }
                        });
                    }
                }
            );
        }

        if (part_checkboxes.length) {
            part_checkboxes.change(updateFeePreview);
        }
        if (field_checkboxes.length) {
            field_checkboxes.change(updateFeePreview);
        }
        if (field_selects.length) {
            field_selects.change(updateFeePreview);
        }
        if (is_orga_checkbox.length) {
            is_orga_checkbox.change(updateFeePreview);
        }
        if (is_member_checkbox.length) {
            is_member_checkbox.change(updateFeePreview);
        }
        if (fee_summary.length) {
            fee_summary.parents('table').show();
        }

        updateFeePreview();
        return this;
    }
})(jQuery);
