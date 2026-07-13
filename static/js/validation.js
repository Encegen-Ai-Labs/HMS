/* =========================================================
   HMS — Global Real-Time Input Validation & Animations
   Applies to every <form> on every page automatically.
   Uses each input's existing type / required / pattern /
   minlength / maxlength attributes (native HTML5 constraints)
   and adds live visual feedback: red shake on error, green
   glow on success, inline helper messages.
   ========================================================= */
(function () {
    "use strict";

    function niceMessage(input) {
        const validity = input.validity;
        const label = (input.placeholder || input.name || "This field").replace(/_/g, " ");

        if (validity.valueMissing) return label + " is required.";
        if (validity.typeMismatch && input.type === "email") return "Please enter a valid email address.";
        if (validity.patternMismatch) {
            return input.title ? input.title : label + " format is invalid.";
        }
        if (validity.tooShort) return label + " must be at least " + input.minLength + " characters.";
        if (validity.tooLong) return label + " must be at most " + input.maxLength + " characters.";
        if (validity.rangeUnderflow) return label + " must be " + input.min + " or more.";
        if (validity.rangeOverflow) return label + " must be " + input.max + " or less.";
        if (validity.badInput) return "Please enter a valid value.";
        return "Please check this field.";
    }

    function getOrCreateMsgEl(input) {
        let msg = input.parentElement.querySelector(":scope > .field-error-msg");
        if (!msg) {
            msg = document.createElement("small");
            msg.className = "field-error-msg";
            msg.style.display = "none";
            input.insertAdjacentElement("afterend", msg);
        }
        return msg;
    }

    function clearState(input) {
        input.classList.remove("field-invalid", "field-valid");
        const msg = input.parentElement.querySelector(":scope > .field-error-msg");
        if (msg) msg.style.display = "none";
    }

    function validateField(input, showSuccess) {
        if (input.type === "hidden" || input.disabled || input.type === "submit" || input.type === "button") {
            return true;
        }

        // Skip empty, non-required optional fields until submit is attempted
        if (!input.required && input.value === "" && !input.dataset.touchedOnce) {
            clearState(input);
            return true;
        }

        const valid = input.checkValidity();

        if (!valid) {
            input.classList.remove("field-valid");
            input.classList.add("field-invalid");
            const msg = getOrCreateMsgEl(input);
            msg.textContent = niceMessage(input);
            msg.style.display = "block";
            // restart shake animation
            input.style.animation = "none";
            // eslint-disable-next-line no-unused-expressions
            input.offsetHeight;
            input.style.animation = "";
        } else {
            input.classList.remove("field-invalid");
            const msg = input.parentElement.querySelector(":scope > .field-error-msg");
            if (msg) msg.style.display = "none";
            if (showSuccess && input.value !== "") {
                input.classList.add("field-valid");
            } else {
                input.classList.remove("field-valid");
            }
        }
        return valid;
    }

    function attachFieldListeners(input) {
        if (input.dataset.hmsValidationBound) return;
        input.dataset.hmsValidationBound = "true";

        input.addEventListener("blur", function () {
            input.dataset.touchedOnce = "true";
            validateField(input, true);
        });

        input.addEventListener("input", function () {
            if (input.dataset.touchedOnce) {
                validateField(input, true);
            }
        });

        input.addEventListener("focus", function () {
            const msg = input.parentElement.querySelector(":scope > .field-error-msg");
            if (msg && !input.classList.contains("field-invalid")) {
                msg.style.display = "none";
            }
        });
    }

    function attachFormListener(form) {
        if (form.dataset.hmsValidationBound) return;
        form.dataset.hmsValidationBound = "true";

        const fields = form.querySelectorAll("input, select, textarea");
        fields.forEach(attachFieldListeners);

        form.addEventListener("submit", function (e) {
            let firstInvalid = null;
            let allValid = true;

            fields.forEach(function (input) {
                input.dataset.touchedOnce = "true";
                const ok = validateField(input, true);
                if (!ok && !firstInvalid) firstInvalid = input;
                if (!ok) allValid = false;
            });

            if (!allValid) {
                e.preventDefault();
                e.stopPropagation();
                if (firstInvalid) {
                    firstInvalid.scrollIntoView({ behavior: "smooth", block: "center" });
                    firstInvalid.focus();
                }
            }
        });
    }

    function scanForms() {
        document.querySelectorAll("form").forEach(attachFormListener);
    }

    document.addEventListener("DOMContentLoaded", scanForms);

    // Re-scan periodically in case content is added dynamically (modals, etc.)
    const observer = new MutationObserver(function () {
        scanForms();
    });
    document.addEventListener("DOMContentLoaded", function () {
        observer.observe(document.body, { childList: true, subtree: true });
    });

    /* ============ Subtle entrance animation for cards/tables ============ */
    document.addEventListener("DOMContentLoaded", function () {
        const animTargets = document.querySelectorAll(
            ".card, .summary-box, .profile-card, .styled-table, .custom-table, table"
        );
        animTargets.forEach(function (el, i) {
            el.style.opacity = "0";
            el.style.animation = "fadeInUp 0.45s ease " + Math.min(i * 0.04, 0.4) + "s both";
        });
    });
})();