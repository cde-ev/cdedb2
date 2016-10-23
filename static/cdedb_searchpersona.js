(function($) {
    /**
     * Compute checkdigit as used in ISBNs and CdEdb user ids.
     * See compute_checkdigit() in common.py for reference implementation and more details.
     */
    function compute_checkdigit(num) {
        digits = []
        while (num > 0) {
            digits.push(num % 10);
            num = Math.floor(num / 10);
        }

        var dsum = 0;
        for (var i=0;i<digits.length;i++) {
            dsum += (i+2)*digits[i];
        }
        return "ABCDEFGHIJK"[((-dsum % 11) + 11) % 11];
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
     * The url parameter must contain '%s' wich will be replaced by the search pattern
     */
    $.fn.cdedbSearchPerson = function(url,exclude) {
        $(this).selectize({
            'placeholder' : '',
            'valueField' : 'cdedb_id',
            'labelField' : 'name',
            searchField: ['name','email','id'],
            create: true,
            createOnBlur: true,
            createFilter: function(string) {
                var res = string.match(/^DB-(\d+)-(\w)$/);
                if (!res) return false;
                return (exclude.indexOf(parseInt(res[1])) == -1) && (compute_checkdigit(res[1]) == res[2]);
            },
            options: [],
            maxItems: 1,
            copyClassesToDropdown: false,
            render: {
                option: function(data, escape) {
                    if (data['id'] && data['email']) {
                        return '<div class="option"><div class="name">' + escape(data['name']) +
                               '</div><div class="meta">' + cdedb_id(data['id']) + ' • '+ escape(data['email']) +
                               '</div></div>';
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
                        if (!res.personas) return callback();

                        var i = res.personas.length - 1;
                        while (i >= 0) {
                            var persona = res.personas[i];
                            if (exclude.indexOf(persona.id) != -1)
                                res.personas.splice(i, 1);
                            persona.cdedb_id = cdedb_id(persona.id);
                            i -= 1;
                        }

                        return callback(res.personas);
                    }
                });
            }
        });
    };
})(jQuery)
