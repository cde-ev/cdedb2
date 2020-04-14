(function($) {
    /**
     * Simple jQuery plugin for collapsable lists for profile history.
     *
     * @param labels An object of translated labels to be used in HTML objects. Must contain:
     *        'more_versions' (with '{num}' placeholder for number of versions)
    */
    $.fn.cdedbHistoryCollapse = function(labels) {
        $(this).each(function() {
            var $element = $(this);
            var $rows = $element.find('.history-row:not(.pending)');
            var $crows = $rows.slice(0, -1);
            
            if ($rows.length < 3)
                return;
            
            $crows.addClass('collapse').hide();
            
            var $more_row = $('<div></div>', {'class': 'row history-row more', 'tab-index': '0'})
                .text((labels['more_versions']).replace('{num}', String($rows.length - 1)));
            
            var $hide_button = $('<button></button>',
                    {'type': 'button', 'class': 'btn btn-default btn-sm softhide collapse-button'})
                .append($('<span></span>', {'class': 'fas fa-caret-up'}));
            
            $more_row.click(function(){
                $crows.show();
                $hide_button.show();
                $(this).hide();
            });
            
            $hide_button.click(function(){
                $crows.hide();
                $more_row.show();
                $(this).hide();
            });
            
            $rows.last().append($hide_button);
            $element.prepend($more_row);
        });
        return this;
    };
})(jQuery);
