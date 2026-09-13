(function($) {
    /**
     *
     */
    $.fn.cdedbTabNavigation = function () {
        // Determine which tab is supposed to be active.
        let active_tab_input = $(this).find(':input[name="nav_tab_active"]');
        let active_tab =  window.location.hash
            || new URLSearchParams(window.location.search).get('nav_tab_active')
            || active_tab_input.val();

        // Show navbar and activate first tab.
        let nav_tabs = $(this).find('.nav-tabs').show().find('a');
        nav_tabs.first().tab('show');
        nav_tabs
            // Activate the specified tab.
            .each(function() {
                if (active_tab === $(this).data('target')) {
                    $(this).tab('show');
                    return false;
                }
            })
            .each(function() {
                let nav_tab = $(this);
                $($(this).data('target')).on("has-error-change", function () {
                    let error = nav_tab.find(".nav-tab-error");
                    if ($(this).find(".has-error").length > 0) {
                        error.show();
                    } else {
                        error.hide();
                    }
                }).trigger("has-error-change");
            })
            // Update current URL with new target.
            .on('shown.bs.tab', function (event) {
                let target = $(event.target).data('target');
                history.replaceState(null, "", target);
                active_tab_input.val(target);
            });

        // Hide alternate tab headings.
        $(this).find('.tab-heading-alt').hide();
    };
})(jQuery);
