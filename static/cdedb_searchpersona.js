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
     * Adds selecizes to the given DOM elements to search personas in the specified realm via jQuerys ajax() function
     * and the json api provieded by our python code.
     */
    $.fn.cdedbSearchPerson = function(realm,exclude) {
        $(this).selectize({
            'placeholder' : '',
            'valueField' : 'cdedb_id',
            'labelField' : 'name',
            searchField: 'name',
            create: true,
            options: [],
            maxItems: 1,
            copyClassesToDropdown: false,
            load: function(query, callback) {
                if (!query.length) return callback();
                $.ajax({
                    url: '/db/core/persona/select?kind=' + encodeURIComponent(realm) + '&phrase=' + encodeURIComponent(query),
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
