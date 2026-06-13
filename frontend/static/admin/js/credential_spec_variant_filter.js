(function($) {
    'use strict';

    $(document).ready(function() {
        var $game = $('#id_game');
        var $variant = $('#id_variant');

        if (!$game.length || !$variant.length) return;

        var currentVariantId = $variant.val();

        function loadVariants(gameId) {
            $variant.empty().append('<option value="">---------</option>');
            if (!gameId) return;

            var basePath = window.location.pathname.split('/credentialspec/')[0];
            var url = basePath + '/credentialspec/variants-for-game/' + gameId + '/';

            $.getJSON(url, function(data) {
                if (!data.variants.length) return;

                $.each(data.variants, function(i, v) {
                    var opt = $('<option>').val(v.id).text(v.label);
                    if (String(v.id) === String(currentVariantId)) {
                        opt.prop('selected', true);
                    }
                    $variant.append(opt);
                });
            });
        }

        // On game change: reload variants
        $game.on('change', function() {
            currentVariantId = null;  // Clear previous selection on game change
            loadVariants($(this).val());
        });

        // On page load (edit mode): if game is already selected, load its variants
        if ($game.val()) {
            loadVariants($game.val());
        }
    });
})(django.jQuery);
