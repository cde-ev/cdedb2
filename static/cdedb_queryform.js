/**
 * Extended javascript functionality for query forms in the cdedb2.
 * The jQuery method defined at the end of this file should be applied to the query form dom object onload.
 */
(function($) {
    var QueryForm = function(element,options) {
        /** jQuery DOM object of the form */
        var $element = $(element);
        var obj = this;
        var settings = $.extend({
            choices : {},            
            separator : ',',
            escapechar : '\\\\', //double escaped backslash for usage in regex
        }, options || {});
        /**
         * List of all data fields listed in the query form. Each element has the following attributes:
         * id: database id of this field (string),
         * type: data type (string: bool, int, string, list, date, datetime, float)
         * name: human readable name of the field
         * choices: List of choices if type==list. Each choice has the format {'id' : 'name'}
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
        
        /* Scan formular rows and initialize field list */
        $element.find('.query_field').each(function() {
            var id = $(this).attr('data-id');
            var input_select = $(this).find('.outputSelector');
            var error_block = $(this).find('.input-error-block');
            
            fieldList.push({
                id: id,
                type: settings.choices[id] ? 'list' : $(this).attr('data-type'),//TODO list type
                name: $(this).find('.name').text(),
                choices: settings.choices[id] ? settings.choices[id] : null,
                sortable : false,
                input_select: input_select.length ? input_select : null,
                input_filter_op: $(this).find('.filter-op'),
                input_filter_value: $(this).find('.filter-value'),
                error: error_block.length ? error_block.html() : null,
            });
        });
        
        /* Find formular sort fields */
        $element.find('.query_sort').each(function() {
            sortInputs.push({
                input_field : $(this).find('.sort-field'),
                input_order : $(this).find('.sort-order')
            });
        });
        
        /* Scan sort field options and mark sortable fields */
        sortInputs[0].input_field.children('option').each(function() {
            for (i in fieldList) {
                if (fieldList[i].id == $(this).attr('value')) {
                    fieldList[i].sortable = true;
                    break;
                }
            }
        });
        
        /* Member functions */
        /**
         * Init function.
         * 
         * Hides non-js formular, shows our nice dynamic form and adds predefined filters (and selected fields) to it.
         * Enables Event handlers for select boxes.
         */
        this.init = function() {
            // Hide non-js form, show js form
            $element.find('.queryform-nojs').hide();
            $element.find('.queryform-js').show();
            
            // Add currently selected and filtered fields to dynamic lists
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                
                if (f.input_filter_op.val() !== '')
                    this.addFilterRow(i);
                
                if (f.input_select && f.input_select.prop('checked'))
                    this.addViewRow(i);
            }
            // Add current sort fields
            for (var i=0; i < sortInputs.length; i++) {
                if (sortInputs[i].input_field.val() !== '') {
                    //Search field in fieldList
                    var field = -1;
                    for (j in fieldList) {
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
            
            // Eventhandler and list update for add*field select boxes
            $('.addviewfield').change(function() {
                obj.addViewRow($(this).val());
                obj.refreshViewFieldSelect();
            });
            this.refreshViewFieldSelect();
            
            $('.addfilter').change(function() {
                obj.addFilterRow($(this).val());
                obj.refreshFilterFieldSelect();
            });
            this.refreshFilterFieldSelect();
            
            $('.addsortfield').change(function() {
                obj.addSortRow($(this).val(),'True');
                obj.updateSortInputs();
                obj.refreshSortFieldSelect();
            });
            this.updateSortInputs();
            this.refreshSortFieldSelect();
        };
        
        /**
         * Add a filter row to the dynamic formular. The filter field is specified by the entry id in the field list
         * array.
         * 
         * @param number (int) Id of the field in fieldList
         */
        this.addFilterRow = function(number) {
            var f = fieldList[number];
            
            var $button = $('<button></button>', {'class':"btn btn-sm btn-danger pull-right",'type':"button"})
                    .append($('<span></span>',{'class':'glyphicon glyphicon-minus'}))
                    .click(function() {
                        f.input_filter_op.val('');
                        f.input_filter_value.val('');
                        $(this).parent().detach();
                        obj.refreshFilterFieldSelect();
                    });
            var $fieldbox = $('<span></span>');
            var $opselector = $('<select></select>', {'class':"form-control input-sm input-slim"})
                    .append(f.input_filter_op.children('option').slice(1).clone())
                    .change(function() {
                        f.input_filter_op.val($(this).val());
                        f.error = null;
                        $(this).siblings('.input-error-block').detach();
                        obj.updateFilterValueInput(number,$(this).val(),$fieldbox);
                    });
            // Initially sync operator select
            if (f.input_filter_op.val() !== '')
                $opselector.val(f.input_filter_op.val());
            else
                f.input_filter_op.val($opselector.val());
                
                
            var $item = $('<li></li>',{'class':"list-group-item queryform-filterbox",'data-id':number})
                    .append(f.name).append('&ensp;')
                    .append($opselector).append('&ensp;')
                    .append($fieldbox)
                    .append($button);
            if (f.error)
                $item.append($('<div></div>',{'class':'input-error-block'}).html(f.error));
            
            $element.find('.filterfield-list').append($item);
            $opselector.focus();
            
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
            case 0: //emtpy
            case 1: //nonempty
                break;
            
            case 2: //equal
            case 3: //unequal
            case 10: //similar
            case 11: //dissimilar
            case 12: //regex
            case 13: //notregex
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
                    var $s = $('<select>',{class : "form-control input-sm input-slim", type: inputTypes[f.type]})
                            .change(changeFunction)
                    if (f.type == 'list') {
                        for (var i in f.choices)
                            $s.append($('<option>',{'value' : i}).text(f.choices[i]))
                    } else {
                        $s.append($('<option>',{'value' : 'True'}).text('wahr'))
                            .append($('<option>',{'value' : 'False'}).text('falsch'));
                    }
                    
                    if (f.input_filter_value.val() !== '')
                        $s.val(f.input_filter_value.val());
                    else
                        f.input_filter_value.val($s.val());
                    $s.appendTo($fieldbox);
                    
                    // TODO select2 if list
                } else {
                    $i = $('<input>',{'class':"form-control input-sm input-slim", 'type': inputTypes[f.type]})
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
                }
                var unescape = function(v) {
                    return v.replace(settings.escapechar+settings.separator,settings.separator)
                            .replace(settings.escapechar+settings.escapechar,settings.escapechar);
                }
            
                //Split value at separator but not at escapechar+separator
                var values = f.input_filter_value.val()
                        .match(new RegExp('('+settings.escapechar+'.|[^'+settings.separator+'])+','g'));
                if (values && values.length > 1)
                    values = values.map(unescape);
                else
                    values=["",""]
            
                $i1 = $('<input>',{'class' : "form-control input-sm input-slim", 'type': 'text'})
                        .val(values[0]);
                $i2 = $('<input>',{'class' : "form-control input-sm input-slim", 'type': 'text'})
                        .val(values[1]);
                
                if (f.type == 'date')
                    $i1.add($i2).attr('placeholder','YYYY-MM-DD');
                else if (f.type == 'datetime')
                    $i1.add($i2).attr('placeholder','YYYY-MM-DDThh:mm');
                    
                $i1.add($i2).change(function() {
                    var val = escape($i1.val()) + ',' + escape($i2.val());
                    f.input_filter_value.val(val);
                });
                
                $fieldbox.append($i1).append('&ensp;und&ensp;').append($i2);
            
                break;
            case 4: //oneof
            case 5: //otherthan
            case 14: //containsall
            case 15: //containsnone
            case 16: //containssome
                var placeholders = {
                    'date' : 'YYYY-MM-DD,YYYY-MM-DD,…',
                    'datetime' : 'YYYY-MM-DDThh:mm,YYYY-MM-DDThh:mm,…',
                    'int' : '<wert>,<wert>,…',
                    'id' : '<id>,<id>,…',
                    'list' : '<id>,<id>,…',
                    'str' : '<wert>,<wert>,…',
                    'float' : '<wert>,<wert>,…'};
                    
                $('<input>',{'class' : "form-control input-sm input-slim",
                             'type': 'text', placeholder: placeholders[f.type]})
                        .change(function() { f.input_filter_value.val($(this).val()); })
                        .attr('size','40')
                        .val(f.input_filter_value.val())
                        .appendTo($fieldbox);
                
                //TODO multiselect with select2 if list
                break;
            }
        }
        
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
            
            // Check hidden checkbox representing the actual state
            f.input_select.prop('checked',true);
            
            // Add box to the dynamic list
            var $button = $('<button></button>', {'class':"btn btn-xs btn-danger",'type':"button"})
                    .append($('<span></span>',{'class':'glyphicon glyphicon-minus'}))
                    .click(function() {
                        f.input_select.prop('checked',false);
                        $(this).parent().detach();
                        obj.refreshViewFieldSelect();
                    });
            var $box = $('<span></span>',{'class':'queryform-fieldbox', 'data-id':number})
                    .text(f.name)
                    .append($button);
            
            this.refreshViewFieldSelect();
            $element.find('.viewfield-list').append($box);
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
            
            var $button = $('<button></button>', {'class':"btn btn-sm btn-danger pull-right",'type':"button"})
                    .append($('<span></span>',{'class':'glyphicon glyphicon-minus'}))
                    .click(function() {
                        $(this).parent().detach();
                        obj.updateSortInputs();
                        obj.refreshSortFieldSelect();
                    });
            var $sortselector = $('<select></select>', {'class':"form-control input-sm input-slim order"})
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
            
            $element.find('.sortfield-list').append($item);
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
            
            // Add not listed fields to selectbox
            var $box = $element.find('.addfilter');
            $box.empty();
            $box.append(new Option('— Filter hinzufügen —',''));
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                if (!currentFields[i]) {
                    $box.append(new Option(f.name, i));
                }
            }
            $box.val('');
        }
        
        /**
         * Refresh the list of options in the .addviewfield select box.
         */
        this.refreshViewFieldSelect = function() {
            // Check currently listed fields
            var currentFields = new Array(fieldList.length);
            $element.find('.viewfield-list .queryform-fieldbox').each(function() {
                currentFields[$(this).attr('data-id')] = true;
            });
            
            // Add all valid and not listed fields to selectbox
            var $box = $element.find('.addviewfield');
            $box.empty();
            $box.append(new Option('— Angezeigtes Feld hinzufügen —',''));
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                if (f.input_select !== null && !currentFields[i]) {
                    $box.append(new Option(f.name, i));
                }
            }
            $box.val('');
        }
        
        /**
         * Refresh the list of options in the .addsortfield select box.
         */
        this.refreshSortFieldSelect = function() {
            // Check currently listed fields
            var currentFields = new Array(fieldList.length);
            var numSortFields=0;
            $element.find('.sortfield-list .queryform-filterbox').each(function() {
                currentFields[$(this).attr('data-id')] = true;
                numSortFields++;
            });
            
            // Add all valid and not listed fields to selectbox
            var $box = $element.find('.addsortfield');
            
            if (numSortFields >= sortInputs.length)
                $box.parent().hide();
            else
                $box.parent().show();
            
            $box.empty();
            $box.append(new Option('— Sortierung hinzufügen —',''));
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                if (f.sortable && !currentFields[i]) {
                    $box.append(new Option(f.name, i));
                }
            }
            $box.val('');
        }
        
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
        }
    };
    
    
    /**
     * The actual "jQuery plugin" - a function to be used on the jQuery object of the query form.
     * It constructs and initializes the above defined object which does everything neccessary for the fancy js form.
     * It also attaches a special submit-handler to the query form to shorten query URLs.
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
                var $toDisable = $();
                $(this).find('.query_field').each(function() {
                    var input_op = $(this).find('.filter-op');
                    if (input_op.val() === '') {
                        $toDisable = $toDisable
                            .add(input_op)
                            .add($(this).find('.filter-value'));
                    }
                });
                $(this).find('.query_sort').each(function() {
                    var input_field = $(this).find('.sort-field');
                    if (input_field.val() === '') {
                        $toDisable = $toDisable
                            .add(input_field)
                            .add($(this).find('.sort-order'));
                    }
                });
                
                // Disable them
                $toDisable.attr("disabled", "disabled");
                
                // Now submit the form
                // Important: We're using the DOM object's handler to prevent calling our jQuery handler recursively
                this.submit();
                
                // And reenable fields after some milliseconds (in case user submitted CSV-Form or navigates back)
                setTimeout(function(){
                    $toDisable.removeAttr("disabled");
                },100);
            });
            
            obj.init();
        });
        return this;
    };
})(jQuery);
