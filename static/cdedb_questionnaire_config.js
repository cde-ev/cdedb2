/**
 * Some javascript enhancements, specially designed for the event/questionnaire_summary page.
 * Some dynamic hiding of elements, additionally to the dynamicRow script.
 */
(function($){
    /**
     * jQuery plugin to be used on each single row in questionnaire_summary formular. It adds an event listener to the
     * field_id input and calls it to hide/show some labels.
     */
    $.fn.cdedbQuestionnaireConfig = function(field_list) {
        $(this).each(function(){
            var $container = $(this);
            var $input_size = $(this).find('.input-inputsize').closest('.form-group');
            var $input_readonly = $(this).find('.input-readonly').closest('.checkbox');

            var handler = function() {
                var val = $(this).val();
                if (val == '') {
                    $input_size.hide();
                    $input_readonly.hide();
                    $container.addClass('shaded-info');
                } else {
                    $input_readonly.show();
                    if (field_list[val] && (field_list[val]['kind'] != 'str' || field_list[val]['entries'])) {
                        $input_size.hide();
                    } else {
                        $input_size.show();
                    }
                    $container.removeClass('shaded-info');
                }
            };

            var $input_field = $(this).find('.input-field').change(handler);
            $input_field.trigger('change');
        });

        return this;
    }
})(jQuery)
