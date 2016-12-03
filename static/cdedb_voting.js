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
     *
     * General behaviour:
     * The jQuery plugin is called on the div.prefvote_container and creates an instance of the following object. The
     * init() function is called and creates a span.prefvote_candidate for each candidate in the candidates parameter.
     * These DOM objects are stored as jQuery wrappers in candidate_list.
     *
     * On opening the jsform tab, the event handler readPreferenceList() should be called. It creates some
     * div.prefvote_stage and div.prefvote_spacer, also considering if a bar option is used (bar_moniker != null).
     *
     * Candidates can be moved to stages and spacers using Drag'n'Drop or clicking ('activating') a candidate and then
     * clicking the destination div. Drag'n'Drop is handled by storing the candidate's moniker in event.dataTransfer;
     * 'activating' is done by adding a class to the span.prefvote_candidate and div.prefvote_container.
     *
     * Moving a candidate to a spacer is done by splitSpacer() and results in creating a new stage and a new spacer
     * underneath the destination spacer and moving the candidate to the new stage. Moving a candidate to a (existing or
     * new) stage is done by moveCandidate() and does three actions: moving the candidate, deleting the source stage if
     * empty, calling updatePreferenceList() to create the text based preference list and update the voting form.
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
         * Removes the .dragover class and uses splitSpacer() to create new Stage and move condidate into.
         */
        function spacer_drop(e) {
            $(this).removeClass('dragover');
            
            var data = e.originalEvent.dataTransfer.getData("text");
            $candidate = candidate_list[data];
            if (!$candidate)
                return;
            splitSpacer($(this), $candidate);
        }
        /**
         * To be used as onclick on .prefvote_stage
         * If container is active: moves active candidate(s) to stage and disactivates container
         */
        function stage_click(e) {
            if ($container.hasClass('active')) {
                var $active_candidates = $container.find('.prefvote_candidate.active');
                moveCandidate($active_candidates,$(this));
                $active_candidates.removeClass('active');
                $container.removeClass('active')
            }
        }
        /**
         * To be used as onclick on .prefvote_spacer
         * If container is active: splits spacer (moving active candidate to new stage) and disactivates container
         */
        function spacer_click(e) {
            if ($container.hasClass('active')) {
                var $active_candidates = $container.find('.prefvote_candidate.active');
                splitSpacer($(this),$active_candidates);
                $active_candidates.removeClass('active');
                $container.removeClass('active')
            }
        }
        /**
         * To be used as onclick on .prefvote_candidate
         * If candidate is active: disactivates container and candidate
         * Else: activates the candidate, the container and disactivates all other candidates
         */
        function candidate_click(e) {
            if ($(this).hasClass('active')) {
                $container.removeClass('active');
                $(this).removeClass('active');
            } else {
                $container.find('.prefvote_candidate').removeClass('active');
                $(this).addClass('active');
                $container.addClass('active');
            }
            e.stopPropagation();
        }
        /**
         * Returns an event handler function for keyboard events that calls the given callback if the keyCode represents
         * a press of ENTER or SPACE function.
         */
        function getKeyboardHandler(callback) {
            return function(e) {
                if (e.keyCode == 13 || e.keyCode == 32)
                    callback.call(this,e);
            };
        }
        
        /**
         * Split $spacer, introduce new stage and move $candidate into it (using moveCandidate()).
         * To be called by spacer_drop() and spacer_click()
         */
        function splitSpacer($spacer, $candidate) {
            $new_stage = createStage();
            $new_spacer = createSpacer();
            if ($spacer.hasClass('positive')) {
                $new_stage.addClass('positive');
                $new_spacer.addClass('positive');
            } else if ($spacer.hasClass('negative')) {
                $new_stage.addClass('negative');
                $new_spacer.addClass('negative');
            }
            
            $new_stage.insertAfter($spacer);
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
            $destination.append(' ');
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
            var $sp = $('<div></div>', {'class': 'prefvote_spacer', 'tabindex': '0'});
            $sp.on('dragover',allowDrop);
            $sp.on('drop',spacer_drop);
            $sp.on('dragenter',dragenter);
            $sp.on('dragleave',dragleave);
            $sp.on('click',spacer_click);
            $sp.on('keydown',getKeyboardHandler(spacer_click));
            return $sp;
        }
        /** Create a new .prefvote_stage box and return jQuery reference. */
        function createStage() {
            var $st = $('<div></div>', {'class': 'prefvote_stage', 'tabindex': '0'});
            $st.on('dragover',allowDrop);
            $st.on('drop',stage_drop);
            $st.on('dragenter',dragenter);
            $st.on('dragleave',dragleave);
            $st.on('click',stage_click);
            $st.on('keydown',getKeyboardHandler(stage_click));
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
                                                'data-moniker': moniker,
                                                'tabindex': '0'});
                $cand.text(candidates[i][1].description);
                candidate_list[moniker] = $cand;
                $cand.on('dragstart',function(e) {
                    e.originalEvent.dataTransfer.setData('text', $(this).attr('data-moniker'));
                    $container.removeClass('active').find('.prefvote_candidate').removeClass('active');
                });
                $cand.click(candidate_click);
                $cand.on('keydown',getKeyboardHandler(candidate_click));
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
                        $stage.append($cand).append(' ');
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
                        $stage.append(missing_candidates[i]).append(' ');
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
     *
     * parameters:
     * candidates: List of all candidates in form: [ [id, {'id', 'moniker', 'description'}] ]
     * bar_moniker: Moniker of bar option, null if bar is not used
     * bar_name: Label of bar option / neutral stage box
     * $input_preferencelist: jQuery object of text only voting form input field
     */
    $.fn.cdedbPrefVote = function(candidates, bar_moniker, bar_name, $input_preferencelist) {
        if ($(this).data('cdedbPrefVote'))
            return;

        var obj = new PrefVote($(this), candidates, bar_moniker, bar_name, $input_preferencelist);
        $(this).data('cdedbPrefVote',obj);
    }
})(jQuery);
