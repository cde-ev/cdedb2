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
     * Un-inlined code from cdedbSearchPerson to avoid code duplication
     */
    function submitRequest(query, callback, url, params, exclude, toggle) {
            if (!query.length) return callback();

            let target_url = new URL(url, document.location);
            // no URI-encoding here, as URLSearchParams below does this internally:
            // https://url.spec.whatwg.org/#interface-urlsearchparams
            params['phrase'] = query;
            if (toggle && toggle['toggle'].is(':checked')) {
                let new_params = $.extend({}, params, toggle);  // values from toggle take precedence
                delete new_params['toggle'];
                for (const key in new_params)
                    target_url.searchParams.append(key, new_params[key]);
            } else {
                for (const key in params)
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

    function refocus(selectize, value) {
        if (value) {
            if (selectize.maxItems === 1) {
                selectize.clear();
                selectize.clearOptions();
                selectize.open();
                selectize.setTextboxValue(value);
                selectize.onSearchChange(value);
            } else {
                selectize.clearOptions();
                for (const item of value.split(",")) {
                    selectize.createItem(item);
                }
            }
        }
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
     * @param freeform If true, all inputs will be accepted as new option, else only well-formed DB-Ids are accepted to be
     *                  added as option.
     * @param multi If true, a list of personas seperated by ',' is produced, otherwise only a single persona can be selected
     * @param placeholder If given, this string is used as placeholder in the selectize.js control
     * @param toggle Optionally let some url parameters depend on a checkbox. If given, this object must contain a key `toggle`,
     *               which holds the checkbox' jquery object and it may contain arbitrary other keys to append to the url with their values.
     *               When the checkbox is checked, values from this object take precedence over those specified via the `params` argument.
     */
    $.fn.cdedbSearchPerson = function(url, params, exclude, freeform, multi, placeholder, toggle) {


        exclude ??= [];
        this.selectize({
            'placeholder' : placeholder ?? $(this).attr("placeholder"),
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
                        var res = '<div class="option" id="selectize-result-option-'
                            + data['id'] + '"><div class="name">' + escape(data['name'])
                            + '</div><div class="meta">' + cdedb_id(data['id']);
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
                submitRequest(query, callback, url, params, exclude, toggle);
            },
            onInitialize: function() {
                // Initialize with display names instead of raw CdEDBIDs (as prefilled in the HTML).
                // To do this, we have to submit every CdEDBID to the server and wait for
                // the result containing its display name.
                const selectize = this;
                const initial_values = selectize.getValue().split(",").map(s => s.trim());
                let retCount = 0;
                for (const db_id of initial_values) {
                    // remove the old option only displayed by CdEDBID
                    selectize.removeOption(db_id);
                    submitRequest(
                        db_id,
                        function(res) {
                            if (!res || res.length === 0) return;
                            // add the new option with display name
                            selectize.addOption(res[0]);
                            // count how many (async) requests have returned
                            retCount += 1;
                            if (retCount === initial_values.length){
                                // all requests have returned, set the values of the selectize control, now with pretty names
                                selectize.setValue(initial_values);
                            }
                        },
                        url,
                        params,
                        exclude,
                        toggle
                    );
                }
            }
        });
        let input = $(this);
        let selectize = input[0].selectize;
        selectize.on("focus", function () {
            refocus(selectize, input.val())
        });
        if (toggle) {  // toggling potentially changes search results
            toggle['toggle'].on('change', function () {
                refocus(selectize, input.val());
            });
        }
        return this;
    };
})(jQuery);
