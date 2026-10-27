frappe.ui.form.on('Mobile App QuickLink Conversation', {
    refresh(frm) {
        if (frm.is_new()) return;
        const wrapper = frm.fields_dict.chat_view.$wrapper.empty();
        const refresh = async () => {
            const {message: data} = await frappe.call({method: 'mobile_app.api.quicklink.desk', args: {conversation: frm.doc.name}});
            wrapper.empty();
            $('<p>').text(__('Recent messages')).appendTo(wrapper);
            for (const row of data.messages) {
                const item = $('<div class="mb-3 p-3 border rounded">').appendTo(wrapper);
                $('<strong>').text(row.sender_type + ' · ' + row.created_at).appendTo(item);
                $('<div>').css('white-space', 'pre-wrap').text(row.message).appendTo(item);
            }
            if (data.support_ticket) {
                $('<button class="btn btn-default btn-sm mb-3">').text(__('Open Support Ticket')).on('click', () =>
                    frappe.set_route('Form', 'Support Ticket', data.support_ticket)).appendTo(wrapper);
            }
            if (data.mode === 'Human') {
                const input = $('<textarea class="form-control mb-2" maxlength="4000">').attr('placeholder', __('Reply to customer')).appendTo(wrapper);
                const send = $('<button class="btn btn-primary btn-sm">').text(__('Send reply')).appendTo(wrapper);
                send.on('click', async () => {
                    if (!input.val().trim()) return;
                    send.prop('disabled', true);
                    try {
                        await frappe.call({method: 'mobile_app.api.quicklink.desk', args: {conversation: frm.doc.name, message: input.val()}});
                        await refresh();
                    } finally {send.prop('disabled', false);}
                });
            }
        };
        frm.add_custom_button(__('Refresh Chat'), refresh);
        refresh();
    }
});
