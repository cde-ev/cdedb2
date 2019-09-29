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
     * cdedbQuestionnaireConfig's event callback.
     *
     * @param field_spec The specification of the new relevant data field (entry from the `field_list` json object)
     * @param $input_defaultvalue jQuery object of the current default_value input
     * @param translations An object of translation strings
     */
    function replace_defaultvalue_input(field_spec, $input_defaultvalue, translations) {
        var has_entries = field_spec['entries'] !== null;
        var field_type = field_spec['kind'];

        if (parseInt($input_defaultvalue.attr('data-type')) !== field_type
            || Boolean($input_defaultvalue.attr('data-entries')) !== has_entries) {
            // Create new input field for data type of selected data field
            if (field_type === FieldDatatypes.bool || has_entries) {
                var $i = $('<select>', {
                    'class': "form-control input-defaultvalue drow-input",
                    'id': $input_defaultvalue.attr('id'),
                    'name': $input_defaultvalue.attr('name')
                });

                $i.append($('<option>', {'value': ''}));
                if (has_entries) {
                    for (var i = 0; i < field_spec['entries'].length; i++)
                        $i.append($('<option>', {'value': field_spec['entries'][i][0]}).text(field_spec['entries'][i][1]))
                } else {
                    $i.append($('<option>', {'value': 'True'}).text(translations['true'] || 'true'))
                        .append($('<option>', {'value': 'False'}).text(translations['false'] || 'false'));
                }

                $i.val($input_defaultvalue.val());

            // For string type fields, we use a textarea (to allow entering line breaks w/o copy&paste)
            } else if (field_type === FieldDatatypes.str) {
                $i = $('<textarea>', {
                    'class': "form-control input-defaultvalue drow-input",
                    'name': $input_defaultvalue.attr('name'),
                    'rows': 2
                });
            } else {
                $i = $('<input>', {
                    'class': "form-control input-defaultvalue drow-input",
                    'name': $input_defaultvalue.attr('name'),
                    'type': inputTypes[field_type]
                })
                    .val($input_defaultvalue.val());

                if (field_type === FieldDatatypes.date)
                    $i.attr('placeholder', 'YYYY-MM-DD');
                else if (field_type === FieldDatatypes.datetime)
                    $i.attr('placeholder', 'YYYY-MM-DDThh:mm');
            }

            $i.attr('data-type', field_type)
                .attr('data-entries', has_entries);
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
            var $input_group_size = $(this).find('.input-inputsize').closest('.form-group');
            var $input_group_readonly = $(this).find('.input-readonly').closest('.checkbox');
            var $input_group_defaultvalue = $(this).find('.input-defaultvalue').closest('.form-group');
            var $input_helpblock = $(this).find('.input-info').closest('.form-group').find('.help-block');

            /* Callback handler to be executed when the data field of this questionnaire part is triggered */
            var input_field_handler = function() {
                var val = $(this).val();
                /* Text-only questionnaire part */
                if (val === '') {
                    $input_group_size.hide();
                    $input_group_readonly.hide();
                    $input_group_defaultvalue.hide();
                    $input_helpblock.show();
                    $container.addClass('shaded-info');

                /* Questionnaire part with input field */
                } else {
                    $input_group_readonly.show();
                    $input_group_defaultvalue.show();
                    $input_helpblock.hide();
                    $container.removeClass('shaded-info');

                    // Show input_size field only for string fields without entries
                    if (field_list[val] &&
                           (field_list[val]['kind'] !== FieldDatatypes.str || field_list[val]['entries'])) {
                        $input_group_size.hide();
                    } else {
                        $input_group_size.show();
                    }

                    // Change default_value input field's type and attributes according to selected field's type
                    var field_spec = field_list[val];
                    if (field_spec) {
                        var $input_defaultvalue = $container.find('.input-defaultvalue');
                        replace_defaultvalue_input(field_spec, $input_defaultvalue, translations);
                    }
                }
            };

            var $input_field = $(this).find('.input-field').change(input_field_handler);
            $input_field.trigger('change');
        });

        return this;
    }
})(jQuery);
