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
}

function setCaretToPos (input, pos) {
  setSelectionRange(input, pos, pos);
}

function jumpCsvPosition(row,col) {
    var $textinput =  $('#input-data');
    var text = $textinput.val();
    var pos = -1;
    // search row
    for (var i=1; i < row;) {
        var offset = text.substring(pos+1).search(/(\n|;)(?:"([^"]*(?:""[^"]*)*))/g)+1;
        if (offset == -1)
            return;
        pos += offset;
        if (text[pos] == '\n')
            i++;
    }
    // search col
    if (col >= 0) {
        for (var i=0; i < col; i++) {
            var offset = text.substring(pos+1).search(/(\n|;)(?:"([^"]*(?:""[^"]*)*))/g)+1;
            if (offset == -1)
                return;
            pos += offset;
        }
        pos+=1;
    }
    pos+=1;
    setCaretToPos($textinput[0], pos);
}

$(function() {
    $('.row-col-key').addClass('clickable').click(function() {
        jumpCsvPosition($(this).attr('data-row'),$(this).attr('data-col'));
    });
    $('.row-key').addClass('clickable').click(function() {
        jumpCsvPosition($(this).attr('data-row'),-1);
    });
});
