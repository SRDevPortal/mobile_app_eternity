# Mobile-owned QuickLink

Flow: Flutter -> shared Render backend -> Frappe `mobile_app` records.
The backend calls OpenAI for text generation. WA Chat Hub is not read or written.
Existing WA Chat Hub conversations and settings remain untouched and are not imported.

## Prompt editing

Open Mobile App -> Manage brands -> choose Siya Ayurveda or Seedfit -> QuickLink AI Settings.
Set Main Instructions, Business Information and FAQs, Product Guidance, Human Handoff Rules,
and Example Questions and Answers. Save, then enable QuickLink AI. Each field is limited to
12,000 characters. Changes are loaded when the next queued message is claimed; an already
running answer uses the prompt revision recorded on its customer message.
These are instructions/reference information, not model training. Do not put credentials
or patient records in prompts. No provider credential is stored in Frappe or Flutter.

## Ownership and handoff

`Mobile App QuickLink Conversation` links a brand to an authenticated Mobile App User.
`Mobile App QuickLink Message` stores ordered messages and durable AI work state.
Only the trusted backend API role or System Manager can assert an app user's identity.
The backend derives that identity from Shopify authentication, never from request body fields.
ERP validates the user's exact configured brand prefix, active state and conversation owner.
Account/profile links and typed phone numbers do not grant clinical access. This version sends
no private ERP order/medical records to AI and offers care-team support for those questions.

Contact care team creates one existing Support Ticket with recent transcript, pauses AI,
and mirrors subsequent messages between the ticket and QuickLink. Agents reply in Support
Tickets or Mobile App QuickLink Conversation. Existing support permissions apply.
Closing/resolving the support ticket closes the conversation on the next poll. New chat is
available afterward. Other ERP apps and existing WhatsApp conversations are unchanged.

## Deployment order

1. Deploy the `mobile_app` commit to the production bench. Do not deploy WA Chat Hub.
2. Back up the site through the normal process. From the actual production bench run:

   ```sh
   bench --site <actual-site-name> migrate
   bench --site <actual-site-name> clear-cache
   bench build --app mobile_app
   bench restart
   ```

   Migration installs two mobile-owned DocTypes, adds Brand settings and creates the
   `Mobile App QuickLink API` role. It does not assign that role automatically. Assign it
   to the existing backend API user if that user is not a System Manager. Do not assign
   this integration role to customers or ordinary agents.
3. Deploy the shared backend commit after ERP migration. In Render configure dedicated
   `QUICKLINK_OPENAI_API_KEY` and `QUICKLINK_MODEL` for Siya, plus
   `SEEDFIT_QUICKLINK_OPENAI_API_KEY` and `SEEDFIT_QUICKLINK_MODEL` for Seedfit.
   The default model is `gpt-4.1-mini`. There is no cross-brand key fallback.
   Keep existing ERP and Shopify authentication unchanged. Missing provider keys disable
   AI sends but leave care-team handoff available. Keep actual keys out of Git.
4. Save each brand's prompts and enable AI when its provider key is configured.
5. Verify both brands with real signed-in test accounts: open, send, receive AI reply,
   reopen, start new chat, hand off, agent reply, close support and start a fresh chat.
6. Publish Flutter builds after deployment checks. The existing `/v1/ai-chat/*` routes
   remain. Updated clients use `mode` and `can_send` to allow agent messages while
   `ai_ready` is false. Older clients can still open the linked Support Ticket.

## Reliability and limits

Customer message IDs are idempotent within a conversation; changed text with the same ID
is rejected. ERP row locks serialize writes and handoff. Workers claim a two-minute lease,
retry at most three times, and discard late replies after handoff, closure, disabling or
lease replacement. A lost provider response can incur another provider request, but only
one visible reply is committed. Configured workers resume after Render restarts.

Limits: 12 customer messages per minute and 200 AI-channel messages per account/day.
History uses sequence cursors, 100 messages per page. Opening shows the latest 100 messages.
AI context uses the latest 20 chat turns and up to three validated public catalogue cards.
Provider requests have a 25-second timeout and bounded output.

Provider contract: https://developers.openai.com/api/docs/guides/text
Requests use Responses API with `store: false`, no tools and no shared provider conversation
IDs. This flag does not make a claim about provider abuse-monitoring retention.

## Verification

- Backend: `npm test`.
- Provider HTTP simulation: `postman simulation run postman/simulations/quicklink.sim.yaml --port 4907`,
  then `node scripts/test-quicklink-simulation.mjs`, from the backend repository.
- ERP: on a migrated TEST site, run
  `bench --site <test-site> run-tests --module mobile_app.tests.test_quicklink --skip-test-records`.
  Tests use synthetic users, roll back writes, and require both Brand records to exist.
- Flutter: `flutter test test/ai_chat_screen_test.dart test/quicklink_chat_test.dart`.

Local tests do not prove production deployment or a real provider reply. Complete the live
checks after ERP code, backend configuration and brand settings are deployed.
