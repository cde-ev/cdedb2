/**
 * Extended javascript functionality for list forms with add and delete functionality and direct edit.
 * The jQuery method defined at the end of this file should be applied to the table or list element onload.
 */
(function($) {
    var DynamicRow = function(element, options) {
        /** jQuery DOM object of the form */
        var $element = $(element);
        var obj = this;
        var settings = $.extend({
            addButton : $(),
            callback : function () {}
        }, options || {});


        /**
         * Private to generate delete button with appropriate onclick handler and append to a given row.
         * Also corrects the visual delete state of the row.
         * 
         * @param $row jQuery object of row.
         * @param newrow boolean, indicating if this is a new row. In this case the delete button will detach the row
         *               instead of toggling the indicator.
         */
        var addDeleteButton = function($row, newrow) {
            var $deleteButton = $('<button />', {'type': 'button',
                                                 'title': 'Löschen',
                                                 'class': 'btn btn-danger btn-sm' })
                    .append($('<span></span>', {'class': 'glyphicon glyphicon-trash'}))
                    
            if (newrow) {
                $deleteButton.click(function() {
                    $row.detach();
                    obj.refreshInputNames();
                });
            } else {
                var $indicator = $row.find('.drow-indicator');
                if ($indicator.prop('disabled'))
                    return;
                    
                if ($indicator.prop("checked")) {
                    $row.addClass('drow-delete');
                    $deleteButton.removeClass('active');
                }
                    
                $deleteButton.click(function() {
                    var check = $indicator.prop("checked");
                    $indicator.prop("checked", !check);
                    if (check) {
                        $row.removeClass('drow-delete');
                        $(this).removeClass('active');
                    } else {
                        $row.addClass('drow-delete');
                        $(this).addClass('active');
                    }
                });
            }
            $row.find('.drow-buttonspace').after($deleteButton);
        }
        
        /**
         * Init function.
         * 
         * Hides prototype row and indicator checkboxes and adds delete buttons. Shows the add button and adds event
         * handler.
         */
        this.init = function() {
            $element.find('.drow-prototype').hide();
            $element.find('.drow-buttonspace').hide();
            
            settings.addButton
                    .click(function() {
                        obj.addRow();
                    })
                    .show();
            
            $element.find('.drow-row').each(function() {
                var $row = $(this);
                addDeleteButton($row, false);
            });
            $element.find('.drow-new').each(function() {
                var $row = $(this);
                addDeleteButton($row, true);
            });
        };
        
        /**
         * Add a new row to formular based on the prototype row.
         */
        this.addRow = function() {
            var $prototype = $element.find('.drow-prototype');
            var $row = $prototype.clone(false);
            $row.addClass('drow-new')
                .removeClass('drow-prototype');
            $row.find('.drow-indicator').prop("checked", true);
            
            addDeleteButton($row, true);            
            $row.show();
            $prototype.before($row);
            $row.find('.drow-input').first().focus();
            obj.refreshInputNames();
            settings.callback.call($row);
        };
        
        /**
         * Refresh the names of inputs of newrows based on their basename and their position in the list.
         */
        this.refreshInputNames = function() {
            var i=1;
            $element.find('.drow-new').each(function() {
                $(this).find('.drow-input,.drow-indicator').each(function() {
                    $(this).attr('name', $(this).attr('data-basename') + String(i));
                });
                i++;
            });
        };
    };
    
    /**
     * The actual "jQuery plugin" - a function to be used on the jQuery object of form table or list.
     * It constructs and initializes the above defined object which does everything neccessary for the fancy js form.
     */
    $.fn.cdedbDynamicRow = function(options) {
        $(this).each(function() {
            if ($(this).data('cdedbDynamicRow'))
                return;
            
            var obj = new DynamicRow(this, options);
            $(this).data('cdedbDynamicRow',obj);
            
            
            obj.init();
        });
        return this;
    };
})(jQuery);
