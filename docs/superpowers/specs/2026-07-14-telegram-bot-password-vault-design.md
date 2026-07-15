# Blue Deer Bot — Password Vault

**Status:** Design approved · **Date:** 2026-07-14 · **Scope:** Add a PIN-gated password manager to the Blue Deer Telegram bot for storing utility/vendor login credentials.

## Goal

Give the admin a quick way, from within the Blue Deer bot, to store and retrieve utility/vendor login credentials (BSA water, DTE, PHA portals, insurance, etc.). Access is gated behind a PIN; credentials are encrypted at rest using a server-held key.

## Non-goals

- Multi-user vault. Single admin only in v1.
- Web UI for the vault. Bot-only.
- Password sharing / delegation / audit log.
- Password strength scoring, breach checking, autofill, TOTP.
- Edit-in-place for stored entries (v1 supports add + delete; edit is delete-then-re-add).

## Threat model & security decisions

**What we defend against:**
- **DB dump leak.** Encryption key is not in the DB, so a stolen dump is useless without also stealing the Railway env.
- **Casual Telegram-account snooping** (someone with brief access to the phone). PIN is required per session; sessions expire after 10 minutes of inactivity.
- **Online PIN brute force.** 5 wrong attempts → 15-minute lockout stored in DB.

**What we do NOT defend against:**
- **Compromised Railway environment.** If `VAULT_ENCRYPTION_KEY` leaks, all vault entries are decryptable. This is the accepted trade-off for allowing PIN reset and eliminating "forgot PIN = lost passwords" recovery scenarios.
- **Compromised Telegram account.** An attacker with full Telegram access can DM the bot and attempt PINs (rate-limited by the lockout). They cannot read stored entries without the PIN.
- **Server-side memory disclosure.** Decrypted passwords briefly exist in bot process memory.

**Explicitly rejected alternatives:**
- **PIN-only encryption** (Fernet key derived from PIN via PBKDF2): a 6-digit PIN has ~1M combinations and is offline-brute-forceable in seconds if the DB leaks.
- **Server key + PIN combined**: strongest, but "forgot PIN = passwords gone forever" was rejected for personal-use ergonomics.

## Architecture

**New module** `bluedeer_bot/vault.py` — all vault handlers, the PIN flow, and the `ConversationHandler` for the add flow. Keeps `handlers.py` uncluttered.

**New service** `bluedeer_bot/vault_crypto.py` — thin wrapper around `cryptography.fernet.Fernet` using the `VAULT_ENCRYPTION_KEY` env var. Handles encrypt/decrypt and raises a clear error if the key is missing or malformed.

**Two new tables** (one migration `database/migrations/add_vault.py`, mirroring `add_recert_reminder_log.py`):

```
vault_entries
  id                  SERIAL PRIMARY KEY
  label               VARCHAR(120) NOT NULL
  username            VARCHAR(255)
  password_encrypted  TEXT NOT NULL        -- Fernet ciphertext (base64)
  notes               TEXT
  created_at          TIMESTAMP DEFAULT NOW()
  updated_at          TIMESTAMP DEFAULT NOW()

vault_pin              -- singleton, id=1
  id                  SERIAL PRIMARY KEY
  pin_hash            VARCHAR(255) NOT NULL     -- bcrypt
  failed_attempts     INTEGER DEFAULT 0
  locked_until        TIMESTAMP
  updated_at          TIMESTAMP DEFAULT NOW()
```

**Admin gate.** A `_require_admin(update)` helper reads `BLUEDEER_ADMIN_TELEGRAM_ID` from the environment. Non-admin invocations reply "Not authorized" once and are dropped.

**Session state.** Unlock timestamp is stored in `context.user_data['vault_unlocked_at']` (python-telegram-bot's per-user in-memory state). Unlock TTL: **10 minutes** of inactivity, refreshed on each vault action. Not persisted across bot restarts — a restart is treated as a lock, which is the safe default.

## Flows

### 1. Setup (first run)

If no row exists in `vault_pin`:
1. `/vault` replies "No vault PIN set. Send a 6-digit PIN to create one." (force-reply)
2. User replies with a PIN — bot deletes the reply message.
3. Bot replies "Confirm your PIN." (force-reply)
4. User replies again — bot deletes the reply.
5. If the two match and are 6 digits: bcrypt-hash and insert into `vault_pin`, reply "✅ Vault created. Use /vault to unlock."
6. If mismatch or invalid: reply "PIN mismatch or invalid format." and restart the flow.

### 2. Unlock

`/vault` when unlocked → skip straight to the main menu.

`/vault` when not unlocked (or TTL expired):
1. Check `vault_pin.locked_until` — if in the future, reply "Locked. Try again at HH:MM." and stop.
2. Reply "Send your PIN." with force-reply.
3. User replies. Bot deletes the reply message.
4. Bcrypt-verify the PIN.
   - **Success:** set `context.user_data['vault_unlocked_at'] = now`, reset `failed_attempts` to 0, delete the "Send your PIN" prompt, show main menu.
   - **Failure:** increment `failed_attempts` (consecutive counter — reset to 0 on any success). At 5, set `locked_until = now + 15 min`, reset attempts to 0. Reply with the appropriate error.

### 3. Main menu

Inline keyboard, one row: `🔑 List  ·  ➕ Add  ·  🔒 Lock`.

### 4. List → Get

- `🔑 List` fetches all `vault_entries` ordered by `label ASC`. Renders each as an inline button (`label — username`, truncated if long) with `callback_data=vault_get:<id>`.
- Tap → decrypt the entry's password, send:

  ```
  🏦 <label>
  User: <username>
  Pass: ||<password>||

  [🗑 Delete]
  ```

  using MarkdownV2. The `||…||` is Telegram's spoiler syntax; the password stays hidden until the user taps it.
- The "🗑 Delete" inline button carries `callback_data=vault_del:<id>` and shows a confirm step (`Delete <label>?` with Yes/No buttons) before removing the row.

### 5. Add (ConversationHandler)

States: `ADD_LABEL → ADD_USERNAME → ADD_PASSWORD → done`.

1. `➕ Add` → "Send the label (e.g., 'BSA Water')." → state ADD_LABEL.
2. User replies → bot deletes reply, stores label in `context.user_data`, prompts "Send the username." → ADD_USERNAME.
3. User replies → bot deletes reply, stores username, prompts "Send the password." → ADD_PASSWORD.
4. User replies → bot deletes reply, encrypts password with Fernet, inserts row, replies "✅ Saved: <label>" + returns to main menu.

Every intermediate user message is deleted after capture so nothing sensitive lingers in the chat.

### 6. Lock

`🔒 Lock` (or `/vault_lock`) → clears `vault_unlocked_at` from `context.user_data`, replies "🔒 Locked."

Auto-lock is lazy: checked on the next action. If `now - vault_unlocked_at > 10 min`, treat as locked and re-prompt for PIN.

## Config

- **`VAULT_ENCRYPTION_KEY`** — required Fernet key. Generate once with:
  ```
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  Store in Railway env for both the `worker` (webapp) and `h20silobot` (bot) services.
- **`BLUEDEER_ADMIN_TELEGRAM_ID`** — already exists; reused as the vault access allowlist (single ID).

## Error handling

- **Missing/malformed `VAULT_ENCRYPTION_KEY`**: `/vault` replies "Vault is not configured. Set VAULT_ENCRYPTION_KEY." and returns. No crash.
- **DB unavailable**: `/vault` replies "Vault is offline — DB unavailable." Mirrors existing bot behavior.
- **Decryption failure on a single entry** (e.g., key was rotated after entries were stored): the entry still appears in the list, but tapping it replies "⚠️ Unable to decrypt — key may have been rotated." Other entries continue to work.
- **Telegram message deletion failure** (rate limits, missing permissions): log a warning, continue the flow.
- **Lockout race** (two attempts arrive nearly simultaneously): read `locked_until` on every attempt; the check is idempotent.
- **Non-admin invocation**: reply "Not authorized" once, drop.

## PIN reset

Because the encryption key lives in `VAULT_ENCRYPTION_KEY` (not derived from the PIN), forgetting the PIN does not lose data. Reset procedure:

1. Connect to the DB (Railway → Postgres → shell).
2. `DELETE FROM vault_pin;`
3. Next `/vault` invocation runs the setup flow again to establish a new PIN.

All existing `vault_entries` remain readable with the new PIN. No dedicated UI for this in v1 — running SQL is intentional friction, since PIN reset should be rare and deliberate.

## Handler registration

Add in `bluedeer_bot/handlers.py::setup_handlers` (or a new `setup_vault_handlers` called from the same place):

```
application.add_handler(vault_conversation_handler)  # /vault + add-flow
application.add_handler(CommandHandler("vault_lock", vault_lock_command))
application.add_handler(CallbackQueryHandler(vault_menu_callback, pattern="^vault_"))
```

Add `BotCommand("vault", "🔐 Password vault")` to the command list in `bot.py::start`.

## Migration wiring

`database/migrations/add_vault.py::run_migration()` creates both tables idempotently. Wired into:
- `webapp/main.py` — alongside the existing migration calls, so the webapp deploy also runs it.
- `BlueDeerBot.start()` — alongside the recert-reminder migration call, so the bot deploy also runs it.

## Testing (manual, post-deploy)

- Non-admin user sends `/vault` → "Not authorized."
- Admin sends `/vault` for the first time → walks setup flow, sets PIN.
- Admin sends `/vault`, enters correct PIN → menu appears.
- Admin sends `/vault`, enters wrong PIN 5× → "Locked. Try again at …" for 15 minutes.
- Add flow: create entry → confirm it appears in List → tap it → verify spoiler + decrypted content.
- Delete flow: 🗑 Delete → confirm → entry gone.
- Lock: 🔒 Lock → next `/vault` re-prompts for PIN.
- TTL: wait 10 min after unlock → next action re-prompts.
- Set an invalid `VAULT_ENCRYPTION_KEY` → `/vault` says "not configured", no crash.

## Out of scope for v1

- Editing an entry in place (delete + re-add works).
- Notes field in the UI (schema has it, add-flow skips it).
- Bulk import/export.
- Audit log of accesses.
- Multiple vaults or categories.
- Web UI mirror.
- Automatic key rotation.
