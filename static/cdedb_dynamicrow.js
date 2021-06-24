/**
 * Extended javascript functionality for list forms with add and delete functionality and direct edit.
 * The jQuery method defined at the end of this file should be applied to the table or list element onload.
 *
 * Each row, that should by dynamically managed, must have the `drow-row` class. One row must be provided as prototype
 * for new rows and tagged with the class `drow-prototype`. It will be hidden automatically.
 *
 * New rows will have the `drow-new` class. They may also be given by the server side HTML generation, e.g. in case the
 * previous attempt to save the form data failed validation. The `name` attribute of all input fields with class
 * `drow-input`, as well as the `drow-indicator` are automatically updated to "<basename><no>", where <basename> is
 * taken from the `data-basename` attribute and <no> are descending negative integers, unique for each new row.
 *
 * All new rows and rows marked to be deleted (`drow-delete`) get their `.drow-indicator` (which is hidden
 * automatically) checked.
 */
(function($) {
    var DynamicRow = function(element, options) {
        /** jQuery DOM object of the form */
        var $element = $(element);
        var obj = this;
        var settings = $.extend({
            addButton : $(),
            callback : function () {},
            delButtonTitle: "delete row",
            prefix: ''
        }, options || {});
        var prefix = settings.prefix ? String(settings.prefix) + '_' : '';


        /**
         * Private function to generate delete button with appropriate onclick handler and append to a given row.
         * Also corrects the visual delete state of the row.
         *
         * @param $row jQuery object of row.
         * @param newrow boolean, indicating if this is a new row. In this case the delete button will detach the row
         *               instead of toggling the indicator.
         */
        var addDeleteButton = function($row, newrow) {
            var $deleteButton = $('<button />', {'type': 'button',
                                                 'title': settings.delButtonTitle,
                                                 'aria-label': settings.delButtonTitle,
                                                 'aria-pressed': 'false',
                                                 'class': 'btn btn-danger btn-sm' })
                    .append($('<span></span>', {'class': 'fas fa-trash-alt'}));

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
                    $deleteButton.addClass('active')
                        .attr('aria-pressed','true');
                }

                $deleteButton.click(function() {
                    var check = $indicator.prop("checked");
                    $indicator.prop("checked", !check);
                    if (check) {
                        $row.removeClass('drow-delete');
                        $(this).removeClass('active')
                            .attr('aria-pressed','false');
                    } else {
                        $row.addClass('drow-delete');
                        $(this).addClass('active')
                            .attr('aria-pressed','true');
                    }
                });
            }
            $row.find('.drow-buttonspace').after($deleteButton);
        };

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
                    .css('display', 'block');

            $element.find('.drow-row').each(function() {
                var $row = $(this);
                addDeleteButton($row, false);
            });
            $element.find('.drow-new').each(function() {
                var $row = $(this);
                addDeleteButton($row, true);
            });
            /* Remove names from prototype row to avoid interference with new rows */
            $element.find('.drow-prototype .drow-input').removeAttr('name');
        };

        /**
         * Add a new row to formular based on the prototype row.
         * TODO hide button if no drow-prototype row is available
         */
        this.addRow = function() {
            var $prototype = $element.find('.drow-prototype');
            var $row = $prototype.clone(false);
            $row.addClass('drow-new')
                .removeClass('drow-prototype');
            $row.find('.drow-indicator').prop("checked", true);

            addDeleteButton($row, true);
            $row.css('display', ''); /* instead of show() to preserve display attribute and be faster */
            $prototype.before($row);
            $row.find('.drow-input').first().focus();
            settings.callback.call($row);
            obj.refreshInputNames();
        };

        /**
         * Refresh the names of inputs of new rows based on their basename and their position in the list.
         *
         * If an input has an id, search for <label>s referencing the input and set the id (as well as the labels'
         * attributes) to drow-input-{name}.
         */
        this.refreshInputNames = function() {
            var i=-1;
            $element.find('.drow-new').each(function() {
                var $row = $(this);
                $(this).find('.drow-input,.drow-indicator').each(function() {
                    var name = prefix + $(this).attr('data-basename');
                    name += String(i);
                    $(this).attr('name', name);

                    var id = $(this).attr('id');
                    if (id) {
                        var new_id = prefix + 'drow-input-' + name;
                        $(this).attr('id', new_id);
                        $row.find('label[for="' + id + '"]').attr('for', new_id);
                    }
                });
                i--;
            });
        };
    };

    /**
     * The actual "jQuery plugin" - a function to be used on the jQuery object of form table or list.
     * It constructs and initializes the above defined object which does everything neccessary for the fancy js form.
     *
     * options may contain the following:
     * addButton: jQuery wrapper of Button to add a new row. It will be unhidden and get an onclick handler.
     * callback: A callback method to be called after adding a new row. It will be bound to a jQuery object wrapping the
     *           new row. It may be used to initialize inner dynamic row blocks.
     * delButtonTitle: A string to be used as title attribute on the delete row button. Defaults to "delete row".
     * prefix: A string to be used as prefix for all inputs of this DynamicRow
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
