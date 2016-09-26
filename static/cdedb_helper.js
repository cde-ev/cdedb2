(function($) {
    /** Custom replacement for scrollIntoView(). */
    $.fn.checkIfInView = function () {
        var top = $(this).offset().top;
        var height = $(this).outerHeight();
        var offset = top - $(window).scrollTop();
        if (offset + height > window.innerHeight)
            $(window).scrollTop(top + height + 10 - window.innerHeight);
        else if (offset < 0)
            $(window).scrollTop(top - 10);
    }

    /**
     * Simple jQuery plugin to hide unimportant things and unhide them on button click.
     *
     * Searches elements with class 'unimportant' inside the given element and hides them. A click on the given button
     * unhides them. The button will be 'shown' onload, in case it was hidden by css rules.
     */
    $.fn.cdedbHideUnimportant = function($button) {
        $elements = $(this).find('.unimportant');
        $elements.hide();
        $button
            .click(function() {
                $elements.show();
                $(this).hide();
            })
            .show();
    };

    /**
     * jQuery plugin to prevent users from accidentally leave forms without saving.
     */
    $.fn.cdedbProtectChanges = function(message) {
        // Message seems to be ignored in most current browsers
        message = message || "Wenn Du die Seite verlässt, gehen Deine ungespeicherten Änderungen verloren.";
        $forms = $(this);

        // For each form
        $forms.each(function() {
            $form = $(this);
            // Store current state
            $form.data('serialize',$(this).serialize());

            // Add submit and abort handlers to suppress unwanted confirms
            $form.submit(function() {
                $(this).data('clean_exit', true);
            });
            $form.find('.cancel').click(function() {
                $form.data('clean_exit', true);
            });
        });

        // BeforeUnload event handler
        // From http://stackoverflow.com/a/155812
        window.onbeforeunload = function(e) {
            var changed = false;
            $forms.each(function(){
                changed = $(this).serialize() != $(this).data('serialize') && !$(this).data('clean_exit');
                return !changed;
            });
            if (changed) {
                e = e || window.event;
                if (e) e.returnValue = message;
                return message;
            }
        };
    };

    /**
     * jQuery plugin to prevent users from accidentally doing irreversible actions.
     */
    $.fn.cdedbProtectAction = function(message, is_safe_callback) {
        message = message || "Diese Aktion kann nicht rückgängig gemacht werden.";
        is_safe_callback = is_safe_callback || function(){ return false; };

        // Submit handler
        $(this).submit(function() {
            return ((is_safe_callback.bind(this))() || confirm(message));
        });
    };

    /**
     * jQuery Plugin for advanced selection in lists (e.g. query results.)
     *
     * Provides support for mouse and keyboard selection as known from Windows Explorer and other file browsers.
     * See https://github.com/mhthies/listselect.js for full source
     */
    var ListSelect = function(element,options) {
        var $element = $(element);
        var obj = this;
        var settings = $.extend({
            mouse : true,
            keyboard : true,
            itemClass: 'ls-item',
            selectedClass: 'ls-selected',
            cursorClass: 'ls-cursor',
            startClass: 'ls-start',
            focusFirst: true,
            callback: function() {},
            rowCallback: function() {},
        }, options || {});

        /* Private methods */
        /** Unselect all items */
        function clearSelection() {
            $element.find('.'+settings.itemClass+'.'+settings.selectedClass)
                .removeClass(settings.selectedClass)
                .each(settings.rowCallback);
        };
        /** Toggle selection of the given item */
        function toggleSelection($item) {
            $item.toggleClass(settings.selectedClass).each(settings.rowCallback);
        };
        /** Select the given item */
        function selectSingle($item) {
            $item.addClass(settings.selectedClass).each(settings.rowCallback);
        };
        /** Select items between selection start pointer and cursor */
        function selectRange() {
            var $c = $element.find('.'+settings.cursorClass);
            var $s = $element.find('.'+settings.startClass);
            var $list = ($c.index() > $s.index()) ?
                    $s.nextAll('.'+settings.itemClass) : $s.prevAll('.'+settings.itemClass);
            selectSingle($s);
            $list.each(function() {
                selectSingle($(this));
                // Break when cursor is reached
                return !($(this).hasClass(settings.cursorClass));
            });
        };
        /** Set cursor (and possibly) selection start pointer to given item */
        function setCursor($item,setStart) {
            $element.find('.'+settings.itemClass)
                .removeClass(settings.cursorClass);
            $item.addClass(settings.cursorClass);
            if (setStart) {
                $element.find('.'+settings.startClass)
                    .removeClass(settings.startClass);
                $item
                    .addClass(settings.startClass);
            }
        };

        // Add event handlers
        if (settings.mouse)
            /* Mouse event handler */
            $element.find('.'+settings.itemClass)
                .on('click', function(e) {
                    if (!e.shiftKey) {
                        if (!e.ctrlKey) {
                            clearSelection();
                            selectSingle($(this));
                        } else {
                            toggleSelection($(this));
                        }
                        setCursor($(this),true);
                    } else {
                        if (!e.ctrlKey)
                            clearSelection();
                        setCursor($(this),false);
                        selectRange();
                    }
                    settings.callback.call(element);
                });

        if (settings.keyboard)
            /* Key event handler */
            $element.on('keydown', function(e) {
                switch(e.keyCode) {
                    case 32: //Leertaste
                        if (e.ctrlKey) {
                            toggleSelection($(this).find('.'+settings.cursorClass));
                            setCursor($(this).find('.'+settings.cursorClass),true);
                            e.preventDefault();
                            settings.callback.call(element);
                        }
                        break;

                    case 38: //Up
                    case 40: //Down
                        var $c = $element.find('.'+settings.cursorClass);
                        var $list = (e.keyCode == 40) ?
                                $c.next() : $c.prev();
                        // return if no next/previous item
                        if ($list.length < 1)
                            return;
                        var $next = $list.first();

                        if (!e.shiftKey) {
                            if (!e.ctrlKey) {
                                clearSelection();
                                selectSingle($next);
                                setCursor($next,true);
                            } else {
                                setCursor($next,false);
                            }
                        } else {
                            if (!e.ctrlKey)
                                clearSelection();
                            setCursor($next,false);
                            selectRange();
                        }
                        $next.checkIfInView();
                        e.preventDefault();
                        settings.callback.call(element);
                        break;
                }
            });

        if (settings.focusFirst)
            $element.find('.'+settings.itemClass).first()
                .addClass(settings.cursorClass);


        /* Public methods */
        /** For external usage: Clear all selected items */
        this.selectNone = function() {
            clearSelection();
            settings.callback.call(element);
        };
        /** For external usage: Select all items */
        this.selectAll = function() {
            $element.find('.'+settings.itemClass).not('.'+settings.selectedClass)
                .addClass(settings.selectedClass)
                .each(settings.rowCallback);
            settings.callback.call(element);
        };
        /** For external usage: Toggle selection of all items */
        this.invertSelection = function() {
            $element.find('.'+settings.itemClass)
                .toggleClass(settings.selectedClass)
                .each(settings.rowCallback);
            settings.callback.call(element);
        };
    };

    /** jQuery Plugin method */
    $.fn.cdedbListSelect = function() {
        $(this).each(function() {
            if ($(this).data('listSelect'))
                return;

            var obj = new ListSelect(this, {
                rowCallback: function() {
                    $(this).find('.rowSelector').prop('checked', $(this).hasClass('ls-selected'));
                }
            });

            $(this).find('.rowSelector')
                .change(function() {
                    if ($(this).is(':checked'))
                        $(this).closest('.ls-item').addClass('ls-selected');
                    else
                        $(this).closest('.ls-item').removeClass('ls-selected');
                })
                .click(function(e){
                    e.stopPropagation();
                });
            $(this).find('a').click(function(e){
                e.stopPropagation();
            });

            $(this).data('listSelect',obj).attr('tabindex','0');
        });
        return this;
    };
})(jQuery);
