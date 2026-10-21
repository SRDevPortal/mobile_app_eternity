# Updating existing app-brand labels

Installation/migration creates the default Siya Ayurveda and Seedfit brands, the
display fields, and an idle progress record. It does not start a historical
record update. New records continue to receive labels through the existing hooks.

Deploy with the normal site migration, mobile_app asset build, cache clear and
process restart. The site scheduler and a worker consuming the **long** queue
must be running.

As System Manager, open any **Mobile App Brand** record and click **Refresh
record brands**. This starts or resumes work and opens **Mobile App Brand Update /
record-brands**, where status, records checked, labels changed and errors appear.
Reload that record to see current progress.

Each job checks at most 200 records and stops after about 10 seconds between
records. Row-lock waits are limited to 3 seconds for this job. It commits labels
and its cursor together. The scheduler queues another batch on its next minute
tick; jobs do not continuously flood the queue. Normal queue load may add delay.

Interrupted workers resume from the last committed cursor. A reported failure
rolls back that batch, marks the run Failed and records an Error Log. Investigate
the error, then click Refresh record brands again to resume. Clicking after
Completed deliberately starts a new pass. Duplicate starts do not reset progress.

The cursor uses record names, without OFFSET scans or full-table COUNT queries.
Normal inserts/edits receive labels through hooks; direct database imports that
bypass hooks may require another pass. Ambiguous origins remain unclassified.
Legacy Select brand fields are preserved during migration, rather than scanning
historical values and converting them to Links without validation.

Schema changes and index creation can still take time on large tables. This
change removes the historical data backfill from deployment; it does not make
schema migration cost-free.
