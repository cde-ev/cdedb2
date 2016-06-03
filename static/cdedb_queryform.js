/**
 * Extended javascript functionality for query forms in the cdedb2.
 * This jQuery method should be applied to the query form dom object onload.
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
         * id: database id (string),
         * type: data type (string: bool, int, string, list, date, datetime, float)
         * name: human readable name of the field
         * choices: List of choices if type==list. Each choice has the format {'id' : 'name'}
         * input_select: jQuery DOM object of the non-js field select checkbox
         * input_filter_op: jQuery DOM object of the non-js filter operator select box
         * input_filter: jQuery DOM object of the non-js filter value field
         */
        var fieldList = [];
        
        /* Scan formular rows and initialize field list */
        $element.find('.query_field').each(function() {
            var id = $(this).attr('data-id');
            var input_select = $(this).find('.outputSelector');
            
            fieldList.push({
                id: id,
                type: settings.choices[id] ? 'list' : $(this).attr('data-type'),//TODO list type
                name: $(this).find('.name').text(),
                choices: settings.choices[id] ? settings.choices[id] : null,
                input_select: input_select.length ? input_select : null,
                input_filter_op: $(this).find('.filter-op'),
                input_filter_value: $(this).find('.filter-value'),
            });
        });
        
        console.log(fieldList);
        
        /* Member functions */
        /**
         * Init function.
         * 
         * Hides non-js formular, shows our nice dynamic form and adds predefined filters (and selected fields) to it.
         * Enables Event handlers for select boxes.
         */
        this.init = function() {
            // Hide non-js form
            $element.find('.queryform-nojs').hide();
            $element.find('.queryform-js').show();
            
            // Add currently selected fields to dynamic lists
            for (var i=0; i < fieldList.length; i++) {
                var f = fieldList[i];
                
                if (f.input_filter_op.val() !== '')
                    this.addFilterRow(i);
                
                if (f.input_select && f.input_select.prop('checked'))
                    this.addViewRow(i);
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
            
            $element.find('.filterfield-list>.insertpoint').before($item);
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
                if (f.type == 'bool' || f.type == 'list') {
                    var $s = $('<select>',{class : "form-control input-sm input-slim", type: inputTypes[f.type]})
                            .change(function() { f.input_filter_value.val($(this).val()); })
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
                            .change(function() { f.input_filter_value.val($(this).val()); })
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
    };
    
    $.fn.cdedbQueryForm = function(options) {
        if ($(this).data('cdedbQueryForm'))
            return;
        
        var obj = new QueryForm(this,options);
        
        $(this).data('cdedbQueryForm',obj);
        obj.init();
    };
})(jQuery);
