/**
 * Some javascript enhancements, specially designed for the event/questionnaire_summary page.
 * Some dynamic hiding of elements, additionally to the dynamicRow script.
 */
/** Enum of possible types of custom DataFields. Reflects cdedb.database.constants.FieldDatatypes */
FieldDatatypes = {
    "str": 1,
    "bool": 2,
    "int": 3,
    "float": 4,
    "date": 5,
    "datetime": 6
};
/** Mapping of CdEDB datafield types to HTML input types */
var inputTypes = {
    1 : 'text',
    3 : 'number',
    4 : 'text',
    5 : 'date',
    6 : 'datetime-local'};

(function($){
    /**
     * Helper function for replacing the 'default_value' input field with one of the correct input type; to be used by
     * cdedbQuestionnaireConfig's event callbacks for the field-input and the size-input.
     *
     * @param field_spec The specification of the relevant data field (entry from the `field_list` json object)
     * @param $input_defaultvalue jQuery object of the current default_value input
     * @param translations An object of translation strings
     * @param size Current value of the size-input to adapt the defaultvalue input's to the size of the input in
     *      questionnaire for string-fields.
     */
    function replace_defaultvalue_input(field_spec, $input_defaultvalue, translations, size) {
        var num_entries = Object.keys(field_spec['entries'] || {}).length;
        var field_type = field_spec['kind'];

        // Store the original default value to be able to reapply it.
        let $input_group_defaultvalue = $input_defaultvalue.closest('.form-group');
        if ($input_group_defaultvalue.data('orig_defaultvalue') === undefined) {
            $input_group_defaultvalue.data('orig_defaultvalue', $input_defaultvalue.val());
        }
        let defaultvalue = $input_group_defaultvalue.data('orig_defaultvalue');

        // Replace the default value input if the field type changed or either the current or the new field has entries.
        if (
            parseInt($input_defaultvalue.data('field_type')) !== field_type
            || parseInt($input_defaultvalue.data('num_entries'))
            || num_entries
        ) {
            // Create new input field for data type of selected data field
            if (field_type === FieldDatatypes.bool || num_entries) {
                $i = $('<select>', {
                    'class': "form-control input-defaultvalue drow-input",
                    'id': $input_defaultvalue.attr('id'),
                    'name': $input_defaultvalue.attr('name')
                });

                $i.append($('<option>', {'value': ''}));
                if (num_entries) {
                    for (var key in field_spec['entries']) {
                        $i.append($('<option>', {'value': key}).text(field_spec['entries'][key]));
                    }
                } else {
                    $i.append($('<option>', {'value': 'True'}).text(translations['true'] || 'true'))
                        .append($('<option>', {'value': 'False'}).text(translations['false'] || 'false'));
                }

                $i.val(defaultvalue);

            // For string type fields, we use a textarea (to allow entering line breaks w/o copy&paste)
            } else {
                $i = $(field_type === FieldDatatypes.str && size > 0 ? '<textarea>' : '<input>', {
                    'class': "form-control input-defaultvalue drow-input",
                    'id': $input_defaultvalue.attr('id'),
                    'name': $input_defaultvalue.attr('name'),
                    'type': inputTypes[field_type]
                })
                    .val(defaultvalue);

                if (field_type === FieldDatatypes.date)
                    $i.attr('placeholder', 'YYYY-MM-DD');
                else if (field_type === FieldDatatypes.datetime)
                    $i.attr('placeholder', 'YYYY-MM-DDThh:mm:ss')
                        .val(defaultvalue.split("+", 1)[0]);
            }

            $i.data('field_type', field_type)
                .data('num_entries', num_entries);
            $input_defaultvalue.replaceWith($i);
        }
    }

    /**
     * jQuery plugin to be used on each single row in questionnaire_summary formular. It adds an event listener to the
     * field_id input and calls it to hide/show some labels.
     */
    $.fn.cdedbQuestionnaireConfig = function(field_list, translations) {
        $(this).each(function(){
            var $container = $(this);
            var $input_field = $(this).find('.input-field');
            var $input_group_readonly = $(this).find('.input-readonly').closest('.checkbox');
            var $input_group_defaultvalue = $(this).find('.input-defaultvalue').closest('.form-group');
            var $input_helpblock_info = $(this).find('.input-info').closest('.form-group').find('.help-block');

            /* Callback handler to be executed when the data field of this questionnaire part is triggered */
            var input_field_handler = function() {
                var val = $(this).val();
                /* Text-only questionnaire part */
                if (val === '') {
                    $input_group_readonly.hide();
                    $input_group_defaultvalue.hide();
                    $input_helpblock_info.show();
                    $container.addClass('shaded-info');

                /* Questionnaire part with input field */
                } else {
                    $input_group_readonly.show();
                    $input_group_defaultvalue.show();
                    $input_helpblock_info.hide();
                    $container.removeClass('shaded-info');

                    // Change default_value input field's type and attributes according to selected field's type
                    var field_spec = field_list[val];
                    if (field_spec) {
                        var $input_defaultvalue = $container.find('.input-defaultvalue');
                        replace_defaultvalue_input(field_spec, $input_defaultvalue, translations);
                    }
                }
            };

            /* Call input_field_handler() on change of field-input and once for intialization */
            $input_field.on("change", input_field_handler);
            $input_field.trigger("change");
        });

        return this;
    }
})(jQuery);
