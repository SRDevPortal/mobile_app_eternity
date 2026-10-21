frappe.ui.form.on("Mobile App Brand", {
    refresh(frm) {
        if (!frm.is_new() && frappe.user.has_role("System Manager")) {
            frm.add_custom_button(__("Refresh record brands"), async () => {
                await frappe.call({method: "mobile_app.brand.refresh_record_brands", freeze: true,
                    freeze_message: __("Updating app brand labels...")});
                frappe.show_alert({message: __("App brand labels updated"), indicator: "green"});
            });
        }
    }
});
