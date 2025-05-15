(function($) {
    /**
     *
     */
    $.fn.cdedbTabNavigation = function () {
        // Prevent scroll to tab container.
        $(window).scrollTop(0);

        // Show navbar and activate first tab.
        let nav_tabs = $(this).find('.nav-tabs').show().find('a');
        nav_tabs.first().tab('show');
        nav_tabs
            // Activate the specified tab.
            .each(function() {
                if ($().cdedbGetActiveTab() === $(this).data('target')) {
                    $(this).tab('show');
                    return false;
                }
            })
            // Update current URL with new target.
            .on('shown.bs.tab', function (event) {
                history.replaceState(null, "", $(event.target).data('target'));
            });

        // Hide alternate tab headings.
        $(this).find('.tab-heading-alt').hide();

    };

    /**
     * Retrieve active tab from URL hash or GET parameter.
     *
     */
    $.fn.cdedbGetActiveTab = function () {
        return window.location.hash || new URLSearchParams(window.location.search).get('nav_tab_active');
    }

})(jQuery);
