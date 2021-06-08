
(function($) {
    /**
     * Helper functions to select text / position cursor inside textbox.
     * Source: http://stackoverflow.com/a/499158
     */
    function setSelectionRange(input, selectionStart, selectionEnd) {
      if (input.setSelectionRange) {
        input.focus();
        input.setSelectionRange(selectionStart, selectionEnd);
      }
      else if (input.createTextRange) {
        var range = input.createTextRange();
        range.collapse(true);
        range.moveEnd('character', selectionEnd);
        range.moveStart('character', selectionStart);
        range.select();
      }
      input.blur();
      input.focus();
    }

    function setCaretToPos (input, pos) {
      setSelectionRange(input, pos, pos);
    }

    /**
     * jQuery plugin to jump to a specific position (row, column) in a textarea with CSV data.
     *
     * @param row The CSV row to jump to (0-indexed)
     * @param col The CSV column to jump to (0-indexed)
     */
    $.fn.jumpCsvPosition = function (row,col) {
        var text = $(this).val();

        // split csv into fields
        var matches = text.match(/("(""|[^"])*"|[^";\n]*)([;\n]|$)/g);

        // search row
        var r = 0;
        var i = 0;
        var pos = 0;
        while(r < row) {
            if (i >= matches.length)
                return;
            if (matches[i].slice(-1) == '\n')
                r++;
            pos += matches[i].length;
            i++;
        }

        // search col
        if (col >= 0) {
            for (var c = 0; c < col; c++) {
                if (i >= matches.length)
                    return;
                pos += matches[i].length;
                i++;
            }
            if (text[pos] == '"')
                pos += 1;
        }

        setCaretToPos(this[0], pos);
    }
})(jQuery);
