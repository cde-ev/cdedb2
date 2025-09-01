(function($) {
    /**
     * Custom wrapper for selectize.js to search for events via XHR requests.
     *
     * Adds selectizes to the given DOM elements to search events via jQuerys ajax() function and the json api at the
     * given url provided by our python code.
     *
     * @param options A list of json objects for the initial options. If not given the event shortname cannot be displayed correctly.
     */
    $.fn.cdedbSearchEvent = function(options=null, multi=false) {
        $(this).selectize({
            'valueField' : 'id',
            'labelField' : 'title',
            searchField: ['title','shortname'],
            create: false,
            createOnBlur: true,
            closeAfterSelect: !multi,
            options: options,
            maxItems: multi ? null : 1,
            copyClassesToDropdown: false,
            render: {
                option: function(data, escape) {
                    return '<div class="option"><div class="name">' + escape(data['title']) +
                        '</div><div class="meta">' + escape(data['shortname']) + '</div></div>';
                }
            },
            onChange: $(this).onChange,
        });
        return this;
    };
})(jQuery);
