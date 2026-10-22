# Eternity installation: Sales Invoice row-size limit

The failed statement was `ALTER TABLE tabSales Invoice ADD COLUMN custom_app_brand varchar(140)`.
MariaDB rejected it with error 1118 and the 65,535-byte logical row-size limit.
This is a schema-width problem, not invoice volume or historical brand processing.

## Fix

- New Sales Invoice brand fields use read-only Small Text (SQL TEXT), with no full-column index.
- Other brand fields remain Links. Existing working invoice Link columns and legacy Select fields are preserved.
- The field name and brand strings stay the same. Existing filters, API values, provenance stamping and resumable backfill still use `custom_app_brand`.
- Invoice brand display is plain text instead of a clickable Link on new installations. Brand-filtered invoice queries do not have a new brand index; assess their performance on large sites.
- A brand referenced by an invoice cannot be deleted, including when its reference is stored as text.
- Before install/migrate, repair an existing invoice brand Link definition only when its physical column is missing. This handles metadata committed during the failed install, before core schema synchronization can repeat the rejected ALTER.
- After custom-field setup, verify the physical brand column on every supported table. Explicitly synchronize only tables with a missing column, including Mobile App User. Frappe's custom-field helper can skip unchanged definitions left by a failed install, so metadata existence alone is insufficient. The repair verifies the result and fails visibly if the column is still absent.
- No unrelated invoice fields are altered or deleted. No historical invoice records are scanned or reclassified by this repair.

## Deploy and resume

Deploy the commit containing this fix to the branch used by the Eternity Frappe Cloud bench first. Keep a current production database backup before retrying schema operations.

Check the partially installed app:

```bash
bench --site eternityerp.m.frappe.cloud list-apps
```

If `mobile_app` is listed, run migration with the updated code:

```bash
bench --site eternityerp.m.frappe.cloud migrate
```

If it is not listed, retry installation with the updated code:

```bash
bench --site eternityerp.m.frappe.cloud install-app mobile_app
```

Use the corresponding deployment/migration controls in Frappe Cloud if shell access is unavailable. Do not uninstall the partially installed app or force an old-code retry.

Afterward confirm Sales Invoice has App Brand and the app workspace loads. Historical brand assignment remains a separate administrator-started background operation.

If the app is already installed and its field definitions are present, the deployed repair can also be run explicitly from the bench:

```bash
bench --site eternityerp.m.frappe.cloud execute mobile_app.brand.repair_missing_brand_columns
bench --site eternityerp.m.frappe.cloud clear-cache
```

This only completes missing schema; it does not start historical brand assignment. It returns the names of repaired DocTypes and returns an empty list when none need repair.

Validation: local regression tests reproduce error 1118 on a temporary wide InnoDB table, then successfully add the TEXT field and filter both brands and unclassified rows. Tests also cover partial-install repair, preservation of working Link columns, brand deletion protection, provenance, permissions and resumable batches. The live Eternity schema has not been inspected or migrated by this change; TEXT reduces the added footprint but a table with no remaining allowance at all may still require a separate schema review.
