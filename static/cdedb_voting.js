/**
 * Simple jQuery plugin to disable checkboxes of a classic voting form with multiple votes.
 */
(function($) {
    $.fn.cdedbMultiVote = function(num_votes, bar) {
        var $checkboxes = $(this).find('input[name="vote"]');
        var $barbox = $checkboxes.filter('[value="'+ bar +'"]');

        $checkboxes.change(function() {
            var num_selected = $checkboxes.filter(':checked').length;
            // Disable all unchecked boxes if barbox was checked or maximum number of votes reached
            if (($barbox && $barbox.prop('checked')) || num_selected >= num_votes)
                $checkboxes.each(function(){
                    if (!this.checked)
                        this.disabled = true;
                });
            else
                $checkboxes.prop('disabled',false);
            
            // Disable barbox additionally if any other was selected
            if (num_selected > 0 && $barbox && !$barbox.prop('checked'))
                $barbox.prop('disabled', true);
        });

        return this;
    };
})(jQuery);
