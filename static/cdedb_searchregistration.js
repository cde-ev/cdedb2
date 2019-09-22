(function($) {
    /**
     * Custom wrapper for selectize.js to search for registrations via XHR requests.
     *
     * Adds selectizes to the given DOM elements to search registrations via jQuerys ajax() function and the json api at the
     * given url provided by our python code.
     *
     * The url parameter must contain '%s' wich will be replaced by the search pattern.
     * @param exclude May contain an array of registration ids, which will be excluded from the fetched result list.
     * @param freeform If true, all inputs will be accepted as new option, else only well-formed IDs are accepted to be
     *                 added as option.
     * @param multi If true, a list of registrations seperated by ',' is produced, otherwise only a single registration can be selected
     * @param placeholder If given, this string is used as placeholder in the selectize.js control
     */
    $.fn.cdedbSearchRegistration = function(url,exclude,freeform,multi,placeholder) {
        $(this).selectize({
            'placeholder' : placeholder || '',
            'valueField' : 'id',
            'labelField' : 'name',
            searchField: ['name','email','id'],
            create: true,
            createOnBlur: true,
            createFilter: freeform ? null : function(string) {
                var res = string.match(/^(\d+)$/);
                if (!res) return false;
                return (exclude.indexOf(parseInt(res[1])) === -1);
            },
            options: [],
            maxItems: (multi ? null : 1),
            copyClassesToDropdown: false,
            render: {
                option: function(data, escape) {
                    if (data['email']) {
                        var res = '<div class="option"><div class="name">' + escape(data['name']) +
                            '</div><div class="meta">' + escape(data['email']) + '</div></div>';
                        return res;
                    } else {
                        return '<div class="option">' + escape(data['name']) + '</div>';
                    }
                }
            },
            load: function(query, callback) {
                if (!query.length) return callback();
                $.ajax({
                    url: url.replace('%s',encodeURIComponent(query)),
                    type: 'GET',
                    error: function() {
                        callback();
                    },
                    success: function(res) {
                        if (!res.registrations) return callback();

                        var i = res.registrations.length - 1;
                        while (i >= 0) {
                            var registration = res.registrations[i];
                            if (exclude.indexOf(registration.id) !== -1)
                                res.registrations.splice(i, 1);
                            i -= 1;
                        }

                        return callback(res.registrations);
                    }
                });
            }
        });
        return this;
    };
})(jQuery);
