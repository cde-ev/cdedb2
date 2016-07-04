(function($) {
    /**
     * Simple jQuery plugin to hide unimportant things and unhide them on button click.
     * 
     * Searches elements with class 'unimportant' inside the given element and hides them. A click on the given button
     * unhides them. The button will be 'shown' onload, in case it was hidden by css rules.
     */
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
    
    /**
     * jQuery plugin to prevent users from accidentally leave forms without saving.
     */
    $.fn.cdedbProtectChanges = function(message) {
        // Message seems to be ignored in most current browsers
        message = message || "Wenn Du die Seite verlässt, gehen Deine ungespeicherten Änderungen verloren.";
        $forms = $(this);
        
        // For each form
        $forms.each(function() {
            $form = $(this);
            // Store current state
            $form.data('serialize',$(this).serialize());
             
            // Add submit and abort handlers to suppress unwanted confirms
            $form.submit(function() {
                $(this).data('clean_exit', true);
            });
            $form.find('.cancel').click(function() {
                $form.data('clean_exit', true);
            });
        });
        
        // BeforeUnload event handler
        // From http://stackoverflow.com/a/155812
        window.onbeforeunload = function(e) {
            var changed = false;
            $forms.each(function(){
                changed = $(this).serialize() != $(this).data('serialize') && !$(this).data('clean_exit');
                return !changed;
            });
            if (changed) {
                e = e || window.event;
                if (e) e.returnValue = message;
                return message;
            }
        };
    };
    
    /**
     * jQuery plugin to prevent users from accidentally doing irreversible actions.
     */
    $.fn.cdedbProtectAction = function(message, is_safe_callback) {
        message = message || "Diese Aktion kann nicht rückgängig gemacht werden.";
        is_safe_callback = is_safe_callback || function(){ return false; };
        
        // Submit handler
        $(this).submit(function() {
            return ((is_safe_callback.bind(this))() || confirm(message));
        });
    };
})(jQuery);
