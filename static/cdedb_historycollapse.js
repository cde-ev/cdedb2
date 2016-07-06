/**
 * Simple jQuery plugin for collapsable lists for profile history.
 */
(function($) {
    $.fn.cdedbHistoryCollapse = function() {
        $(this).each(function() {
            var $element = $(this);
            var $rows = $element.find('.history-row:not(.pending)');
            var $crows = $rows.slice(0, -1);
            
            if ($rows.length < 2)
                return;
            
            $crows.addClass('collapse').hide();
            
            var $more_row = $('<div></div>', {'class': 'row history-row more', 'tab-index': '0'})
                .text('– ' + String($rows.length - 1) + ' weitere Version' + ($rows.length > 2 ? 'en' : '') + ' –');
            
            var $hide_button = $('<button></button>',
                    {'type': 'button', 'class': 'btn btn-default btn-sm softhide collapse-button'})
                .append($('<span></span>', {'class': 'glyphicon glyphicon-triangle-top'}));
            
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
