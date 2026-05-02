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
        }, options || {});


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
                                                 'class': 'btn btn-danger btn-sm',
                                                 'id': 'dynamicrow-delete-button-' + $row.data("drow-id"),})
                    .append($('<span></span>', {'class': 'far fa-trash-alt'}));

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

        var setUpRow = function($row) {
            newrow = $row.hasClass("drow-new");
            addDeleteButton($row, newrow);
            // Add input handler for inline add button if it exists.
            $row.find('.drow-inline-add-button')
                .on('click', function() {obj.addRow($row);})
                .show();
            // Add input handler for row move buttons if they exist.
            $row.find('.drow-move-row-up-button')
                .on('click', function() {moveRow($row, true)})
                // .show();
            $row.find('.drow-move-row-down-button')
                .on('click', function() {moveRow($row, false)})
                // .show();
            $row.show();
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
            $element.find('.drow-hide').hide();

            // Add handler for the given add button and add per row handlers.
            settings.addButton.on('click', function() {obj.addRow();}).show();
            $element.find('.drow-row,.drow-new').each(function() {
                setUpRow($(this));
            });
            /* Remove names from prototype row to avoid interference with new rows */
            $element.find('.drow-prototype .drow-input').removeAttr('name');

            refresh();
        };

        /**
         * Add a new row to formular based on the prototype row.
         */
        this.addRow = function($before) {
            // Create a new row from the prototype.
            var $prototype = $element.find('.drow-prototype');
            var $row = $prototype.clone(false);
            $row.addClass('drow-new')
                .removeClass('drow-prototype');
            // Mark the creation indicator checkbox.
            $row.find('.drow-indicator').prop("checked", true);

            // Set up the new row.
            setUpRow($row);
            // If an element was given (by clicking an inline add button), insert the new row sbove an existing
            if ($before !== undefined)
                $before.before($row);
            else
                $prototype.before($row);
            $row.find('.drow-input').first().focus();

            // If there is an inline add button, add the inline handler.
            $row
                .find('.drow-inline-add-button')
                .on('click', function() {obj.addRow($row);})

            // Update the names and ids of all inputs and their labels from the basename and the current drow id.
            $row.find('.drow-input,.drow-indicator').each(function() {
                var name = $(this).attr('data-basename');
                name += String($row.data("drow-id"));
                $(this).attr('name', name);

                var id = $(this).attr('id');
                if (id) {
                    var new_id = 'drow-input-' + name;
                    $(this).attr('id', new_id);
                    $row.find('label[for="' + id + '"]').attr('for', new_id);
                }
            });

            // Update the drow id of the prototype for the next created row.
            // Only adjusting the data does not affect the DOM and therefore further prototype rows.
            // Only adjusting the attrs does not affect the jQuery object for further usage.
            let new_drow_id = $prototype.data('drow-id') - 1;
            $prototype.data('drow-id', new_drow_id);
            $prototype.attr('data-drow-id', new_drow_id);

            // Call refresh and any given callback.
            refresh();
            settings.callback.call($row);
        };

        var moveRow = function($row, up) {
            let $other = up ? $row.prev() : $row.next();
            $row.detach;
            up ? $other.before($row) : $other.after($row);
            refresh();
        }

        /**
         * To be called after adding a new row or moving rows.
         *
         * Sets the 'pos' input for all rows according to their position in the DOM, if it exists.
         */
        var refresh = function() {
            // Iterate over all rows and adjust their 'pos' inputs if they exist.
            var i = 0;
            $element.find('.drow-input.input-pos').each(function() {
                $(this).val(i);
                i++;
            });
            let rows = $element.find('.drow-row,.drow-new');
            rows.find('.drow-move-row-up-button').show().first().hide();
            rows.find('.drow-move-row-down-button').show().last().hide();
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
