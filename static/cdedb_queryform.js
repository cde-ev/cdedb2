/**
 * Extended javascript functionality for query forms in the cdedb2.
 * The jQuery method defined at the end of this file should be applied to the query form dom object onload.
 */
(function($) {
    /**
     * Create QueryForm object upon a given HTML DOM elemnt
     * @param element (DOM object) The DOM object of the query form container
     * @param options (object) A dict of options passed by the appliction. Should contain:
     *                         choices: An object mapping fields to a list of chosable values for this field
     *                         seperator: The seperator character/string to seperate multiple values
     *                         escapechar: The escape character to escape the seperator if present within a value
     *                         labels: An object of translated labels to be used as button captions and titles
     * @constructor
     */
    var QueryForm = function(element,options) {
        /** jQuery DOM object of the form */
        var $element = $(element);
        var obj = this;
        var settings = $.extend({
            choices : {},  // Format: {field_name: [[value, title]]}
            separator : ',',
            escapechar : '\\\\', //double escaped backslash for usage in regex
            labels : {}
        }, options || {});
        /**
         * List of all data fields listed in the query form. Each element has the following attributes:
         * id: database id of this field (string),
         * type: data type (string: bool, int, string, list, date, datetime, float)
         * name: human readable name of the field
         * choices: List of choices if type==list. Each choice has the format {'value': v, 'text': t}, which is the
         *          format required by selectize.js for options.
         * sortable: Can this field be used for sorting? (bool)
         * input_select: jQuery DOM object of the non-js field select checkbox
         * input_filter_op: jQuery DOM object of the non-js filter operator select box
         * input_filter: jQuery DOM object of the non-js filter value field
         * error: Validation error message in case of validation error for this field (html string)
         */
        var fieldList = [];
        /**
         * List of the sort/ordering selects. Each element has the following attributes:
         * input_field: jQuery DOM object of the field select box for this order
         * input_order: jQuery DOM object of the order (asc/desc) select box
         */
        var sortInputs = [];
        /**
         * Index of the id field in the fieldList. This field is used by the setIdFilter() function.
         * -1 if no filterable field is known to be the id field.
         */
        var idField = -1;

        /** The jQueryDOM object of the .addviewfield select box (and not it's selectize container) */
        var $viewFieldSelect = $element.find('.addviewfield');
        /** The jQueryDOM object of the .addsortfield select box (and not it's selectize container) */
        var $sortFieldSelect = $element.find('.addsortfield');
        /** The jQueryDOM object of the .addfilter select box (and not it's selectize container) */
        var $filterFieldSelect = $element.find('.addfilter');
        /** The jQueryDOM object of the container for filter rows */
        var $filterFieldList = $element.find('.filterfield-list');
        /** The jQueryDOM object of the container for view field entries */
        var $viewFieldList = $element.find('.viewfield-list');
        /** The jQueryDOM object of the container for sort rows */
        var $sortFieldList = $element.find('.sortfield-list');

        /* Scan form rows and initialize field list */
        $element.find('.query_field').each(function() {
            var id = $(this).attr('data-id');
            var input_select = $(this).find('.outputSelector');
            var error_block = $(this).find('.help-block');

            /* Reformat list of choices from [[v, t]] to [{'value': v, 'text': t}] */
            var choices = [];
            if (settings.choices[id]) {
                for (var i=0; i < settings.choices[id].length; i++) {
                    choices.push({'value': settings.choices[id][i][0], 'text': settings.choices[id][i][1]})
                }
            }

            fieldList.push({
                id: id,
                type: settings.choices[id] ? 'list' : $(this).attr('data-type'),
                name: $(this).find('.name').text(),
                choices: choices,
                sortable : false,
                input_select: input_select.length ? input_select : null,
                input_filter_op: $(this).find('.filter-op'),
                input_filter_value: $(this).find('.filter-value'),
                error: error_block.length ? error_block.html() : null
            });

            if ($(this).hasClass('id-field'))
                idField = fieldList.length - 1;
        });

        /* Find form sort fields */
        $element.find('.query_sort').each(function() {
            sortInputs.push({
                input_field : $(this).find('.sort-field'),
                input_order : $(this).find('.sort-order')
            });
        });

        /* Scan sort field options and mark sortable fields */
        sortInputs[0].input_field.children('option').each(function() {
            for (var i = 0; i < fieldList.length; i++) {
                if (fieldList[i].id == $(this).attr('value')) {
                    fieldList[i].sortable = true;
                    break;
                }
            }
        });

        /* Member functions */
        /**
         * Initialize add*field select boxes.
         *
         * Enables Event handlers and selectize.js for add*field select boxes and uses the refresh*() functions to add
         * available options.
         */
        this.initFieldSelects = function() {
            /* Add event handler, and selectize.js for add*field select boxes */
            /* No refreshs/filling with options for now, as they are done later by init() */
            $viewFieldSelect.change(function() {
                if ($(this).val() === '')
                    return;
                obj.addViewRow($(this).val());
                obj.refreshViewFieldSelect();
                $viewFieldSelect[0].selectize.focus();
            });
            $viewFieldSelect.selectize({
                'placeholder': settings.labels['add_field'] || '',
                copyClassesToDropdown: false
            });

            $filterFieldSelect.change(function() {
                if ($(this).val() === '')
                    return;
                obj.addFilterRow($(this).val(), true);
                obj.refreshFilterFieldSelect();
            });
            $filterFieldSelect.selectize({
                'placeholder': settings.labels['add_filter'] || '',
                copyClassesToDropdown: false
            });

            $sortFieldSelect.change(function() {
                if ($(this).val() === '')
                    return;
                obj.addSortRow($(this).val(),'True');
                obj.updateSortInputs();
                obj.refreshSortFieldSelect();
            });
            $sortFieldSelect.selectize({
                'placeholder': settings.labels['add_sort'] || '',
                copyClassesToDropdown: false
            });

            this.refreshViewFieldSelect();
            this.refreshFilterFieldSelect();
            this.refreshSortFieldSelect();
        };

        /**
         * Add a filter row to the dynamic formular. The filter field is specified by the entry id in the field list
         * array.
         *
         * @param number (int) Id of the field in fieldList
         * @param focus (bool) If true, the operator select box will get keyboard focus
         */
        this.addFilterRow = function(number, focus) {
            var f = fieldList[number];

            var $button = $('<button></button>', {
                'class':"btn btn-sm btn-danger pull-right",
                'type':"button",
                'title': settings.labels['del_filter'] || ''
            })
                .append($('<span></span>',{'class':'fas fa-minus'}))
                .click(function() {
                    f.input_filter_op.val('');
                    f.input_filter_value.val('');
                    $(this).parent().detach();
                    obj.refreshFilterFieldSelect();
                });
            var $fieldbox = $('<span></span>');
            var $opselector = $('<select></select>', {
                'class':"form-control input-sm input-slim",
                'aria-label': settings.labels['filter_op'] || ''
            })
                .append(f.input_filter_op.children('option').slice(1).clone())
                .change(function() {
                    f.input_filter_op.val($(this).val());
                    f.error = null;
                    $(this).siblings('.help-block').detach();
                    $(this).parent().removeClass('has-error');
                    obj.updateFilterValueInput(number,$(this).val(),$fieldbox);
                });
            // Initially sync operator select
            if (f.input_filter_op.val() !== '')
                $opselector.val(f.input_filter_op.val());
            else
                f.input_filter_op.val($opselector.val());


            var $item = $('<li></li>',{
                'class':"list-group-item queryform-filterbox" + (f.error ? " has-error": ""),
                'data-id': number
            })
                .append(f.name).append('&ensp;')
                .append($opselector).append('&ensp;')
                .append($fieldbox)
                .append($button);
            if (f.error)
                $item.append($('<div></div>',{'class':'help-block'}).html(f.error));

            $filterFieldList.append($item);
            if (focus) {
                $opselector.focus();
            }

            this.updateFilterValueInput(number, $opselector.val(), $fieldbox)
        };

        /**
         * Generate the filter value inputs according to the selected filter operator.
         *
         * @param fieldNumber (int) Id of the field in fieldList
         * @param operator (int) selected filter operator
         * @param $fieldbox (jQuery DOM object) DOM element to fill with the inputs.
         */
        this.updateFilterValueInput = function(fieldNumber, operator, $fieldbox) {
            $fieldbox.empty();
            var f = fieldList[fieldNumber];

            var inputTypes = {
                    'date' : 'date',
                    'datetime' : 'datetime-local',
                    'int' : 'number',
                    'id' : 'number',
                    'str' : 'text',
                    'float' : 'text'};

            switch (parseInt(operator)) {
            // The constants arise from cdedb.query.QueryOperators.
            case 1: //emtpy
            case 2: //nonempty
                break;

            case 3: //equal
            case 4: //unequal
            case 7: //equalornull
            case 8: //unequalornull
            case 10: //match
            case 11: //unmatch
            case 12: //regex
            case 13: //notregex
            case 17: //fuzzy
            case 20: //less
            case 21: //lessequal
            case 24: //greaterequal
            case 25: //equal
                var changeFunction = function() {
                    f.input_filter_value.val($(this).val());
                    f.error = null;
                    $fieldbox.siblings('.input-error-block').detach();
                };

                if (f.type == 'bool' || f.type == 'list') {
                    var $s = $('<select>',{
                        'class' : "form-control input-sm input-slim",
                        'aria-label': settings.labels['filter_val'] || ''
                    })
                            .change(changeFunction);
                    if (f.type == 'list') {
                        for (var i=0; i < f.choices.length; i++)
                            $s.append($('<option>',{'value' : f.choices[i]['value']}).text(f.choices[i]['text']))
                    } else {
                        $s.append($('<option>',{'value' : 'True'}).text(settings.labels['true'] || 'true'))
                            .append($('<option>',{'value' : 'False'}).text(settings.labels['false'] || 'false'));
                    }

                    if (f.input_filter_value.val() !== '')
                        $s.val(f.input_filter_value.val());
                    else
                        f.input_filter_value.val($s.val());
                    $s.appendTo($fieldbox);

                    if (f.type == 'list')
                        $s.selectize();
                } else {
                    $i = $('<input>',{
                        'class': "form-control input-sm input-slim",
                        'type': inputTypes[f.type],
                        'aria-label': settings.labels['filter_val'] || ''
                    })
                        .change(changeFunction)
                        .val(f.input_filter_value.val());
                    if (f.type == 'date')
                        $i.attr('placeholder','YYYY-MM-DD');
                    else if (f.type == 'datetime')
                        $i.attr('placeholder','YYYY-MM-DDThh:mm');
                    $i.appendTo($fieldbox);
                }
                break;

            case 22: //between
            case 23: //outside
                var escape = function(v) {
                    return v.replace(settings.escapechar,settings.escapechar+settings.escapechar)
                            .replace(settings.separator,settings.escapechar+settings.separator);
                };
                var unescape = function(v) {
                    return v.replace(settings.escapechar+settings.separator,settings.separator)
                            .replace(settings.escapechar+settings.escapechar,settings.escapechar);
                };

                //Split value at separator but not at escapechar+separator
                var values = f.input_filter_value.val()
                        .match(new RegExp('('+settings.escapechar+'.|[^'+settings.separator+'])+','g'));
                if (values && values.length > 1)
                    values = values.map(unescape);
                else
                    values=["",""];

                var $i1 = $('<input>',{
                    'class' : "form-control input-sm input-slim",
                    'type': 'text',
                    'aria-label': settings.labels['filter_range_start'] || ''
                })
                    .val(values[0]);
                var $i2 = $('<input>',{
                    'class' : "form-control input-sm input-slim",
                    'type': 'text',
                    'aria-label': settings.labels['filter_range_end'] || ''
                })
                    .val(values[1]);

                var $inputs = $i1.add($i2);
                $inputs.attr('type', inputTypes[f.type])
                if (f.type == 'date')
                    $inputs.attr('placeholder','YYYY-MM-DD');
                else if (f.type == 'datetime')
                    $inputs.attr('placeholder','YYYY-MM-DDThh:mm');
                $inputs.change(function() {
                    var val = escape($i1.val()) + ',' + escape($i2.val());
                    f.input_filter_value.val(val);
                });

                $fieldbox.append($i1).append(settings.labels['filter_range_through'] || '').append($i2);

                break;
            case 5: //oneof
            case 6: //otherthan
            case 14: //containsall
            case 15: //containsnone
            case 16: //containssome
                var placeholders = {
                    'date' : 'YYYY-MM-DD,YYYY-MM-DD,…',
                    'datetime' : 'YYYY-MM-DDThh:mm,YYYY-MM-DDThh:mm,…',
                    'int' : settings.labels['range_values'],
                    'id' : settings.labels['range_ids'],
                    'list' : settings.labels['range_ids'],
                    'str' : settings.labels['range_values'],
                    'float' : settings.labels['range_values']};

                var $i = $('<input>',{
                    'class' : "form-control input-sm input-slim",
                    'type': 'text',
                    'placeholder': placeholders[f.type],
                    'aria-label': settings.labels['filter_vals'] || ''
                })
                    .change(function() { f.input_filter_value.val($(this).val()); })
                    .attr('size','40')
                    .val(f.input_filter_value.val())
                    .appendTo($fieldbox);

                if (f.type == 'list') {
                    $i.attr('placeholder','');
                    $i.selectize({
                        options: f.choices
                    });
                }

                break;
            }
        };

        /**
         * Add a row to the dynamic view list. The new field is specified by the entry id in the field list array.
         *
         * @param number (int) Id of the field in fieldList
         */
        this.addViewRow = function(number) {
            var f = fieldList[number];
            if (f.input_select === null) {
                console.warn('Field '+f.id+' does not allow selection for view.');
                return;
            }

            // Tick hidden checkbox representing the actual state
            f.input_select.prop('checked',true);

            // Add box to the dynamic list
            var $button = $('<button></button>', {
                'class': "btn btn-xs btn-danger",
                'type': "button",
                'title': settings.labels['del_field'] || ''
            })
                .append($('<span></span>',{'class':'fas fa-minus'}))
                .click(function() {
                    f.input_select.prop('checked',false);
                    $(this).parent().detach();
                    obj.refreshViewFieldSelect();
                });
            var $box = $('<span></span>',{'class':'queryform-fieldbox', 'data-id':number})
                    .text(f.name)
                    .append($button);

            $viewFieldList.append($box);
        };

        /**
         * Add a row to the list of sort fields of the dynamic formular.
         *
         * @param number (int) Id of the field in fieldList
         * @param sorting (string) predefined value of the order (asc/desc) select box
         */
        this.addSortRow = function(number, sorting) {
            var f = fieldList[number];

            var inputTypes = {
                    'bool' : ['✘→✔','✔→✘'],
                    'date' : ['0→9','9→0'],
                    'datetime' : ['0→9','9→0'],
                    'int' : ['0→9','9→0'],
                    'id' : ['0→9','9→0'],
                    'str' : ['A→Z','Z→A'],
                    'list' : ['A→Z','Z→A'],
                    'float' : ['0→9','9→0']};

            var $button = $('<button></button>', {
                'class': "btn btn-sm btn-danger pull-right",
                'type': "button",
                'title': settings.labels['del_sort'] || ''
            })
                .append($('<span></span>',{'class':'fas fa-minus'}))
                .click(function() {
                    $(this).parent().detach();
                    obj.updateSortInputs();
                    obj.refreshSortFieldSelect();
                });
            var $sortselector = $('<select></select>', {
                'class': "form-control input-sm input-slim order",
                'aria-label': settings.labels['sort_order'] || ''
            })
                .append(new Option(inputTypes[f.type][0],'True'))
                .append(new Option(inputTypes[f.type][1],'False'))
                .val(sorting)
                .change(function() {
                    obj.updateSortInputs();
                });
            var $item = $('<li></li>',{'class':"list-group-item queryform-filterbox",'data-id':number})
                    .append($('<span></span>',{'class':'num label label-default'})).append('&ensp;')
                    .append(f.name).append('&ensp;')
                    .append($sortselector).append('&ensp;')
                    .append($button);

            $sortFieldList.append($item);
        };


        /**
         * Refresh the list of options in the .addfilter select box.
         */
        this.refreshFilterFieldSelect = function() {
            // Check currently listed fields
            var currentFields = new Array(fieldList.length);
            $element.find('.filterfield-list .queryform-filterbox').each(function() {
                currentFields[$(this).attr('data-id')] = true;
            });

            // Add not listed fields to selectize.js-selectbox
            options = [];
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                if (!currentFields[i]) {
                    options.push({value: i, text: f.name});
                }
            }
            var selectize = $filterFieldSelect[0].selectize;
            selectize.setValue('');
            selectize.clearOptions();
            selectize.addOption(options);
        };

        /**
         * Refresh the list of options in the .addviewfield select box.
         */
        this.refreshViewFieldSelect = function() {
            // Check currently listed fields
            var currentFields = new Array(fieldList.length);
            $element.find('.viewfield-list .queryform-fieldbox').each(function() {
                currentFields[$(this).attr('data-id')] = true;
            });

            // Add all valid and not listed fields to selectize.js-selectbox
            options = [];
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                if (f.input_select !== null && !currentFields[i]) {
                    options.push({value: i, text: f.name});
                }
            }
            var selectize = $viewFieldSelect[0].selectize;
            selectize.setValue('');
            selectize.clearOptions();
            selectize.addOption(options);
        };

        /**
         * Refresh the list of options in the .addsortfield select box.
         */
        this.refreshSortFieldSelect = function() {
            // Check currently listed fields
            var currentFields = new Array(fieldList.length);
            var numSortFields = 0;
            $element.find('.sortfield-list .queryform-filterbox').each(function () {
                currentFields[$(this).attr('data-id')] = true;
                numSortFields++;
            });

            // Check if maximum number of sortfields is reached
            if (numSortFields >= sortInputs.length) {
                $sortFieldSelect.parent().css('display', 'none');
                return;
            } else {
                $sortFieldSelect.parent().css('display', '');
            }

            // Add all valid and not listed fields to selectize.js-selectbox
            options = [];
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                if (f.sortable && !currentFields[i]) {
                    options.push({value: i, text: f.name});
                }
            }
            var selectize = $sortFieldSelect[0].selectize;
            selectize.setValue('');
            selectize.clearOptions();
            selectize.addOption(options);
        };

        /**
         * Write back the sort selection and ordering into the input fields of the non-js form.
         * Also updates the displayed numbers in the dynamic sort list.
         */
        this.updateSortInputs = function() {
            var i=0;
            $element.find('.sortfield-list .queryform-filterbox').each(function() {
                $(this).children('.num').text(i+1);
                sortInputs[i].input_field.val(fieldList[$(this).attr('data-id')].id);
                sortInputs[i].input_order.val($(this).children('.order').val());
                i++;
            });
            for (;i<sortInputs.length;i++) {
                sortInputs[i].input_field.val('');
            }
        };

        /**
         * Public API: Remove all filters
         */
        this.clearFilters = function() {
            for (var i = 0; i < fieldList.length; i++) {
                f = fieldList[i];
                f.input_filter_op.val('');
                f.input_filter_value.val('');
            }
            $element.find('.filterfield-list').children().detach();
            obj.refreshFilterFieldSelect();
        };

        /**
         * Public API: Remove all view fields
         */
        this.clearViewFields = function() {
            for (var i = 0; i < fieldList.length; i++) {
                f = fieldList[i];
                if (f.input_select)
                    f.input_select.prop('checked',false);
            }
            $element.find('.viewfield-list').children().detach();
            obj.refreshViewFieldSelect();
        };

        /**
         * Public API: Remove all sort fields
         */
        this.clearSortFields = function () {
            $element.find('.sortfield-list').children().detach();
            obj.updateSortInputs();
            obj.refreshSortFieldSelect();
        };

        /**
         * Public API: Remove all filters and add an 'one of filter' for the id field (if an id field is existent)
         *
         * @param ids Array of ids to be searched
         */
        this.setIdFilter = function(ids) {
            if (idField == -1)
                return;

            this.clearFilters();

            var f = fieldList[idField];
            // Set filter operator in nonjs-form to 'one of'
            f.input_filter_op.val(5);
            // Set filter value in nonjs-form to id list
            f.input_filter_value.val(ids.join(settings.separator));
            // Add filter rot to js-form
            this.addFilterRow(idField, false)
        };

        /**
         * Public API: Reset fancy js query form from the current state of the non-js query form
         *
         * This method is automatically called, when initializing this QueryForm object with .init(). It can be called
         * afterwards, if manual changes to the non-js form are expected.
         */
        this.initFromForm = function() {
            // Clear formular
            $filterFieldList.children().detach();
            $viewFieldList.children().detach();
            $sortFieldList.children().detach();

            // Add currently selected and filtered fields to dynamic lists
            for (var i = 0; i < fieldList.length; i++) {
                var f = fieldList[i];

                if (f.input_filter_op.val() !== '')
                    this.addFilterRow(i, false);

                if (f.input_select && f.input_select.prop('checked'))
                    this.addViewRow(i);
            }
            // Add current sort fields
            for (var i = 0; i < sortInputs.length; i++) {
                if (sortInputs[i].input_field.val() !== '') {
                    //Search field in fieldList
                    var field = -1;
                    for (var j = 0; j < fieldList.length; j++) {
                        if (fieldList[j].id == sortInputs[i].input_field.val()) {
                            field = j;
                            break;
                        }
                    }
                    if (field == -1)
                        continue;

                    // Add field to sort list
                    this.addSortRow(field, sortInputs[i].input_order.val());
                }
            }

            this.refreshViewFieldSelect();
            this.refreshFilterFieldSelect();
            this.updateSortInputs();
            this.refreshSortFieldSelect();
        };

        /**
         * Public API: Reset query form to parameters from query url.
         * @param url The query url to read query parameters from. The GET-parameter string is sufficient; anything
         *            before the first question mark will be stripped.
         */
        this.queryFromURL = function(url) {
            // First get the parameters in an indexed object
            var parts = url.split('?');
            parts = parts[parts.length-1].split('#');
            parts = parts[0].split('&');
            var parameters = {};
            for (var i = 0; i < parts.length; i++) {
                var s = parts[i].split('=');
                parameters[decodeURIComponent(s[0])] = decodeURIComponent(s[1]);
            }

            // Now clear formular
            this.clearFilters();
            this.clearViewFields();
            this.clearSortFields();

            // Scan for filters and view fields
            for (var i = 0; i < fieldList.length; i++) {
                var f = fieldList[i];
                if (parameters[f.input_filter_op.attr('name')]) {
                    f.input_filter_op.val(parameters[f.input_filter_op.attr('name')]);
                    f.input_filter_value.val(decodeURIComponent(parameters[f.input_filter_value.attr('name')]));
                    this.addFilterRow(i, false);
                }
                if (f.input_select && parameters[f.input_select.attr('name')] == 'True') {
                    f.input_select.prop('checked',true);
                    this.addViewRow(i);
                }
            }
            this.refreshViewFieldSelect();
            this.refreshFilterFieldSelect();
            // Scan for sort fields
            for (var i = 0; i < sortInputs.length; i++) {
                if (parameters[sortInputs[i].input_field.attr('name')]) {
                    sortInputs[i].input_field.val(parameters[sortInputs[i].input_field.attr('name')]);
                    var order_value = parameters[sortInputs[i].input_order.attr('name')];
                    sortInputs[i].input_order.val(order_value);
                    //Search field in fieldList
                    var field = -1;
                    for (var j = 0; j < fieldList.length; j++) {
                        if (fieldList[j].id == sortInputs[i].input_field.val()) {
                            field = j;
                            break;
                        }
                    }
                    if (field == -1)
                        continue;
                    // Add field to sort list
                    this.addSortRow(field, order_value);
                }
            }
            this.updateSortInputs();
            this.refreshSortFieldSelect();
        }
    };


    /**
     * The actual "jQuery plugin" - a function to be used on the jQuery object of the query form.
     * It constructs and initializes the above defined object which does everything neccessary for the fancy js form.
     * It also attaches a special submit-handler to the query form to shorten query URLs.
     *
     * @param options: Object of options to be passed to the QueryForm object
     */
    $.fn.cdedbQueryForm = function(options) {
        $(this).each(function() {
            if ($(this).data('cdedbQueryForm'))
                return;

            var obj = new QueryForm(this,options);
            $(this).data('cdedbQueryForm',obj);

            // Custom submit handler
            // Inspired by http://stackoverflow.com/a/5169572 and http://www.billerickson.net/code/hide-empty-fields-get-form/
            $(this).submit(function(e) {
                //Prevent default handler
                e.preventDefault();
                //Gather input fields that will be disabled in a jQuery object
                var toDisable = [];
                $(this).find('.query_field').each(function() {
                    var input_op = $(this).find('.filter-op');
                    if (input_op.val() === '') {
                        toDisable.push(input_op[0]);
                        toDisable.push($(this).find('.filter-value')[0]);
                    }
                });
                $(this).find('.query_sort').each(function() {
                    var input_field = $(this).find('.sort-field');
                    if (input_field.val() === '') {
                        toDisable.push(input_field[0]);
                        toDisable.push($(this).find('.sort-order')[0]);
                    }
                });

                // Disable them
                $(toDisable).attr("disabled", "disabled");

                // Now submit the form
                // Important: We're using the DOM object's handler to prevent calling our jQuery handler recursively
                this.submit();

                // And reenable fields after some milliseconds (in case user submitted CSV-Form or navigates back)
                var $form = $(this);
                setTimeout(function(){
                    $(toDisable).removeAttr("disabled");
                    $form.find('.submit-value').detach();
                },100);
            });
            var $form = $(this);
            $(this).find('button[type="submit"],input[type="submit"]').click(function() {
                // Add submit button value as a hidden input to pass it through the above submit handler
                if ($(this).attr('name')) {
                    $form.append($('<input />', {
                        'class': 'submit-value',
                        'type': 'hidden',
                        'name': $(this).attr('name'),
                        'value': $(this).attr('value')
                    }));
                }
                // Because we don't actually submit the button, we have to transfer the
                // formaction and formmethod attributes to the form, if they are set.
                if ($(this).attr('formaction')) {
                    $form.attr('action', $(this).attr('formaction'));
                }
                if ($(this).attr('formmethod')) {
                    $form.attr('method', $(this).attr('formmethod'));
                }
            });

            obj.initFieldSelects();
        });
        return this;
    };

    /**
     * jQuery plugin to move results list into wide content container.
     *
     * This plugin must be applied on the box containing the result list. The 'triggers' parameters should contain all
     * buttons triggering the change. A click on one of these buttons will move the contents of the containing box into
     * a special wide container underneath the #maincontainer and add class 'active' to the trigger buttons.
     * This plugin creates the wide container and applys event handlers to the trigger buttons.
     */
    $.fn.cdedbMoveToWidePage = function($triggers) {
        var $box = $(this);

        // Construct wide page container
        var $widecontainer = $('<div></div>',{'class': 'wide-content-page'});
        $widecontainer.css('display', 'none');
        $('#maincontainer').after($widecontainer);

        // Add event handlers
        $triggers.click(function() {
            if (!$(this).hasClass('active')) {
                $widecontainer.append($box.contents());
                $widecontainer.css('display', '');
                $triggers.addClass('active');
            } else {
                $box.append($widecontainer.contents());
                $widecontainer.css('display', 'none');
                $triggers.removeClass('active');
            }
        });

        return this;
    }
})(jQuery);
