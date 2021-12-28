/**
 * The jQuery plugins defined below can be used for a better user experience when having multiselects with many
 * entries, e.g. adding participants to courses / lodgements or specifying attachments for ballots.
 */
(function($){
    /**
     * Custom wrapper for selectize.js to search for entries in a given list.
     *
     * Adds selectizes to the given DOM elements to search entries in the given list of all options. Each option may
     * have an associated group, whose name is rendered below the option name (but not taken into account for the
     * selectize search).
     *
     * @param options list of options, each option represented by an object with the following fields:
     *                * `id`:       id of the option to be used as option value
     *                * `name`:     full name of the option to be displayed and used as search field
     *                * `group_id`: the id of the group this option is associated with
     * @param group_names object mapping the group ids to a descriptive name which is displayed for all options
     *                    associated with this group
     * @param current_label This is rendered in front of the group name of each option which has an associated group,
     *                      independent of the group. Probably something like "Currently: " or similar.
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
                    if (data['group_id'] && group_names[data['group_id']]) {
                        return '<div class="option"><div class="name">' + escape(data['name']) +
                               '</div><div class="meta">' + current_label + escape(group_names[data['group_id']]) +
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
