(function($) {
    /**
     * Selectize for a past course input based on the selected past event.
     *
     * Can be applied to a jQuery object containing more than one pcourse id input, but will only ever consider the first matched pevent id input.
     *
     * @param optionsByPastEvent: A mapping of past event id to list of json objects with the courses for that event.
     */
    $.fn.cdedbSelectPastCourse = function (optionsByPastEvent, sentinelValue=1) {
        pastCourseSelect = $(this);
        pastEventSelect = pastCourseSelect.closest("form").find(':input.pcourse-pevent-input');
        prevPastEventInput = pastCourseSelect.closest("form").find(':input[name="prev_pevent_id"]')

        form = pastCourseSelect.closest("form");
        pastCourseInputGroup = form.find(".pcourse-input");
        pastCourseNoEventInfo = form.find(".pcourse-noevent-info");
        pastCourseNoCoursesInfo = form.find(".pcourse-nocourses-info");

        form.find(".pcourse-nojs-info").hide();

        updateCourseSelect = function () {
            prevPastEventInput.val(pastEventSelect.val());
            if (pastEventSelect.val() === "") {
                pastCourseNoEventInfo.show();
                pastCourseInputGroup.hide();
                pastCourseNoCoursesInfo.hide();
                pastCourseSelect.val("");
            } else {
                if (optionsByPastEvent === null) {
                    pastCourseSelect.cdedbSelectize();
                    return;
                }
                options = optionsByPastEvent[pastEventSelect.val()] ?? [];

                if (options.length) {
                    pastCourseInputGroup.show();
                    pastCourseNoCoursesInfo.hide();
                } else {
                    pastCourseNoCoursesInfo.show();
                    pastCourseInputGroup.hide();
                }
                pastCourseNoEventInfo.hide();

                // .selectize does not work with jQuery objects, so do this individually for each one.
                pastCourseSelect.each(function () {
                    if (this.selectize) {
                        this.selectize.setValue("");
                        this.selectize.clearOptions();
                        this.selectize.addOption(options);
                    } else {
                        $(this).cdedbSelectize(options);
                    }
                });
            };
        }

        pastEventSelect.on("change", updateCourseSelect);
        updateCourseSelect();
    }
})(jQuery);
