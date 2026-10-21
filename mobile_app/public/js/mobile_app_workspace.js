/* Mobile App workspace dashboard */

(function () {
	const WORKSPACE_LABEL = "Mobile App";
	const DASHBOARD_CLASS = "ma-mobile-dashboard-cards";
	const DASHBOARD_SHELL_CLASS = "ma-mobile-dashboard-shell";
	const ACTIVE_BODY_CLASS = "ma-mobile-dashboard-active";
	const STYLE_ID = "ma-mobile-dashboard-runtime-style";
	let render_timer = null;
	let is_rendering = false;
	let $dashboard = null;

	const CARDS = [
		{
			key: "users",
			title: "Mobile App User",
			doctype: "Mobile App User",
			accent: "green",
			icon: "user",
			footer_label: "View users",
			footer_value: "Open",
			route: ["List", "Mobile App User"],
		},
		{
			key: "appointments",
			title: "Mobile App Appointments",
			doctype: "Mobile App Appointment",
			accent: "blue",
			icon: "appointment",
			footer_label: "View appointments",
			footer_value: "Open",
			route: ["List", "Mobile App Appointment"],
		},
		{
			key: "tickets",
			title: "Support Tickets",
			doctype: "App Support Ticket",
			accent: "purple",
			icon: "ticket",
			footer_label: "Tickets and chats",
			footer_value: "Open",
			route: ["List", "App Support Ticket"],
		},
		{
			key: "portal",
			title: "Appointment Calendar",
			accent: "orange",
			icon: "play",
			footer_label: "View clinic schedule",
			footer_value: "Open",
			route: ["doctor-clinical"],
		},
	];

    let related_links = [];
    async function refresh_related_links() {
        const $links = $dashboard.find(".ma-related-links");
        try {
            related_links = await frappe.xcall("mobile_app.workspace.get_related_links");
            $links.html(related_links.map(row => `
                <a class="widget shortcut-widget-box ma-related-shortcut" href="/app/${escape_html(frappe.router.slug(row.doctype))}"
                   data-related-doctype="${escape_html(row.doctype)}"
                   title="${escape_html(__(row.brand_filtered ? "Uses the selected app brand" : "All mobile apps"))}">
                    <div class="widget-head"><div class="widget-label"><div class="widget-title">
                        <span class="ellipsis">${escape_html(__(row.doctype))}</span>
                    </div></div><div class="widget-control">${frappe.utils.icon("es-line-arrow-up-right", "xs", "", "", "ml-2")}</div></div>
                </a>`).join(""));
        } catch (_) {
            $links.html(`<p role="alert">${escape_html(__("Unable to load related records."))} <button type="button" class="btn btn-link ma-related-retry">${escape_html(__("Retry"))}</button></p>`);
        }
    }

	function escape_html(value) {
		return frappe.utils.escape_html(String(value ?? ""));
	}

	function compact_text(value) {
		return String(value || "").replace(/\s+/g, "");
	}

	function current_route_parts() {
		return (frappe.get_route?.() || []).map((part) =>
			decodeURIComponent(String(part)).toLowerCase()
		);
	}

	function is_mobile_workspace() {
		const route = current_route_parts();
		const route_is_workspace = route.some(
			(part) => part === "workspaces" || part === "workspace"
		);
		const route_is_mobile_workspace = route.length === 1 && route[0] === "mobile-app";
		const route_match =
			route_is_mobile_workspace ||
			(route_is_workspace && route.some((part) => part === WORKSPACE_LABEL.toLowerCase()));

		return route_match;
	}

	function inject_runtime_style() {
		if (document.getElementById(STYLE_ID)) return;

		const style = document.createElement("style");
		style.id = STYLE_ID;
		style.textContent = `
			.ma-brand-toolbar { display:flex; align-items:center; gap:16px; flex-wrap:wrap; margin-bottom:20px; }
            .ma-brand-toolbar label { margin:0; font-weight:600; }
            .ma-brand-toolbar select { min-width:190px; }
            .ma-brand-note { color:var(--text-muted); margin-bottom:20px; }
            .ma-related-links { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px 24px; padding:0 0 20px; }
            .ma-related-links a { text-decoration:none; }
            .ma-related-links a:focus-visible { outline:2px solid var(--primary); outline-offset:3px; }
            @media (max-width:1199px) { .ma-related-links { grid-template-columns:repeat(2,minmax(0,1fr)); } }
            @media (max-width:575px) { .ma-related-links { grid-template-columns:1fr; } }
			.${DASHBOARD_SHELL_CLASS} { width: 100%; max-width: none; margin: 0 0 28px; }
			.${DASHBOARD_CLASS} { width: 100%; max-width: none; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 24px; margin: 0 0 28px; }
			.ma-mobile-dashboard-card { position: relative; min-height: 144px; border: 0; border-radius: 20px; padding: 22px; gap: 22px; display: flex; flex-direction: column; justify-content: space-between; color: #fff; text-align: left; overflow: hidden; cursor: pointer; box-shadow: 0 8px 20px rgba(15, 23, 42, 0.10); transition: transform .25s ease, box-shadow .25s ease; }
			.ma-mobile-dashboard-card:hover { transform: translateY(-2px); box-shadow: 0 12px 24px rgba(15, 23, 42, 0.14); }
			.ma-support-destinations { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; padding: 8px 0; }
			.ma-mobile-dashboard-card:focus-visible { outline: 3px solid #111827; outline-offset: 3px; }
			@media (max-width: 575px) { .ma-support-destinations { grid-template-columns: 1fr; } }
			.ma-mobile-dashboard-card--green { background: linear-gradient(135deg, #10b981 0%, #0f766e 100%); }
			.ma-mobile-dashboard-card--blue { background: linear-gradient(135deg, #3b82f6 0%, #0284c7 100%); }
			.ma-mobile-dashboard-card--purple { background: linear-gradient(135deg, #a855f7 0%, #4f46e5 100%); }
			.ma-mobile-dashboard-card--orange { background: linear-gradient(135deg, #f97316 0%, #dc2626 100%); }
			.ma-mobile-dashboard-card__main { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
			.ma-mobile-dashboard-card__title { display: block; font-size: 1rem; font-weight: 700; line-height: 1.35; text-transform: none; color: #fff; }
			.ma-mobile-dashboard-card__metric { display: block; margin-top: .85rem; font-size: 2.55rem; font-weight: 850; line-height: 1; color: #fff; }
			.ma-mobile-dashboard-card__icon { width: 42px; height: 42px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; background: rgba(255,255,255,.18); color: #fff; }
			.ma-mobile-dashboard-card__icon svg { width: 25px; height: 25px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
			.ma-mobile-dashboard-card__action { display: block; margin-bottom: .65rem; text-align: right; font-size: .7rem; font-weight: 800; color: rgba(255,255,255,.9); }
			.ma-mobile-dashboard-card__rule { height: 1px; background: rgba(255,255,255,.18); margin-bottom: .8rem; }
			.ma-mobile-dashboard-card__footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: .8rem; font-weight: 500; color: rgba(255,255,255,.82); }
			.ma-mobile-dashboard-card__footer strong { color: #fff; font-weight: 700; white-space: nowrap; }
			body.${ACTIVE_BODY_CLASS} .ma-mobile-dashboard-raw-hidden { display: none !important; }
			body.${ACTIVE_BODY_CLASS} .ma-workspace-title { display: none !important; }
			/* The custom cards have their own loading values; the native skeleton shifts them. */
			body.${ACTIVE_BODY_CLASS} .workspace-skeleton { display: none !important; }
			body.${ACTIVE_BODY_CLASS} .ce-block:has(.ma-workspace-title) { display: none !important; }
			@media (max-width: 1199px) { .${DASHBOARD_CLASS} { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
			@media (max-width: 767px) { .${DASHBOARD_CLASS} { grid-template-columns: 1fr; gap: 16px; } .ma-mobile-dashboard-card { min-height: 136px; padding: 20px; } }
		`;
		document.head.appendChild(style);
	}

	function icon_svg(name) {
		const icons = {
			user:
				'<path d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Z"/><path d="M5 20a7 7 0 0 1 14 0"/><path d="m9 16 3 3 3-3"/>',
			appointment:
				'<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M8 3v4M16 3v4M4 10h16"/><circle cx="9" cy="15" r="2"/><path d="M13 17c.8-1.8 4.2-1.8 5 0"/>',
			ticket:
				'<path d="M5 6h14a2 2 0 0 1 2 2v2a2 2 0 0 0 0 4v2a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-2a2 2 0 0 0 0-4V8a2 2 0 0 1 2-2Z"/><path d="M9 9h6M9 15h6"/>',
			chat: '<path d="M21 11a8 8 0 0 1-8 8H7l-4 3V11a8 8 0 0 1 8-8h2a8 8 0 0 1 8 8Z"/><path d="M7 9h10M7 13h6"/>',
			play: '<circle cx="12" cy="12" r="9"/><path d="m10 8 6 4-6 4Z"/>',
		};

		return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || icons.user}</svg>`;
	}

	function card_html(card) {
		return `
			<button type="button" class="ma-mobile-dashboard-card ma-mobile-dashboard-card--${card.accent}" data-card-key="${card.key}">
				<div class="ma-mobile-dashboard-card__main">
					<div>
						<span class="ma-mobile-dashboard-card__title">${escape_html(card.title)}</span>
					</div>
					<span class="ma-mobile-dashboard-card__icon">${icon_svg(card.icon)}</span>
				</div>
				<div class="ma-mobile-dashboard-card__bottom">
					<div class="ma-mobile-dashboard-card__rule"></div>
					<div class="ma-mobile-dashboard-card__footer">
						<span>${escape_html(card.footer_label)}</span>
						<strong data-card-footer="${card.key}">${escape_html(card.footer_value)} <span aria-hidden="true">&rarr;</span></strong>
					</div>
				</div>
			</button>
		`;
	}

	function workspace_root() {
		const $workspace_body = frappe.workspace?.body?.find(".editor-js-container").first();
		if ($workspace_body?.length) return $workspace_body;
		return $('[data-page-route="Workspaces"] .editor-js-container').first();
	}

	function hide_raw_workspace_blocks($root) {
		if (!$root.find(`.${DASHBOARD_SHELL_CLASS}`).length) return;

		$root.find(".ce-block, .ce-header, .widget, .shortcut-widget-box, h3, h4")
			.filter(function () {
				if ($(this).closest(`.${DASHBOARD_SHELL_CLASS}`).length) return false;
				const text = compact_text($(this).text());
				return (
					$(this).find(".shortcut-widget-box").length ||
					$(this).hasClass("shortcut-widget-box") ||
					$(this).hasClass("ma-workspace-title") ||
					($(this).find(".ma-workspace-title").length && text === "MobileApp") ||
					text === "MobileApp" ||
					(text.includes("MobileAppMobileAppUser") && text.includes("DoctorClinicalPortal"))
				);
			})
			.addClass("ma-mobile-dashboard-raw-hidden");
	}

	function open_support_menu() {
		const choices = [
			{key: "support-list", title: "Support Tickets", metric: "Tickets", accent: "purple", icon: "ticket",
				footer_label: "View and manage tickets", footer_value: "Open", route: ["List", "Support Ticket"]},
			{key: "support-chats", title: "Chats", metric: "Chats", accent: "blue", icon: "chat",
				footer_label: "Read and reply to messages", footer_value: "Open", route: ["List", "App Support Ticket"]},
		];
		const dialog = new frappe.ui.Dialog({
			title: __("Support"), size: "large",
			fields: [{fieldtype: "HTML", fieldname: "destinations"}],
		});
		dialog.fields_dict.destinations.$wrapper.html(
			`<div class="ma-support-destinations">${choices.map(card_html).join("")}</div>`
		).on("click", ".ma-mobile-dashboard-card", function () {
			const choice = choices.find(item => item.key === $(this).data("card-key"));
			if (!choice) return;
			delete frappe._mobile_support_target;
			frappe.route_options = null;
			dialog.hide();
			mobile_app.brand.open(choice.route);
		});
		dialog.show();
	}

	function bind_cards($dashboard) {
		$dashboard.find(".ma-mobile-dashboard-card").on("click", function () {
			const card = CARDS.find((item) => item.key === $(this).data("card-key"));
			if (!card?.route) return;
			if (card.key === "tickets") return open_support_menu();
			mobile_app.brand.open(card.route);
		});
	}

	function render_dashboard() {
		if (is_rendering) return;
		is_rendering = true;

		try {
			const active = is_mobile_workspace();
			document.body.classList.toggle(ACTIVE_BODY_CLASS, active);
			if (!active) {
				$dashboard?.detach();
				$(".ma-mobile-dashboard-raw-hidden").removeClass("ma-mobile-dashboard-raw-hidden");
				return;
			}

			inject_runtime_style();
			const $root = workspace_root();
			if (!$root.length) return;
			const first_render = !$dashboard;
			if (first_render) {
				$dashboard = $(`
					<div class="${DASHBOARD_SHELL_CLASS}">
						<div class="ma-brand-toolbar"><label for="ma-brand-filter">App brand</label><select id="ma-brand-filter" class="form-control" aria-label="App brand" style="width:auto">${mobile_app.brand.options()}</select><button type="button" class="btn btn-default btn-sm ma-brand-manage">Manage brands</button></div>
                        <p class="ma-brand-note">Choose a brand before opening a section. Records without a confirmed app origin appear under Unclassified. Diet and care records remain available from the linked user profile.</p>
                        <div class="${DASHBOARD_CLASS}">${CARDS.map(card_html).join("")}</div>
                        <div class="ma-related-links" aria-label="Related mobile app records"></div>
					</div>
				`);
                bind_cards($dashboard);
                $dashboard.on("click", "[data-related-doctype]", function (event) {
                    event.preventDefault();
                    const row = related_links.find(item => item.doctype === $(this).attr("data-related-doctype"));
                    if (!row) return;
                    if (row.single) {
                        frappe.route_options = null;
                        frappe.set_route("Form", row.doctype, row.doctype);
                    } else if (row.brand_filtered) {
                        mobile_app.brand.open(["List", row.doctype]);
                    } else {
                        frappe.route_options = {name: ["is", "set"]};
                        frappe.set_route("List", row.doctype);
                    }
                });
                $dashboard.on("click", ".ma-related-retry", refresh_related_links);
                $dashboard.find(".ma-brand-manage").on("click", () => { frappe.route_options = null; frappe.set_route("List", "Mobile App Brand"); });
                $dashboard.find("#ma-brand-filter").val(mobile_app.brand.get()).on("change", function () {
                    mobile_app.brand.set(this.value);
                });
			}
			// Stay outside #editorjs: its asynchronous render replaces its contents.
			// Reuse these nodes when returning from a list or workspace.
			if ($dashboard.parent()[0] !== $root[0]) {
				$root.prepend($dashboard);
                refresh_related_links();
                mobile_app.brand.refresh().then(() => {
                    $dashboard.find("#ma-brand-filter").html(mobile_app.brand.options()).val(mobile_app.brand.get());
                }).catch(() => frappe.show_alert({message: __("Unable to refresh app brands. Please reload."), indicator: "orange"}));
                if (!first_render) { $dashboard.find("#ma-brand-filter").val(mobile_app.brand.get()); }
			}
			hide_raw_workspace_blocks($root);
		} finally {
			is_rendering = false;
		}
	}

	function schedule_render() {
		if (render_timer !== null) return;
		render_timer = window.requestAnimationFrame(() => {
			render_timer = null;
			render_dashboard();
		});
	}

	// Apply the route's visibility before the next paint, including while Frappe loads.
	$(document).on("page-change", render_dashboard);
	frappe.router?.on?.("change", render_dashboard);

	$(document).ready(() => {
		schedule_render();
		frappe.after_ajax?.(schedule_render);
	});

	new MutationObserver(() => {
		if (!is_mobile_workspace()) return;
		schedule_render();
	}).observe(document.body, { childList: true, subtree: true });
})();
