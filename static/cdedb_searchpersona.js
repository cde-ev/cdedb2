(function($) {
    /**
     * Compute checkdigit as used in ISBNs and CdEdb user ids.
     * See compute_checkdigit() in common.py for reference implementation and more details.
     */
    function compute_checkdigit(num) {
        var digits = [];
        while (num > 0) {
            digits.push(num % 10);
            num = Math.floor(num / 10);
        }

        var dsum = 0;
        for (var i=0;i<digits.length;i++) {
            dsum += (i+2)*digits[i];
        }
        return "0123456789X"[((-dsum % 11) + 11) % 11];
    }

    /**
     * Get user id in CdEdb ID syntax from an numeric user id.
     */
    function cdedb_id(id) {
        var check = compute_checkdigit(parseInt(id));
        return 'DB-' + id + '-' + check;
    }

    /**
     * Custom wrapper for selectize.js to search for personas via XHR requests.
     *
     * Adds selecizes to the given DOM elements to search personas via jQuerys ajax() function and the json api at the
     * given url provided by our python code.
     *
     * @param url The url of the server-side endpoint, relative to the document's location.
     * @param params Object specifying GET-parameters to be appended to the url.
     *               The search phrase will be added with `phrase` as key.
     * @param exclude May contain an array of (unformatted) persona ids, which will be excluded from the fetched result list.
     * @param freeform' If true, all inputs will be accepted as new option, else only well-formed DB-Ids are accepted to be
     *                  added as option.
     * @param multi If true, a list of personas seperated by ',' is produced, otherwise only a single persona can be selected
     * @param placeholder If given, this string is used as placeholder in the selectize.js control
     */
    $.fn.cdedbSearchPerson = function(url, params, exclude, freeform, multi, placeholder) {
        exclude ??= [];
        $(this).selectize({
            'placeholder' : placeholder || '',
            'valueField' : 'cdedb_id',
            'labelField' : 'name',
            searchField: ['name','email','id'],
            create: true,
            createOnBlur: true,
            createFilter: freeform ? null : function(string) {
                var res = string.match(/^DB-(\d+)-(\w)$/);
                if (!res) return false;
                return (exclude.indexOf(parseInt(res[1])) === -1) && (compute_checkdigit(res[1]) === res[2]);
            },
            options: [],
            maxItems: (multi ? null : 1),
            copyClassesToDropdown: false,
            render: {
                option: function(data, escape) {
                    if (data['id']) {
                        var res = '<div class="option"><div class="name">' + escape(data['name']) +
                                '</div><div class="meta">' + cdedb_id(data['id']);
                        if (data['email'])
                            res += ' • '+ escape(data['email']);
                        res += '</div></div>';
                        return res;
                    } else {
                        return '<div class="option">' + escape(data['name']) + '</div>';
                    }
                }
            },
            load: function(query, callback) {
                if (!query.length) return callback();
                let target_url = new URL(url, document.location);
                params['phrase'] = encodeURIComponent(query);
                for (const key in params) {
                    target_url.searchParams.append(key, params[key]);
                }
                $.ajax({
                    url: target_url,
                    type: 'GET',
                    error: function() {
                        callback();
                    },
                    success: function(res) {
                        if (!res.personas) return callback();

                        var i = res.personas.length - 1;
                        while (i >= 0) {
                            var persona = res.personas[i];
                            if (exclude.indexOf(persona.id) !== -1)
                                res.personas.splice(i, 1);
                            persona.cdedb_id = cdedb_id(persona.id);
                            i -= 1;
                        }

                        return callback(res.personas);
                    }
                });
            }
        });
        return this;
    };
})(jQuery);
