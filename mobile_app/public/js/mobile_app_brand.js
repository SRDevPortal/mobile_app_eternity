/* One brand preference for workspace navigation and the appointment calendar. */
frappe.provide("mobile_app.brand");
(() => {
    let values = ["", ...(frappe.boot?.mobile_app_brands || []), "Unclassified"];
    let pending;
    const escape = value => String(value).replace(/[&<>"\']/g, c => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "\'":"&#39;"}[c]));
    mobile_app.brand.refresh = () => {
        if (!pending) pending = frappe.xcall("mobile_app.brand.get_brands").then(names => {
            values = ["", ...names, "Unclassified"];
            if (current !== undefined && !values.includes(current)) mobile_app.brand.set("");
        }).finally(() => { pending = null; });
        return pending;
    };
    const key = () => `mobile-app:brand:${frappe.session.user}`;
    let current;
    mobile_app.brand.get = () => {
        if (current !== undefined) return current;
        try { current = sessionStorage.getItem(key()); } catch (_) {}
        return current = values.includes(current) ? current : "";
    };
    mobile_app.brand.set = value => {
        current = values.includes(value) ? value : "";
        try { sessionStorage.setItem(key(), current); } catch (_) {}
    };
    mobile_app.brand.options = () => values.map(value => `<option value="${escape(value)}">${escape(value || "All brands")}</option>`).join("");
    mobile_app.brand.filters = (value = mobile_app.brand.get()) => value === "Unclassified"
        ? {custom_app_brand: ["is", "not set"]} : value ? {custom_app_brand: value} : {};
    mobile_app.brand.matches = (value, brand = mobile_app.brand.get()) => !brand || (brand === "Unclassified" ? !value : value === brand);
    mobile_app.brand.open = route => {
        frappe.route_options = route[0] === "List" ? (mobile_app.brand.get() ? mobile_app.brand.filters() : {name: ["is", "set"]}) : null;
        frappe.set_route(...route);
    };
})();
