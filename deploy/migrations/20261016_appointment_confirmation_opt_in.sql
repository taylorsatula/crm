-- Workspace auto-scheduling of appointment confirmation/reminder messages must
-- be opt-in. The column previously defaulted to TRUE, so every fresh workspace
-- silently queued email-channel messages on ticket creation even when the user
-- had never configured email delivery — the records then sat pending forever.
-- Flip stored values back to the new opt-in default; workspaces that explicitly
-- enabled confirmations can re-enable via Settings.
\set ON_ERROR_STOP on

BEGIN;

UPDATE workspace_settings
SET appointment_confirmation_enabled = FALSE
WHERE appointment_confirmation_enabled = TRUE;

COMMIT;
