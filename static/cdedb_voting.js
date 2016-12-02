(function($) {
    /**
     * Simple jQuery plugin to disable checkboxes of a classic voting form with multiple votes.
     */
    $.fn.cdedbMultiVote = function(num_votes, bar) {
        var $checkboxes = $(this).find('input[name="vote"]');
        var $barbox = $checkboxes.filter('[value="'+ bar +'"]');

        $checkboxes.change(function() {
            var num_selected = $checkboxes.filter(':checked').length;
            // Disable all unchecked boxes if barbox was checked or maximum number of votes reached
            if (($barbox && $barbox.prop('checked')) || num_selected >= num_votes)
                $checkboxes.each(function(){
                    if (!this.checked)
                        this.disabled = true;
                });
            else
                $checkboxes.prop('disabled',false);
            
            // Disable barbox additionally if any other was selected
            if (num_selected > 0 && $barbox && !$barbox.prop('checked'))
                $barbox.prop('disabled', true);
        });

        return this;
    };
    
    /**
     * Object representing state and methods of the fancy interactive preferential voting form. The jQuery plugin
     * to instantiate this object on the form follows underneath.
     */
    var PrefVote = function($container, candidates, bar_moniker, bar_name, $input_preferencelist) {
        /** Associative list of candidate jQuery DOM elements indexed by their moniker */
        var candidate_list = {};
        
        /* ***************************** *
         * Private function definitions  *
         * ***************************** */
        /**
         * To be used as ondragover
         * Enables dropping on the element.
         */
        function allowDrop(e) {
            e.preventDefault();
        }
        /**
         * To be used as ondragenter
         * Adds .dragover class to the element.
         */
        function dragenter(e) {
            $(this).addClass('dragover');
        }
        /**
         * To be used as ondragleave
         * Removes .dragover class from the element.
         */
        function dragleave(e) {
            $(this).removeClass('dragover');
        }
        /**
         * To be used as ondrop on .prefvote_stage boxes
         * Removes the .dragover class and call moveCandidate() with the element as destination.
         */
        function stage_drop(e) {
            $(this).removeClass('dragover');
            var data = e.originalEvent.dataTransfer.getData("text");
            moveCandidate(candidate_list[data], $(this));
        }
        /**
         * To be used as ondrop on .prefvote_spacer
         * Removes the .dragover class, creates a new stage and spacer underneath this element and calls
         * moveCandidate() with the new stage es destination.
         */
        function spacer_drop(e) {
            $(this).removeClass('dragover');
            
            var data = e.originalEvent.dataTransfer.getData("text");
            $candidate = candidate_list[data];
            if (!$candidate)
                return;
            
            $new_stage = createStage();
            $new_spacer = createSpacer();
            if ($(this).hasClass('positive')) {
                $new_stage.addClass('positive');
                $new_spacer.addClass('positive');
            } else if ($(this).hasClass('negative')) {
                $new_stage.addClass('negative');
                $new_spacer.addClass('negative');
            }
            
            $new_stage.insertAfter($(this));
            $new_spacer.insertAfter($new_stage);
            
            moveCandidate($candidate, $new_stage);
        }
        
        /**
         * To be used implicitly by drop functions.
         * Moves the $candidate to the $destination stage and deletes the source stage if empty and not neutral.
         * Afterwards calls updatePreferenceList() to update the text form.
         */
        function moveCandidate($candidate, $destination) {
            $source = $candidate.parent();
            $destination.append($candidate);
            // If source stage is empty and not neutral stage ...
            if ($source.children('.prefvote_candidate').length == 0 && !$source.hasClass('neutral')) {
                // ... remove spacer and source stage
                $source.next().detach();
                $source.detach();
            }
            updatePreferenceList();
        }
        /**
         * Create text representation of preference from DOM elements and update text based input field.
         */
        function updatePreferenceList() {
            var stages = [];
            $container.children('.prefvote_stage').each(function(){
                var stage_candidates = [];
                $(this).children('.prefvote_candidate').each(function(){
                    stage_candidates.push($(this).attr('data-moniker'));
                });
                if ($(this).hasClass('neutral'))
                    stage_candidates.push(bar_moniker);
                stages.push(stage_candidates.join('='));
            });
            var preflist = stages.join('>');
            $input_preferencelist.val(preflist);
        }
        
        /** Create a new .prefvote_spacer box and return jQuery reference. */
        function createSpacer() {
            var $sp = $('<div></div>', {'class': 'prefvote_spacer'});
            $sp.on('dragover',allowDrop);
            $sp.on('drop',spacer_drop);
            $sp.on('dragenter',dragenter);
            $sp.on('dragleave',dragleave);
            return $sp;
        }
        /** Create a new .prefvote_stage box and return jQuery reference. */
        function createStage() {
            var $st = $('<div></div>', {'class': 'prefvote_stage'});
            $st.on('dragover',allowDrop);
            $st.on('drop',stage_drop);
            $st.on('dragenter',dragenter);
            $st.on('dragleave',dragleave);
            return $st;
        }
        
        /**
         * Initialization function
         * Reads the candidate list and creates candidate DOM elements without adding them to the DOM tree yet.
         * (Createing stages and adding candidate boxes will be done by readPreferenceList() later.)
         */
        function init() {
            for (var i in candidates) {
                var moniker = candidates[i][1].moniker;
                var $cand = $('<span></span>', {'class': 'prefvote_candidate',
                                                'draggable': 'true',
                                                'id': 'vote-cand_' + candidates[i][1].id,
                                                'data-moniker': moniker});
                $cand.text(candidates[i][1].description);
                candidate_list[moniker] = $cand;
                $cand.on('dragstart',function(e) {
                    e.originalEvent.dataTransfer.setData('text', $(this).attr('data-moniker'));
                });
            }
        }
        
        /* ************** *
         * Initialization *
         * ************** */
        init();
        
        /* **************** *
         * Public functions *
         * **************** */
        /**
         * Reads the preference list from the text only form, parses it and creates stages and adds candidates to them.
         * May be used as event handler whenever displaying the js form.
         */
        this.readPreferenceList = function() {
            // Remove all stage boxes
            $container.children('.prefvote_stage,.prefvote_spacer').detach();
            
            // Get preference list
            var preflist = $input_preferencelist.val();
            
            // Parse stages
            var stages = preflist.split('>');
            var bar_option = false;
            
            // Create first spacer
            var $sp = createSpacer().appendTo($container);
            if (bar_moniker) {
                if (bar_option)
                    $sp.addClass('negative');
                else 
                    $sp.addClass('positive');
            }
            
            // Create stage boxes and spacers
            for (var i in stages) {
                if (stages[i] == '')
                    continue;
                var $stage = createStage().appendTo($container);
                var is_neutral = false;
                var stage_candidates = stages[i].split('=');
                for (var j in stage_candidates) {
                    var $cand = candidate_list[stage_candidates[j]];
                    if ($cand) {
                        $stage.append($cand);
                    } else if (bar_moniker && stage_candidates[j] == bar_moniker) {
                        bar_option = true;
                        is_neutral = true;
                        $stage.addClass('neutral');
                        $stage.append($('<div></div>', {'class': 'label'}).text(bar_name));
                    }
                }
                if (bar_moniker && !is_neutral) {
                    if (bar_option)
                        $stage.addClass('negative');
                    else 
                        $stage.addClass('positive');
                }
                
                var $sp = createSpacer().appendTo($container);
                if (bar_moniker) {
                    if (bar_option)
                        $sp.addClass('negative');
                    else 
                        $sp.addClass('positive');
                }
            }
            
            // Find missing candidates by checking if they are in the DOM tree
            var missing_candidates = [];
            for (var i in candidate_list) {
                if (candidate_list[i].closest(document.documentElement).length == 0) 
                    missing_candidates.push(candidate_list[i])
            }
            
            if (missing_candidates.length > 0 || (bar_moniker && !bar_option)) {
                // If use_bar and bar has been added yet, add missing_candidates to neutral stage
                if (bar_moniker && bar_option) {
                    $neutral_stage = $container.children('.prefvote_stage.neutral');
                    for (var i in missing_candidates)
                        $neutral_stage.append(missing_candidates[i]);
                        
                // else create new stage under all other stages (and make it neutral)
                } else {
                    var $stage = createStage().appendTo($container);
                    for (var i in missing_candidates)
                        $stage.append(missing_candidates[i]);
                    var $sp = createSpacer().appendTo($container);
                    if (bar_moniker) {
                        $stage.addClass('neutral');
                        $stage.append($('<div></div>', {'class': 'label'}).text(bar_name));
                        $sp.addClass('negative');
                    }
                }
            }
        };
    };


    /**
     * jQuery plugin for the fancy interactive preferential voting.
     */
    $.fn.cdedbPrefVote = function(candidates, bar_moniker, bar_name, $input_preferencelist) {
        if ($(this).data('cdedbPrefVote'))
            return;

        var obj = new PrefVote($(this), candidates, bar_moniker, bar_name, $input_preferencelist);
        $(this).data('cdedbPrefVote',obj);
    }
})(jQuery);
