var inputsChanged = false;

function do_bulk_action(setting, field) {
    event.preventDefault();

    if (inputsChanged) {
        alert('One of more fields in form is not yet saved. Please save the form first');
        return false;
    }

    var config = $('#setting-page-config');
    var url = config.data('url-show-preview');
    var modal = "modal-bulk_actions";
    var data = "setting=" + setting + "&field=" + field;

    $.ajax({
        type: "GET",
        url: url,
        data: data,
        success: function (response) {
            $("#bulk_modal_content").html(response);
            $("#" + modal).modal('show');
        },
        error: function (xhr, status, errorThrown) {
            var span = document.createElement('span');
            span.innerHTML = 'Error';

            swal({
                title: 'Unable to complete request',
                content: span,
                icon: 'warning'
            });
        }
    });

    return false;
}

(function ($) {
    var config = $('#setting-page-config');
    var urlRecordsInCategory = config.data('url-records-in-category');
    var urlRecordDetails = config.data('url-record-details');
    var urlRunRecordBase = config.data('url-run-record').replace('/00000000-0000-0000-0000-000000000000', '');

    $(document).on('change', 'form input, form textarea', function () {
        inputsChanged = true;
    });

    var report_id = '';

    // ---- Quick search ------------------------------------------------------
    // One request to search_index/ returns every setting with its fields'
    // labels, help text and current values. Matching runs in the browser on
    // punctuation-free tokens, and a result jumps to the exact field (or
    // section header) it matched.

    var urlSearchIndex = config.data('url-search-index') ||
        String(urlRecordsInCategory || '').replace(/records_in_category\/?$/, 'search_index/');

    var MAX_ROWS = 30;
    var MAX_FIELDS_PER_SETTING = 4;

    var search = {
        records: null,
        loading: false,
        failed: false,
        stale: false,
        rows: [],
        active: -1,
        timer: null
    };

    var $searchInput = $("#setting-quick-search");
    var $searchPanel = $("#setting-search-dropdown");

    function escapeHtml(value) {
        return String(value == null ? "" : value)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

    function escapeRegex(value) {
        return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    // "Parent Notification(s)" -> "parent notification s"
    function normalize(value) {
        var s = String(value == null ? "" : value).toLowerCase();
        if (s.normalize) {
            s = s.normalize("NFD").replace(/[\u0300-\u036f]/g, "");
        }
        return s.replace(/[^a-z0-9]+/g, " ").trim();
    }

    // Loose singular form, so "notifications" finds "Notification(s)".
    function stem(token) {
        if (token.length > 4 && /(s|x|z|ch|sh)es$/.test(token)) return token.slice(0, -2);
        if (token.length > 3 && /[^s]s$/.test(token)) return token.slice(0, -1);
        return token;
    }

    function queryTokens(query) {
        var all = normalize(query).split(" ").filter(Boolean);
        var tokens = all.filter(function (t) { return t.length > 1; });
        if (!tokens.length) tokens = all;
        var seen = {};
        return tokens.filter(function (t) {
            if (seen[t]) return false;
            seen[t] = true;
            return true;
        }).map(stem);
    }

    // A lone character ("s", "(s)") would match nearly every setting.
    function isSearchable(tokens) {
        return tokens.some(function (t) { return t.length > 1; });
    }

    function hasToken(haystack, token) {
        return haystack.indexOf(token) !== -1;
    }

    function hasAll(haystack, tokens) {
        if (!haystack) return false;
        for (var i = 0; i < tokens.length; i++) {
            if (!hasToken(haystack, tokens[i])) return false;
        }
        return true;
    }

    function humanize(name) {
        var s = String(name || "").replace(/_/g, " ").trim();
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    function prepareIndex(records) {
        return (records || []).map(function (r) {
            var categories = r.categories || [];
            return {
                id: String(r.id),
                title: r.title || humanize(r.name),
                categories: categories,
                categoryKey: categories.length ? String(categories[0].key) : "",
                categoryText: categories.map(function (c) { return c.label; }).join(", "),
                n: {
                    title: normalize(r.title),
                    keys: normalize((r.key || "") + " " + (r.name || "")),
                    description: normalize(r.description),
                    categories: normalize(categories.map(function (c) { return c.label; }).join(" "))
                },
                fields: (r.fields || []).map(function (f) {
                    return {
                        name: f.name,
                        label: f.label || humanize(f.name),
                        helpText: f.help_text || "",
                        value: f.value || "",
                        heading: !!f.heading,
                        n: {
                            label: normalize(f.label || humanize(f.name)),
                            name: normalize(f.name),
                            help: normalize(f.help_text),
                            value: normalize(f.value)
                        }
                    };
                })
            };
        });
    }

    function loadIndex() {
        if (search.loading) return;
        search.loading = true;
        $.ajax({
            url: urlSearchIndex,
            type: "GET",
            dataType: "json"
        }).done(function (result) {
            search.records = prepareIndex(result && result.records);
            search.failed = false;
            search.stale = false;
        }).fail(function () {
            if (!search.records) search.failed = true;
        }).always(function () {
            search.loading = false;
            if ($searchInput.is(":focus") && $.trim($searchInput.val())) {
                renderResults();
            }
        });
    }

    // Any saved setting (form save, title/JSON edit) can change what matches.
    $(document).ajaxSuccess(function (event, xhr, options) {
        if (options && String(options.type).toUpperCase() === "POST") {
            search.stale = true;
        }
    });

    // Score how well a field matches; 0 = no match. `titleN` lets a query
    // like "registration parent" match the Parent field of the Registration
    // setting: words found in the setting title need not be in the field.
    function scoreField(field, tokens, phrase, titleN) {
        var best = scoreFieldTokens(field, tokens, phrase);
        if (best.score) return best;

        var rest = tokens.filter(function (t) { return !hasToken(titleN, t); });
        if (rest.length && rest.length < tokens.length) {
            best = scoreFieldTokens(field, rest, "");
            if (best.score) best.score -= 15;
        }
        return best;
    }

    function scoreFieldTokens(field, tokens, phrase) {
        var n = field.n;
        if (phrase && n.label.indexOf(phrase) !== -1) return { score: 100, source: "label" };
        if (hasAll(n.label, tokens)) return { score: 80, source: "label" };
        if (hasAll(n.name, tokens)) return { score: 60, source: "name" };
        if (hasAll(n.help, tokens)) return { score: 40, source: "help" };
        if (hasAll(n.value, tokens)) return { score: 20, source: "value" };
        return { score: 0, source: "" };
    }

    function scoreRecord(record, tokens, phrase) {
        var n = record.n;
        if (phrase && n.title.indexOf(phrase) !== -1) return 90;
        if (hasAll(n.title, tokens)) return 70;
        if (hasAll(n.keys, tokens)) return 50;
        if (hasAll(n.description, tokens)) return 30;
        if (hasAll(n.categories, tokens)) return 15;
        return 0;
    }

    function findMatches(query) {
        var tokens = queryTokens(query);
        if (!isSearchable(tokens) || !search.records) return [];
        var phrase = normalize(query);

        var groups = [];
        search.records.forEach(function (record) {
            var recordScore = scoreRecord(record, tokens, phrase);
            var fields = [];
            record.fields.forEach(function (field) {
                var hit = scoreField(field, tokens, phrase, record.n.title);
                if (hit.score > 0) {
                    fields.push({ field: field, score: hit.score, source: hit.source });
                }
            });
            if (!recordScore && !fields.length) return;

            fields.sort(function (a, b) { return b.score - a.score; });
            var best = recordScore;
            if (fields.length && fields[0].score > best) best = fields[0].score;
            groups.push({
                record: record,
                score: best,
                recordScore: recordScore,
                fields: fields.slice(0, MAX_FIELDS_PER_SETTING),
                moreFields: Math.max(0, fields.length - MAX_FIELDS_PER_SETTING)
            });
        });

        groups.sort(function (a, b) {
            return (b.score - a.score) || a.record.title.localeCompare(b.record.title);
        });
        return groups;
    }

    function highlight(text, tokens) {
        text = String(text || "");
        if (!tokens.length) return escapeHtml(text);
        var pattern = tokens.slice().sort(function (a, b) { return b.length - a.length; })
            .map(escapeRegex).join("|");
        var re = new RegExp("(" + pattern + ")", "gi");
        return text.split(re).map(function (part, i) {
            return i % 2 ? "<mark>" + escapeHtml(part) + "</mark>" : escapeHtml(part);
        }).join("");
    }

    function snippet(text, tokens) {
        text = String(text || "");
        var lower = text.toLowerCase();
        var at = -1;
        tokens.forEach(function (t) {
            var i = lower.indexOf(t);
            if (i !== -1 && (at === -1 || i < at)) at = i;
        });
        if (at === -1) at = 0;
        var start = Math.max(0, at - 40);
        var end = Math.min(text.length, at + 100);
        return (start > 0 ? "\u2026" : "") + text.substring(start, end) + (end < text.length ? "\u2026" : "");
    }

    function pill(fieldHit) {
        if (fieldHit.field.heading) return "<span class='ss-pill ss-pill-section'>Section</span>";
        if (fieldHit.source === "help") return "<span class='ss-pill'>Help text</span>";
        if (fieldHit.source === "value") return "<span class='ss-pill ss-pill-value'>Value</span>";
        return "<span class='ss-pill'>Field</span>";
    }

    function setPanelOpen(open) {
        $searchPanel.toggleClass("d-none", !open);
        $searchInput.attr("aria-expanded", open ? "true" : "false");
        if (!open) {
            $searchInput.removeAttr("aria-activedescendant");
        }
    }

    function showMessage(html) {
        search.rows = [];
        search.active = -1;
        $searchPanel.html("<div class='ss-message'>" + html + "</div>");
        setPanelOpen(true);
    }

    function renderResults() {
        var query = $.trim($searchInput.val());
        $("#setting-search-clear").toggleClass("d-none", !query);

        if (!query) {
            closePanel();
            return;
        }
        if (!search.records) {
            if (search.failed) {
                showMessage("<i class='fa fa-exclamation-triangle'></i> Search is unavailable right now. Reload the page to try again.");
            } else {
                showMessage("<i class='fa fa-spinner fa-spin'></i> Loading settings\u2026");
                loadIndex();
            }
            return;
        }
        if (search.stale) loadIndex();

        var tokens = queryTokens(query);
        if (!isSearchable(tokens)) {
            showMessage("Keep typing to search\u2026");
            return;
        }
        var groups = findMatches(query);
        if (!groups.length) {
            showMessage("No settings match <strong>" + escapeHtml(query) + "</strong>.");
            return;
        }

        var rows = [];
        var html = [];
        // Start on the best hit: the top setting's first field when a field
        // matched better than the setting itself, else the setting.
        var top = groups[0];
        var firstActive = (top.fields.length && top.fields[0].score > top.recordScore) ? 1 : 0;
        for (var g = 0; g < groups.length && rows.length < MAX_ROWS; g++) {
            var group = groups[g];
            var record = group.record;
            html.push("<div class='ss-group'>");

            html.push(
                "<button type='button' class='ss-item ss-setting' role='option' id='ss-opt-" + rows.length + "' data-row='" + rows.length + "'>" +
                "<span><i class='fa fa-cog' aria-hidden='true'></i>" + highlight(record.title, tokens) + "</span>" +
                "<span class='ss-cats'>" + escapeHtml(record.categoryText) + "</span>" +
                "</button>"
            );
            rows.push({ record: record, field: null });

            for (var f = 0; f < group.fields.length && rows.length < MAX_ROWS; f++) {
                var hit = group.fields[f];
                var detail = "";
                if (hit.source === "help") {
                    detail = "<span class='ss-snippet'>" + highlight(snippet(hit.field.helpText, tokens), tokens) + "</span>";
                } else if (hit.source === "value") {
                    detail = "<span class='ss-snippet'>" + highlight(snippet(hit.field.value, tokens), tokens) + "</span>";
                } else if (hit.source === "name") {
                    detail = "<span class='ss-snippet'>" + highlight(hit.field.name, tokens) + "</span>";
                }
                html.push(
                    "<button type='button' class='ss-item ss-field' role='option' id='ss-opt-" + rows.length + "' data-row='" + rows.length + "'>" +
                    "<span class='ss-field-line'><span class='ss-field-label'>" + highlight(hit.field.label, tokens) + "</span>" + pill(hit) + "</span>" +
                    detail +
                    "</button>"
                );
                rows.push({ record: record, field: hit.field });
            }
            if (group.moreFields) {
                html.push("<div class='ss-snippet ss-field' style='padding-bottom:.35rem'>+" + group.moreFields + " more in this setting</div>");
            }
            html.push("</div>");
        }

        var count = groups.length === 1 ? "1 setting" : groups.length + " settings";
        html.push("<div class='ss-footer'>" + count + " \u00b7 \u2191\u2193 to move \u00b7 Enter to open \u00b7 Esc to close</div>");

        search.rows = rows;
        $searchPanel.html(html.join(""));
        setPanelOpen(true);
        setActiveRow(firstActive);
    }

    function setActiveRow(index) {
        var $items = $searchPanel.find(".ss-item");
        if (!$items.length) return;
        if (index < 0) index = $items.length - 1;
        if (index >= $items.length) index = 0;
        search.active = index;
        $items.removeClass("ss-active").attr("aria-selected", "false");
        var $item = $items.eq(index).addClass("ss-active").attr("aria-selected", "true");
        $searchInput.attr("aria-activedescendant", $item.attr("id"));

        var panel = $searchPanel[0];
        var el = $item[0];
        if (el.offsetTop < panel.scrollTop) {
            panel.scrollTop = el.offsetTop;
        } else if (el.offsetTop + el.offsetHeight > panel.scrollTop + panel.clientHeight) {
            panel.scrollTop = el.offsetTop + el.offsetHeight - panel.clientHeight;
        }
    }

    function closePanel() {
        search.rows = [];
        search.active = -1;
        $searchPanel.empty();
        setPanelOpen(false);
    }

    function clearSearch() {
        $searchInput.val("");
        $("#setting-search-clear").addClass("d-none");
        closePanel();
    }

    // Opens a setting the same way clicking its category and then its title
    // does: list the category's settings, mark this one active, load its form.
    function openSetting(categoryKey, reportId, done) {
        $("#report-category li").removeClass("active");
        $.blockUI();

        function loadDetails() {
            $.ajax({
                url: urlRecordDetails,
                type: "GET",
                dataType: "json",
                data: { report_id: reportId }
            }).done(function (response) {
                $.unblockUI();
                if (response && response.status === "success") {
                    report_id = reportId;
                    $("#cepm-report-container").html(response.report);
                    $(".dateinput").datepicker();
                    $('.dateinput').mask('00/00/0000');
                    if (typeof done === "function") done();
                } else {
                    swal("Unable to open setting", (response && response.message) || "", "warning");
                }
            }).fail(function () {
                $.unblockUI();
                swal("Unable to open setting", "Please try again.", "warning");
            });
        }

        if (!categoryKey) {
            loadDetails();
            return;
        }

        $("#report-category li").filter(function () {
            return String($(this).attr("category")) === categoryKey;
        }).addClass("active");

        $.ajax({
            url: urlRecordsInCategory,
            type: "GET",
            dataType: "json",
            data: { category: categoryKey }
        }).done(function (result) {
            var $list = $("ul#report-list").html("");
            (result && result.records || []).forEach(function (report) {
                $("<li>").attr("report_id", report.id).text(report.title).appendTo($list);
            });
            $list.children("li").filter(function () {
                return String($(this).attr("report_id")) === reportId;
            }).addClass("active");
        }).always(loadDetails);
    }

    function findTarget(fieldName) {
        var $container = $("#cepm-report-container");
        if (fieldName) {
            var byId = document.getElementById("div_id_" + fieldName);
            if (byId && $.contains($container[0], byId)) return $(byId);

            var $input = $container.find("[name]").filter(function () {
                return this.name === fieldName;
            }).first();
            if ($input.length) {
                var $group = $input.closest(".form-group");
                return $group.length ? $group : $input;
            }
        }
        return $container.find("#setting-title");
    }

    function revealTarget(fieldName) {
        var $target = findTarget(fieldName);
        if (!$target.length) return;

        var userScrolled = false;
        $(window).off(".settingSearchJump").one("wheel.settingSearchJump touchmove.settingSearchJump", function () {
            userScrolled = true;
        });

        function scrollToTarget() {
            var offset = $target.offset();
            if (!offset) return;
            $("html, body").stop(true).animate({ scrollTop: Math.max(0, offset.top - 140) }, 350);
        }

        // Let the inserted form lay out, then scroll once. Editors that load
        // late can push the target down; correct once, unless the user has
        // started scrolling themselves.
        setTimeout(function () {
            scrollToTarget();

            $target.removeClass("setting-search-flash");
            void $target[0].offsetWidth;
            $target.addClass("setting-search-flash");
            setTimeout(function () { $target.removeClass("setting-search-flash"); }, 1700);

            var $control = $target.is(":input") ? $target : $target.find(
                "input[type='text'], input[type='email'], input[type='number'], input[type='url'], " +
                "input[type='search'], input:not([type]), textarea, select"
            ).filter(":visible").first();
            if ($control.length) {
                try { $control[0].focus({ preventScroll: true }); } catch (e) {}
            }
        }, 100);

        setTimeout(function () {
            $(window).off(".settingSearchJump");
            var offset = $target.offset();
            if (userScrolled || !offset) return;
            if (Math.abs($(window).scrollTop() - Math.max(0, offset.top - 140)) > 80) {
                scrollToTarget();
            }
        }, 900);
    }

    function openRow(index) {
        var row = search.rows[index];
        if (!row) return;
        closePanel();
        $searchInput.blur();
        var fieldName = row.field ? row.field.name : "";
        openSetting(row.record.categoryKey, row.record.id, function () {
            revealTarget(fieldName);
        });
    }

    $(document).on("click", "#report-category li", function () {
        $("#report-category li").removeClass("active");

        var obj = this;
        $(this)
            .addClass("active")
            .addClass("processing");

        $.blockUI();
        $.ajax({
            url: urlRecordsInCategory,
            type: 'GET',
            data: "category=" + $(this).attr("category"),
            success: function (result) {
                $.unblockUI();
                $("ul#report-list").html("");
                if (result.records.length <= 0) {
                    $("ul#report-list").append("<li>None found</li>");
                } else {
                    result.records.forEach(function (report) {
                        $("ul#report-list").append(
                            "<li report_id='" + report.id + "'>" + report.title + "</li>"
                        );
                    });
                    $(obj).removeClass("processing");

                    $("#report-list li").first().trigger("click");
                }
            }
        });

        if (event.preventDefault) event.preventDefault();
        else event.returnValue = false;
    });

    $(document).on('submit', 'form', function () {
        var form = $('form');

        if ($("input, select, textarea").hasClass('is-invalid'))
            $("input, select, textarea").removeClass('is-invalid');

        if ($("input, select, textarea").next('p').length)
            $("input, select, textarea").nextAll('p').empty();

        $.blockUI();

        $.post({
            url: urlRunRecordBase + '/' + report_id,
            data: $(form).serialize(),
            error: function (xhr, status, errorThrown) {
                $.unblockUI();
                var errors = $.parseJSON(xhr.responseJSON.errors);

                var span = document.createElement('span');
                span.innerHTML = xhr.responseJSON.message;

                var first_element = '';
                for (var name in errors) {
                    for (var i in errors[name]) {
                        var $input = $("[name='" + name + "']");
                        $input.addClass('is-invalid');
                        $input.after("<p class='invalid-feedback'><strong class=''>" + errors[name][i].message + "</strong></p>");
                    }

                    if (name == '__all__') {
                        span.innerHTML += "<br><br>" + errors[name][0].message;
                    }

                    if (first_element == '')
                        $input.focus();
                    else {
                        first_element = '-';
                    }
                }

                swal({
                    title: xhr.responseJSON.message,
                    content: span,
                    icon: 'warning'
                });
            },
            success: function (result) {
                $.unblockUI();
                inputsChanged = false;

                if ($.fn.DataTable.isDataTable('#history-table')) {
                    $('#history-table').DataTable().ajax.reload();
                }

                swal(
                    "Success",
                    result.message,
                    'success'
                );
            }
        });
        return false;
    });

    $(document).on("click", "#report-list li", function () {
        var obj = this;

        $("#report-list li").removeClass("active");
        $(this)
            .addClass("active")
            .addClass("processing");
        report_id = $(this).attr("report_id");

        $.blockUI();
        $.ajax({
            url: urlRecordDetails,
            type: 'GET',
            data: "report_id=" + $(this).attr("report_id"),
            success: function (result) {
                $.unblockUI();
                if (result.status == 'success') {
                    $(obj).removeClass("processing");
                    $("#cepm-report-container").html(result.report);

                    $(".dateinput").datepicker();
                    $('.dateinput').mask('00/00/0000');
                } else {
                    alert(result.message);
                }
            }
        });

        if (event.preventDefault) event.preventDefault();
        else event.returnValue = false;
    });


    $(document).on("focus", "#setting-quick-search", function () {
        if (!search.records || search.stale) loadIndex();
        if ($.trim($(this).val())) renderResults();
    });

    $(document).on("input", "#setting-quick-search", function () {
        clearTimeout(search.timer);
        search.timer = setTimeout(renderResults, 80);
    });

    $(document).on("keydown", "#setting-quick-search", function (e) {
        var open = !$searchPanel.hasClass("d-none");
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            if (!open) {
                renderResults();
                return;
            }
            setActiveRow(search.active + (e.key === "ArrowDown" ? 1 : -1));
        } else if (e.key === "Enter") {
            e.preventDefault();
            clearTimeout(search.timer);
            if (!open || !search.rows.length) renderResults();
            if (search.rows.length) openRow(search.active < 0 ? 0 : search.active);
        } else if (e.key === "Escape") {
            e.preventDefault();
            if (open) closePanel();
            else clearSearch();
        }
    });

    $(document).on("mousedown", "#setting-search-dropdown .ss-item", function (e) {
        // Keep focus in the input until the click lands.
        e.preventDefault();
    });

    $(document).on("click", "#setting-search-dropdown .ss-item", function () {
        openRow(parseInt($(this).attr("data-row"), 10));
    });

    $(document).on("mousemove", "#setting-search-dropdown .ss-item", function () {
        var index = $searchPanel.find(".ss-item").index(this);
        if (index !== search.active) setActiveRow(index);
    });

    $(document).on("click", "#setting-search-clear", function () {
        clearSearch();
        $searchInput.trigger("focus");
    });

    // Older copies of index.html still have a Search button.
    $(document).on("click", "#btn-setting-quick-search", function () {
        $searchInput.trigger("focus");
        renderResults();
    });

    $(document).on("mousedown", function (e) {
        if (!$(e.target).closest(".setting-search-box, #setting-search-dropdown, #setting-quick-search").length) {
            if (!$searchPanel.hasClass("d-none")) closePanel();
        }
    });

    // "/" jumps to the search box from anywhere outside a text field.
    $(document).on("keydown", function (e) {
        if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
        var el = e.target;
        if (el && (/^(input|textarea|select)$/i.test(el.tagName) || el.isContentEditable)) return;
        if (!$searchInput.length) return;
        e.preventDefault();
        $searchInput.trigger("focus").select();
    });

})(jQuery);
