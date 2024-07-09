(function($) {
    /**
     *
     */
    $.fn.multiset = function (delete_icon, delete_title, restore_icon, restore_title) {
        $form = $(this);
        $(this).find('.multiset-explanation').show();

        $form.find('.multiset-input').each( function() {
            /* Insert two buttons (delete and restore) after each input */
            let group = $(this);
            let input = group.find('input, textarea, select');
            if (input.length > 0) {
                (input.parent().is('label') ? input.parent() : input)
                    .after(' <button type="button" class="btn btn-danger align-top" title="' + delete_title + '">' + delete_icon + '</button>')
                    .after(' <button type="button" class="btn btn-default align-top" title="' + restore_title + '">' + restore_icon + '</button>')
                    .css('display', 'inline');
                if (input.css('width') === input.parent().css('width')) {
                    input.css('width', '80%');
                }
            }
            $form.find('#changenotes')
                .css('width', input.css('width'))
                .parent()
                .css('margin-left', '-3px');
            let delete_button = group.find('button.btn-danger');
            let restore_button = group.find('button.btn-default');

            /* Save the original value. This is the new, but not saved, value in case of validation error. */
            if (input.is(':checkbox')) {
                input.data('original_value', input.is(':checked') ? "true" : "");
            } else {
                input.data('original_value', input.val());
            }

            /*
                Clicking delete clears the corresponding input, clicking restore restores the original value.
                Either way, trigger the "input" event for the input, to adjust coloring and button visibility.
            */
            delete_button.on("click", function () {
                if (input.is(':checkbox')) {
                    input.prop('checked', false);
                } else {
                    input.val("");
                }
                input.trigger("input");
            });
            restore_button.on("click", function () {
                if (input.is(':checkbox')) {
                    input.prop('checked', Boolean(input.data('original_value')));
                } else {
                    input.val(input.data('original_value'));
                }
                input.trigger("input");
            });

            /* Optionally color the input too: */
            let to_color = group;
            // to_color.add(input);

            /* After any change to the input, adjust the display. */
            input.on("input", function () {

                let current;
                if ($(this).is(':checkbox')) {
                    current = $(this).is(':checked') ? "true" : "";
                } else {
                    current = $(this).val();
                }
                let original = $(this).data('original_value');


                if (current === original) {
                    /* The input has the original value. If this is non-empty show the delete button. Show no coloring. */
                    to_color.removeClass("alert-danger").removeClass("alert-warning").removeClass("alert-success");
                    restore_button.hide();
                    if (current) {
                        delete_button.show();
                    } else {
                        delete_button.hide();
                    }
                } else if (current) {
                    /*
                        The input has changed but is non-empty.
                        Show the restore button.
                        If the input was originally empty, color green.
                        Otherwise show the delete button and color yellow.
                    */
                    to_color.removeClass("alert-danger").removeClass("alert-warning").removeClass("alert-success");
                    restore_button.show();
                    if (original) {
                        to_color.addClass("alert-warning");
                        delete_button.show();
                    }
                    else {
                        to_color.addClass("alert-success")
                        delete_button.hide();
                    }
                } else {
                    /* Input is now empty, but wasn't originally. Color red and show restore button. */
                    to_color.addClass("alert-danger").removeClass("alert-warning").removeClass("alert-success");
                    delete_button.hide();
                    restore_button.show();
                }
            });

            input.trigger("input");
        });
    }
})(jQuery);
