(function($) {
    /**
     * Custom wrapper for selectize.js to search for events via XHR requests.
     *
     * Adds selectizes to the given DOM elements to search events via jQuerys ajax() function and the json api at the
     * given url provided by our python code.
     *
     * @param options A list of json objects for the initial options. If not given the event shortname cannot be displayed correctly.
     */
    $.fn.cdedbSearchEvent = function(url, options) {
        $(this).selectize({
            'valueField' : 'id',
            'labelField' : 'title',
            searchField: ['title','shortname'],
            create: false,
            options: options,
            maxItems: 1,
            copyClassesToDropdown: false,
            render: {
                option: function(data, escape) {
                    console.log(data);
                    return '<div class="option"><div class="name">' + escape(data['title']) +
                        '</div><div class="meta">' + escape(data['shortname']) + '</div></div>';
                }
            },
            load: function(query, callback) {
                if (!query.length) return callback();

                let target_url = new URL(url, document.location);
                target_url.searchParams.append('phrase', query);
                $.ajax({
                    url: target_url,
                    type: 'GET',
                    error: function() {
                        callback();
                    },
                    success: function(res) {
                        console.log(res.events);
                        if (!res.events) return callback();
                        return callback(res.events);
                    }
                });
            }
        });
        return this;
    };
})(jQuery);
