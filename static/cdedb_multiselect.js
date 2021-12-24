/**
 * Some jQuery helpers for the assembly/change_ballot, event/manage_inhabitants and event/manage_attendees pages.
 * The jQuery plugins defined below can be used for a better user experience when having multiselects with many
 * entries, e.g. adding participants to courses or lodgements or specifying attachments for ballots.
 */
(function($){
    /**
     * Custom wrapper for selectize.js to search for entries in a given list.
     *
     * Adds selecizes to the given DOM elements to search entries in the given list of all participants/attachments.
     * This should be used for the add attendee multiselect on event/manage_attendees for courses or the add inhabitant
     * multiselect on event/manage_inhabitants for lodgements. Also, it is useful for adding attachments to ballots; for
     * this usecase the current and group functionality is not used, i.e. the corresponding arguments are left empty.
     *
     * The `options` parameter should contain a list of objects where each object
     * represents an attachment / a participant of the event, that is not already part of
     * the course/lodgement in the relevant event part.
     * Each object must contain the following fields:
     * id: registration_id of the attachment/participant to be used as option value
     * name: full name of the attachment/participant to be displayed
     * current: the id of the current course/lodgement to show it's name in the rendering. null if currently not
     *          assigned to a course/lodgement
     *
     * The `group_names` parameter should be an object, mapping course/lodgement ids of all courses/lodgements to their
     * display name. This is used to lookup the name of the current course/lodgement of a participant and show them
     * inside the rendered option.
     *
     * `current_label` is inserted in the rendered option in front of the name of the current course/lodgement. Should
     * be something like "current course: " or similar.
     */
    $.fn.cdedbMultiSelect = function(options, group_names = {}, current_label = "") {
        $(this).selectize({
            'valueField' : 'id',
            'labelField' : 'name',
            searchField: ['name'],
            create: false,
            options: options,
            maxItems: null,
            copyClassesToDropdown: false,
            render: {
                option: function(data, escape) {
                    if (data['current'] && group_names[data['current']]) {
                        return '<div class="option"><div class="name">' + escape(data['name']) +
                               '</div><div class="meta">' + current_label + escape(group_names[data['current']]) +
                               '</div></div>';
                    } else {
                        return '<div class="option">' + escape(data['name']) + '</div>';
                    }
                }
            }
        });
    };

    /**
     * jQuery plugin as a helper to improve usability of the delete checkbox.
     *
     * This plugin should be called on the `delete` checkboxes of the manage_attendees/manage_inhabitants pages. It
     * inserts a small red button with minus-icon and the given title and hides the checkbox in return. The button will
     * toggle the checked state of the (hidden) checkbox and add some highlight to the surrounding list item.
     */
    $.fn.cdedbRemoveParticipantButton = function(title) {
        $(this).each(function () {
            var $box = $(this);
            var $li = $(this).closest('li,tr');
            var $button = $('<button></button>', {
                'class': 'btn btn-xs btn-danger',
                'type': 'button',
                'aria-pressed': 'false',
                'aria-label': title,
                'title': title
            });
            $button.append($('<span></span>', {'class': 'fas fa-minus'}));
            $button.append($('<span></span>', {'class': 'sr-only'}).append(title));
            $button.click(function () {
                $(this).toggleClass('active');
                if ($(this).hasClass('active')) {
                    $box.prop('checked', true);
                    $(this).attr('aria-pressed', 'true');
                    $li.addClass('list-group-item-danger');
                } else {
                    $box.prop('checked', false);
                    $(this).attr('aria-pressed', 'false');
                    $li.removeClass('list-group-item-danger');
                }
            });
            if ($box.prop('checked')) {
                $button.addClass('active');
                $li.addClass('list-group-item-danger');
            }
            $box.parent().after($button);
            $box.parent().css('display', 'none');
        });
    };
})(jQuery);
