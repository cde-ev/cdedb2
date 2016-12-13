(function($) {
    /**
     * Object representing state and methods of the fancy orderrow functionality, which is as simplified version of the
     * fancy preferential voting. The jQuery plugin to instantiate this object on the form follows underneath.
     *
     * General behaviour:
     * The jQuery plugin is called on the div.orderrow_container and creates an instance of the following object. The
     * init() function is called, stores jQuery wrappers of all .orderrow-outer inside the row_list array and adds
     * event handlers
     *
     * Rows can be moved onto other rows using Drag'n'Drop or clicking ('activating') a .orderrow-inner and then
     * clicking the destination .orderrow-outer. Drag'n'Drop is handled by storing the rows's id in event.dataTransfer;
     * 'activating' is done by adding a class to the .orderrow-outer and div.orderrow-container.
     *
     * Moving a row to another is done by moveRow() and results in placing the .orderrow-outer right before the
     * destination row. It also calls updateRowList() to create the text based order list and update the form input.
     */
    var OrderRow = function($container, $input_rowlist) {
        /** List of row jQuery DOM elements indexed by their id */
        var row_list = {};

        /* ***************************** *
         * Private function definitions  *
         * ***************************** */
        /**
         * To be used as ondragover
         * Enables dropping on the element.
         */
        function allowDrop(e) {
            e.preventDefault();
        }
        /**
         * To be used as ondragenter
         * Adds .dragover class to the element.
         * But the more complicated way with reference counting.
         */
        function dragenter(e) {
            var ct = $(this).data('dragcounter') || 0;
            $(this).data('dragcounter', ct+1);
            $(this).addClass('dragover');
        }
        /**
         * To be used as ondragleave
         * Removes .dragover class from the element.
         * But the more complicated way with reference counting.
         */
        function dragleave(e) {
            var ct = $(this).data('dragcounter') - 1;
            $(this).data('dragcounter', ct);
            if (ct === 0)
                $(this).removeClass('dragover');
        }
        /**
         * To be used as ondrop on .orderrow-outer
         * Removes the .dragover class and call moveRow() with the element as destination.
         */
        function row_drop(e) {
            $(this).data('dragcounter', 0);
            $(this).removeClass('dragover');
            var data = e.originalEvent.dataTransfer.getData("text");
            moveRow(row_list[data], $(this));
            e.preventDefault();
        }
        /**
         * To be used as onclick on .orderrow-outer
         * If container is active: moves the active row before this one and deactivates container
         */
        function outer_click(e) {
            if ($container.hasClass('active')) {
                if ($(this).hasClass('active')) {
                    $container.removeClass('active');
                    $(this).removeClass('active');
                } else {
                    var $active_candidates = $container.find('.orderrow-outer.active');
                    moveRow($active_candidates, $(this));
                    $active_candidates.removeClass('active');
                    $container.removeClass('active');
                }
            }
        }
        /**
         * To be used as onclick on .orderrow-inner
         * If container is not active: activates this row and the container
         */
        function inner_click(e) {
            var outer = $(this).closest('.orderrow-outer');
            if (!$container.hasClass('active')) {
                outer.addClass('active');
                $container.addClass('active');
                e.stopPropagation();
            }
        }
        /**
         * Returns an event handler function for keyboard events that calls the given callback if the keyCode represents
         * a press of ENTER or SPACE function.
         */
        function getKeyboardHandler(callback) {
            return function(e) {
                if (e.keyCode == 13 || e.keyCode == 32) {
                    callback.call(this,e);
                    e.preventDefault();
                }
            };
        }

        /**
         * To be used implicitly by drop functions.
         * Moves the $row before the $destination row. Afterwards calls updateRowList() to update the form input.
         */
        function moveRow($row, $destination) {
            $destination.before($row);
            updateRowList();
        }
        /**
         * Create text representation of preference from DOM elements and update text based input field.
         */
        function updateRowList() {
            var row_ids = [];
            $container.children('.orderrow-outer').each(function(){
                row_ids.push($(this).attr('data-id'));
            });
            var textList = row_ids.join(',');
            $input_rowlist.val(textList);
        }

        /**
         * Initialization function
         * Adds event handlers to the .orderrow-row elements and appends them to the row_list.
         */
        function init() {
            $container.children('.orderrow-outer')
                .click(outer_click)
                .on('dragenter', dragenter)
                .on('dragleave', dragleave)
                .on('dragover', allowDrop)
                .on('drop', row_drop)
                .on('keydown',getKeyboardHandler(outer_click))
                .on('keydown',getKeyboardHandler(inner_click))
                .each(function() {
                    row_list[$(this).attr('data-id')] = $(this);
                })

                .children('.orderrow-inner')
                .click(inner_click)
                .on('dragstart',function(e) {
                    e.originalEvent.dataTransfer.setData('text', $(this).closest('.orderrow-outer').attr('data-id'));
                    $container.removeClass('active').find('.orderrow-outer').removeClass('active');
                });
        }

        /* ************** *
         * Initialization *
         * ************** */
        init();

    };


    /**
     * jQuery plugin for the fancy interactive row ordering.
     *
     * parameters:
     * $input_rowlist: jQuery object of text only form input field
     */
    $.fn.cdedbOrderRow = function($input_rowlist) {
        if ($(this).data('cdedbOrderRow'))
            return;

        var obj = new OrderRow($(this), $input_rowlist);
        $(this).data('cdedbOrderRow',obj);

        return this;
    }
})(jQuery);
