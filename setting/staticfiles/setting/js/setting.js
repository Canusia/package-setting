(function ($) {
    function getConfig() {
        return $('#setting-detail-config');
    }

    $(document).on('shown.bs.tab', 'a[href="#change-log"]', function () {
        if ($.fn.DataTable.isDataTable('#history-table')) return;

        var settingKey = getConfig().data('setting-key');

        $("#history-table").DataTable({
            order: [[0, 'desc']],
            searching: false,
            paging: true,
            pageLength: 10,
            ajax: {
                url: 'setting_history/',
                data: function (d) {
                    d.setting_key = settingKey;
                }
            },
            columns: [
                { data: 'history_date' },
                { data: 'history_user' },
                {
                    data: 'history_type',
                    render: function (data) {
                        if (data === 'Created') {
                            return '<span class="badge badge-success">Created</span>';
                        } else if (data === 'Changed') {
                            return '<span class="badge badge-warning">Changed</span>';
                        } else if (data === 'Deleted') {
                            return '<span class="badge badge-danger">Deleted</span>';
                        }
                        return data;
                    }
                },
                {
                    data: 'value',
                    render: function (data) {
                        var preview = data.length > 80 ? data.substring(0, 80) + '...' : data;
                        return '<code class="history-value-preview" style="cursor:pointer; font-size:0.85em;" title="Click to view full JSON">' +
                            $('<span>').text(preview).html() + '</code>';
                    }
                }
            ]
        });
    });

    $(document).on('click', '.history-value-preview', function () {
        var row = $(this).closest('tr');
        var table = $("#history-table").DataTable();
        var rowData = table.row(row).data();
        if (rowData) {
            swal({ title: 'Setting Value', text: rowData.value, customClass: 'swal-wide' });
        }
    });

    $(document).on('click', '#btn-copy-json', function () {
        var jsonText = $('#setting-json-display').text();
        navigator.clipboard.writeText(jsonText).then(function () {
            swal('Copied', 'JSON copied to clipboard', 'success');
        }, function () {
            swal('Error', 'Failed to copy to clipboard', 'error');
        });
    });

    $(document).on('click', '#btn-edit-setting', function () {
        if (!getConfig().data('is-superuser')) return;
        $('#description-display').hide();
        $('#description-edit').show();
    });

    $(document).on('click', '#btn-cancel-edit', function () {
        $('#description-edit').hide();
        $('#description-display').show();
    });

    $(document).on('click', '#btn-save-setting', function () {
        if (!getConfig().data('is-superuser')) return;

        var recordId = getConfig().data('record-id');
        var title = $('#edit-setting-title').val().trim();
        var description = $('#edit-setting-description').val().trim();
        var settingJson = $('#edit-setting-json').val().trim();
        var csrftoken = $('[name=csrfmiddlewaretoken]').val();

        if (!title) {
            swal('Error', 'Title is required', 'error');
            return;
        }

        if (settingJson) {
            try {
                JSON.parse(settingJson);
            } catch (e) {
                swal('Error', 'Invalid JSON format', 'error');
                return;
            }
        }

        $.post({
            url: 'update_setting/',
            data: {
                record_id: recordId,
                title: title,
                description: description,
                setting_value: settingJson,
                csrfmiddlewaretoken: csrftoken
            },
            success: function (response) {
                $('#setting-title').text(title);
                $('#report-list li.active').text(title);

                var displayHtml = (description || '-');
                displayHtml += '<hr><button type="button" class="btn btn-sm btn-outline-secondary" id="btn-edit-setting">';
                displayHtml += '<i class="fa fa-pencil"></i> Edit</button>';
                $('#description-display').html(displayHtml);

                if (settingJson) {
                    try {
                        var formatted = JSON.stringify(JSON.parse(settingJson), null, 2);
                        $('#setting-json-display').text(formatted);
                        $('#edit-setting-json').val(formatted);
                    } catch (e) {}
                }

                $('#description-edit').hide();
                $('#description-display').show();

                if ($.fn.DataTable.isDataTable('#history-table')) {
                    $("#history-table").DataTable().ajax.reload();
                }

                swal('Success', response.message, 'success');
            },
            error: function (xhr) {
                var msg = 'Failed to update setting';
                if (xhr.responseJSON && xhr.responseJSON.message) {
                    msg = xhr.responseJSON.message;
                }
                swal('Error', msg, 'error');
            }
        });
    });
})(jQuery);
