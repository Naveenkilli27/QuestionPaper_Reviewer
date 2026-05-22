/**
 * Renders exactly N file upload rows (Set A …) based on "Number of question paper sets".
 */
(function() {
    var SLOT_NAMES = ["set_a", "set_b", "set_c", "set_d", "set_e"];
    var LABELS = ["Set A", "Set B", "Set C", "Set D", "Set E"];

    function clamp(n) {
        if (isNaN(n) || n < 1) return 1;
        if (n > 5) return 5;
        return n;
    }

    function render() {
        var numInput = document.getElementById("num_sets");
        var container = document.getElementById("upload-slots");
        if (!numInput || !container) return;

        var n = clamp(parseInt(numInput.value, 10));
        numInput.value = String(n);

        container.innerHTML = "";
        for (var i = 0; i < n; i++) {
            var row = document.createElement("label");
            row.className = "file-row";
            var span = document.createElement("span");
            span.className = "lbl";
            span.textContent = LABELS[i];
            var input = document.createElement("input");
            input.type = "file";
            input.name = SLOT_NAMES[i];
            input.required = true;
            input.accept = ".pdf,.docx,.txt,.md";
            row.appendChild(span);
            row.appendChild(input);
            container.appendChild(row);
        }
    }

    document.addEventListener("DOMContentLoaded", function() {
        var numInput = document.getElementById("num_sets");
        if (!numInput) return;
        numInput.addEventListener("input", render);
        numInput.addEventListener("change", render);
        render();

        var form = document.getElementById("review-form");
        var busy = document.getElementById("busy-overlay");
        if (form && busy) {
            form.addEventListener("submit", function() {
                busy.hidden = false;
                busy.setAttribute("aria-busy", "true");
            });
        }
    });
})();