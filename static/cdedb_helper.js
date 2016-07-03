/**
 * Simple jQuery plugin to hide unimportant things and unhide them on button click.
 * 
 * Searches elements with class 'unimportant' inside the given element and hides them. A click on the given button
 * unhides them. The button will be 'shown' onload, in case it was hidden by css rules.
 */
(function($) {
    $.fn.cdedbHideUnimportant = function($button) {
        $elements = $(this).find('.unimportant');
        $elements.hide();
        $button
            .click(function() {
                $elements.show();
                $(this).hide();
            })
            .show();
    };
})(jQuery);
