frappe.ui.form.on("Mobile App Brand", {
    refresh(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__("QuickLink Conversations"), () => {
                frappe.set_route("List", "Mobile App QuickLink Conversation", {brand: frm.doc.name});
            });
        }
        if (!frm.is_new() && frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Refresh record brands"), async () => {
                const response = await frappe.call({
                    method: "mobile_app.brand.refresh_record_brands",
                    freeze: true,
                    freeze_message: __("Starting background update...")
                });
                frappe.show_alert({
                    message: __("Brand update queued or already running. Older records will update in batches."),
                    indicator: "blue"
                });
                frappe.set_route("Form", "Mobile App Brand Update", response.message.name);
            });
        }
    }
});
