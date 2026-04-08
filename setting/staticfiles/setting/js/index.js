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
    var searchIndex = [];
    var searchIndexLoaded = false;
    var loadingSearchIndex = false;

    function normalizeText(value) {
        return (value || '').toString().trim().toLowerCase();
    }

    function clearSearchDropdown() {
        $("#setting-search-dropdown").empty().addClass("d-none");
    }

    function focusBestMatchingField(searchTerm) {
        var term = normalizeText(searchTerm);
        var $container = $("#cepm-report-container");

        var $allFields = $container.find("textarea, input[type='text'], input[type='email'], input[type='number'], input[type='search'], select");
        if (!$allFields.length) return false;

        function scoreField($field) {
            var s = 0;
            var val = normalizeText($field.val());
            if (term && val.indexOf(term) !== -1) s += 100;

            var $group = $field.closest(".form-group");
            if (!$group.length) {
                $group = $field.closest(".form-row, .mb-3");
            }
            var groupText = normalizeText($group.text());
            if (term && groupText.indexOf(term) !== -1) s += 50;

            var fieldId = $field.attr("id") || "";
            var labelText = "";
            if (fieldId) {
                labelText = $("label[for='" + fieldId + "']").first().text();
            }
            var meta = normalizeText(
                ($field.attr("name") || "") + " " + fieldId + " " + labelText + " " + ($field.attr("placeholder") || "")
            );
            if (term && meta.indexOf(term) !== -1) s += 25;

            return s;
        }

        var $best = null;
        var bestScore = -1;
        $allFields.each(function () {
            var sc = scoreField($(this));
            if (sc > bestScore) {
                bestScore = sc;
                $best = $(this);
            }
        });

        if (!$best || bestScore < 0) {
            $best = $allFields.filter("textarea").first();
        }
        if (!$best.length) {
            $best = $allFields.first();
        }

        function scrollAndHighlight($el) {
            if (!$el || !$el.length) return;
            var $scrollTo = $el.closest(".form-group");
            if (!$scrollTo.length) {
                $scrollTo = $el;
            }
            if ($scrollTo.offset()) {
                var top = $scrollTo.offset().top - 140;
                $("html, body").stop(true).animate({ scrollTop: Math.max(0, top) }, 400);
            }
            try {
                $el.trigger("focus");
            } catch (e) {}
            $el.addClass("border-primary");
            setTimeout(function () {
                $el.removeClass("border-primary");
            }, 2000);
        }

        function finishFocus() {
            var $target = $best;
            if (!$target.is(":visible")) {
                $target = $allFields.filter(":visible").first();
            }
            if ($target && $target.length) {
                scrollAndHighlight($target);
                return true;
            }
            return false;
        }

        if ($best.closest("#description-edit").length && $("#description-edit").is(":hidden") && $("#btn-edit-setting").length) {
            $("#btn-edit-setting").trigger("click");
            setTimeout(function () {
                scrollAndHighlight($best);
            }, 350);
            return true;
        }

        var $pane = $best.closest(".tab-pane");
        if ($pane.length && !$pane.hasClass("active")) {
            var pid = $pane.attr("id");
            if (pid) {
                $('a[href="#' + pid + '"]').tab("show");
            }
            setTimeout(function () {
                scrollAndHighlight($best);
            }, 350);
            return true;
        }

        return finishFocus();
    }

    function waitForReportAndFocus(searchTerm) {
        var tries = 0;
        var maxTries = 60;
        var timer = setInterval(function () {
            tries += 1;
            var $container = $("#cepm-report-container");
            var hasFormFields = $container.find("textarea, input[type='text'], input[type='email'], input[type='number'], select").length > 0;
            var hasTitle = $container.find("#setting-title").length > 0;

            if (hasFormFields || hasTitle) {
                if (focusBestMatchingField(searchTerm)) {
                    clearInterval(timer);
                    [200, 500, 1000].forEach(function (delay) {
                        setTimeout(function () {
                            focusBestMatchingField(searchTerm);
                        }, delay);
                    });
                }
            }
            if (tries >= maxTries) {
                clearInterval(timer);
                focusBestMatchingField(searchTerm);
            }
        }, 100);
    }

    function buildSearchIndex(onComplete) {
        if (searchIndexLoaded || loadingSearchIndex) {
            if (typeof onComplete === "function") onComplete();
            return;
        }

        loadingSearchIndex = true;
        searchIndex = [];

        var categories = [];
        $("#report-category li").each(function () {
            categories.push({
                key: $(this).attr("category"),
                label: $(this).text().trim()
            });
        });

        if (!categories.length) {
            loadingSearchIndex = false;
            searchIndexLoaded = true;
            if (typeof onComplete === "function") onComplete();
            return;
        }

        var requests = categories.map(function (cat) {
            return $.ajax({
                url: urlRecordsInCategory,
                type: "GET",
                dataType: "json",
                data: { category: cat.key }
            }).done(function (result) {
                var records = (result && result.records) ? result.records : [];
                records.forEach(function (report) {
                    searchIndex.push({
                        category: cat.key,
                        categoryLabel: cat.label,
                        reportId: String(report.id),
                        reportTitle: report.title || ""
                    });
                });
            });
        });

        $.when.apply($, requests).always(function () {
            loadingSearchIndex = false;
            searchIndexLoaded = true;
            if (typeof onComplete === "function") onComplete();
        });
    }

    function runSettingSearch() {
        var term = $("#setting-quick-search").val();
        var normalizedTerm = normalizeText(term);

        if (!normalizedTerm) {
            swal("Search", "Enter text to search settings.", "warning");
            return;
        }

        function escapeHtml(value) {
            return $("<div>").text(value || "").html();
        }

        function stripHtml(value) {
            return $("<div>").html(value || "").text();
        }

        function buildSnippetFromText(text, searchTerm) {
            var raw = (text || "").replace(/\s+/g, " ").trim();
            if (!raw) return "No preview available.";

            var lower = raw.toLowerCase();
            var idx = lower.indexOf(searchTerm);
            if (idx === -1) {
                return raw.length > 180 ? raw.substring(0, 177) + "..." : raw;
            }

            var start = Math.max(0, idx - 80);
            var end = Math.min(raw.length, idx + searchTerm.length + 80);
            var snippet = raw.substring(start, end);
            if (start > 0) snippet = "..." + snippet;
            if (end < raw.length) snippet = snippet + "...";
            return snippet;
        }

        function renderSearchDropdown(matches, searchTerm) {
            var dropdownHtml = matches.map(function (match, index) {
                return (
                    "<button type='button' class='list-group-item list-group-item-action text-left setting-search-choice' data-index='" + index + "'>" +
                    "<div><strong>" + escapeHtml(match.reportTitle) + "</strong></div>" +
                    "<div class='text-muted small'>" + escapeHtml(match.categoryLabel) + " • " + escapeHtml(match.matchTypeLabel) + "</div>" +
                    "<div class='small mt-1'>" + escapeHtml(match.snippet || "") + "</div>" +
                    "</button>"
                );
            }).join("");

            var header = "<div class='list-group-item bg-light small text-muted'>Multiple matches for \"" + escapeHtml(searchTerm) + "\" (" + matches.length + ")</div>";
            $("#setting-search-dropdown").html(header + dropdownHtml).removeClass("d-none");

            $(document).off("click.settingSearchDropdown").on("click.settingSearchDropdown", function (e) {
                if (!$(e.target).closest("#setting-search-dropdown, #setting-quick-search, #btn-setting-quick-search").length) {
                    clearSearchDropdown();
                    $(document).off("click.settingSearchDropdown");
                }
            });

            $("#setting-search-dropdown").off("click", ".setting-search-choice");
            $("#setting-search-dropdown").on("click", ".setting-search-choice", function () {
                var idx = parseInt($(this).attr("data-index"), 10);
                var selected = matches[idx];
                if (!selected) return;
                clearSearchDropdown();
                openMatch(selected, searchTerm);
            });
        }

        function openMatch(match, searchTerm) {
            $("#report-category li").removeClass("active");
            var $cat = $("#report-category li[category='" + match.category + "']");
            if ($cat.length) {
                $cat.addClass("active");
            }

            $.blockUI();
            $.ajax({
                url: urlRecordsInCategory,
                type: "GET",
                dataType: "json",
                data: { category: match.category },
                success: function (result) {
                    $("ul#report-list").html("");
                    if (result.records && result.records.length) {
                        result.records.forEach(function (report) {
                            $("ul#report-list").append(
                                "<li report_id='" + report.id + "'>" + escapeHtml(report.title) + "</li>"
                            );
                        });
                    }
                    $("#report-list li").removeClass("active");
                    var $li = $("#report-list li[report_id='" + match.reportId + "']");
                    $li.addClass("active");
                    report_id = match.reportId;

                    $.ajax({
                        url: urlRecordDetails,
                        type: "GET",
                        dataType: "json",
                        data: { report_id: match.reportId },
                        success: function (response) {
                            $.unblockUI();
                            if (response.status === "success") {
                                $("#cepm-report-container").html(response.report);
                                $(".dateinput").datepicker();
                                $('.dateinput').mask('00/00/0000');
                                waitForReportAndFocus(searchTerm);
                            }
                        },
                        error: function () {
                            $.unblockUI();
                        }
                    });
                },
                error: function () {
                    $.unblockUI();
                }
            });
        }

        function findInRecordContent(done) {
            if (!searchIndex.length) {
                done([]);
                return;
            }

            var results = [];
            var remaining = searchIndex.length;

            searchIndex.forEach(function (item) {
                $.ajax({
                    url: urlRecordDetails,
                    type: "GET",
                    dataType: "json",
                    data: { report_id: item.reportId }
                }).done(function (result) {
                    var html = result && result.report ? result.report : "";
                    var plain = normalizeText(stripHtml(html));
                    if (result && result.status === "success" && plain.indexOf(normalizedTerm) !== -1) {
                        results.push({
                            category: item.category,
                            categoryLabel: item.categoryLabel,
                            reportId: item.reportId,
                            reportTitle: item.reportTitle,
                            matchType: "content",
                            matchTypeLabel: "content",
                            snippet: buildSnippetFromText(stripHtml(html), normalizedTerm),
                            uiTargetType: "page",
                            uiTargetSelector: "",
                            uiRoute: "",
                            previewImageUrl: "",
                            previewStatus: "resolving"
                        });
                    }
                }).always(function () {
                    if (--remaining === 0) done(results);
                });
            });
        }

        function collectMatches() {
            var matches = [];
            searchIndex.forEach(function (item) {
                var titleHit = normalizeText(item.reportTitle).indexOf(normalizedTerm) !== -1;
                var categoryHit = normalizeText(item.categoryLabel).indexOf(normalizedTerm) !== -1;

                if (titleHit || categoryHit) {
                    matches.push({
                        category: item.category,
                        categoryLabel: item.categoryLabel,
                        reportId: item.reportId,
                        reportTitle: item.reportTitle,
                        matchType: titleHit ? "title" : "category",
                        matchTypeLabel: titleHit ? "title" : "category",
                        snippet: titleHit
                            ? "Matched in setting title."
                            : "Matched in category.",
                        uiTargetType: "page",
                        uiTargetSelector: "",
                        uiRoute: "",
                        previewImageUrl: "",
                        previewStatus: "resolving"
                    });
                }
            });
            return matches;
        }

        function continueSearch() {
            var initialMatches = collectMatches();
            var uniqueMap = {};
            initialMatches.forEach(function (m) {
                uniqueMap[m.reportId] = m;
            });

            if (Object.keys(uniqueMap).length === 1) {
                clearSearchDropdown();
                openMatch(initialMatches[0], normalizedTerm);
                return;
            }

            $.blockUI();
            findInRecordContent(function (contentMatches) {
                $.unblockUI();
                (contentMatches || []).forEach(function (m) {
                    if (!uniqueMap[m.reportId]) {
                        uniqueMap[m.reportId] = m;
                    }
                });

                var allMatches = Object.keys(uniqueMap).map(function (key) {
                    return uniqueMap[key];
                });

                if (!allMatches.length) {
                    clearSearchDropdown();
                    swal("No match found", "No settings matched your search.", "warning");
                    return;
                }

                if (allMatches.length === 1) {
                    clearSearchDropdown();
                    openMatch(allMatches[0], normalizedTerm);
                    return;
                }

                renderSearchDropdown(allMatches, term);
            });
        }

        if (!searchIndexLoaded) {
            $.blockUI();
            buildSearchIndex(function () {
                $.unblockUI();
                continueSearch();
            });
        } else {
            continueSearch();
        }
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

    $(document).on("click", "#btn-setting-quick-search", function () {
        runSettingSearch();
    });

    $(document).on("keydown", "#setting-quick-search", function (e) {
        if (e.key === "Enter") {
            e.preventDefault();
            runSettingSearch();
        }
    });

    $(document).on("input", "#setting-quick-search", function () {
        if (!$(this).val().trim()) {
            clearSearchDropdown();
        }
    });

})(jQuery);
