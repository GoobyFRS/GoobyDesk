# MFA Plan

## Goal

Add a low-barrier MFA layer for technician logins without changing the app's databaseless design.

Recommended first implementation: app-based TOTP plus one-time recovery codes.

## Why this approach

- No external SaaS, SMS gateway, or paid provider.
- Works with the current JSON-file storage model.
- Can be implemented with Python standard library helpers plus existing bcrypt password hashing.
- Authenticator apps are common and easy for small teams to adopt.
- Better security than email-only codes because a mailbox compromise alone does not also bypass login MFA.

## Why not start with other options

### Email one-time codes

- Lower implementation effort, but weaker.
- Depends on SMTP being configured correctly.
- If the user's mailbox is already compromised, MFA is effectively gone.
- Still useful later as an account recovery path, not as the primary MFA factor.

### SMS

- Adds third-party dependencies and operating cost.
- Weaker than TOTP.

### WebAuthn / passkeys

- Best long-term option, but higher implementation cost.
- Bigger UI and browser-handling surface area.
- Not the lowest-barrier first step for this repo.

## Current auth state in this repo

### Login flow

- `app.py` owns the `/login` route.
- Username and password are checked directly against the auth JSON records.
- Successful login sets:
  - `session["technician"]`
  - `session["roles"]`
- There is currently no second-factor challenge.

Relevant files:

- `app.py`
- `templates/public/login.html`
- `local_handlers/utils.py`
- `storage/employee_store.py`

### Existing security-related fields

The repo already has useful account metadata:

- Auth records already store:
  - `tech_username`
  - `password_hash`
  - `account_locked`
  - `must_change_password`
- HR records already store:
  - `access.mfa_enabled`
  - `access.last_login`
  - `access.failed_login_attempts`
  - `access.login_enabled`
  - `access.auth_username`

This means MFA can fit the current model cleanly.

### Important gap already visible

`templates/public/login.html` renders a Cloudflare Turnstile widget, but the `/login` POST handler in `app.py` does not currently call the existing `_verify_turnstile()` helper from that same file.

That is separate from MFA, but it should be fixed while implementing the login flow changes because the UI already implies CAPTCHA protection. Treat it as a high-priority auth hardening task, not a nice-to-have follow-up, and open a tracking issue if it is not fixed in the same workstream.

## Recommended design

### Primary factor

- Keep current username + password authentication.

### Second factor

- Add TOTP using a standard 6-digit code.
- Use 30-second time steps.
- Allow a drift tolerance of ±1 window only. With 30-second steps, that means accepting 3 windows total: previous, current, and next.

### Recovery method

- Generate a small set of one-time recovery codes during enrollment.
- Store recovery codes as bcrypt hashes, not plain text.
- Show recovery codes once and instruct the admin/user to save them offline.

## Low-barrier implementation shape

### 1. Add MFA fields to auth records

Prefer the auth JSON record as the source of truth.

Suggested new fields in the auth record:

- `mfa_enabled`: boolean
- `mfa_encrypted_secret`: TOTP secret stored at rest in encrypted form; see the security section below
- `mfa_enrolled_at`: timestamp
- `mfa_recovery_codes`: list of objects containing a bcrypt hash plus `used_at`
- `mfa_last_used_at`: timestamp or null
- `mfa_failed_attempts`: integer

Keep `access.mfa_enabled` in the HR record as a mirrored display field if desired, but avoid making HR the primary source of truth for login security decisions.

### 2. Add small MFA helper module

Recommended new file:

- `local_handlers/mfa.py`

Put the TOTP-specific logic there so `app.py` stays readable.

Responsibilities:

- generate Base32 secrets
- build an `otpauth://` URI
- verify a 6-digit TOTP code
- generate recovery codes
- verify recovery codes

This can be done with standard-library modules such as:

- `base64`
- `hashlib`
- `hmac`
- `secrets`
- `struct`
- `time`
- `urllib.parse`

## Enrollment flow

### Recommended first version

Use manual enrollment instead of QR generation.

Why:

- avoids adding a QR code dependency
- avoids adding image generation logic
- keeps the first implementation simple

User/admin flow:

1. Admin or authenticated user opens an MFA setup page.
2. App generates a secret and recovery codes.
3. App shows:
   - the Base32 secret
   - the account label
   - the issuer name
   - the recovery codes
4. User enters one valid TOTP code to confirm setup.
5. App persists the secret and sets `mfa_enabled` to true.

If a later UI improvement is wanted, QR rendering can be added afterward.

## Login flow changes

### Recommended behavior

Do not fully authenticate the session until the MFA challenge passes.

Suggested flow:

1. User submits username and password.
2. If password fails, return normal login failure.
3. If password succeeds and MFA is disabled:
   - create the normal authenticated session
4. If password succeeds and MFA is enabled:
   - create a short-lived partial session only
   - redirect to an MFA challenge page
5. Only after a valid TOTP or recovery code:
   - set `session["technician"]`
   - set `session["roles"]`
   - clear partial-session values

### Partial-session fields

Suggested temporary session keys:

- `session["pending_mfa_username"]`
- `session["pending_mfa_uuid"]`
- `session["pending_mfa_started_at"]`

Keep the partial session short-lived and clear it on:

- success
- logout
- timeout
- too many MFA failures

Recommended timeout: 90 seconds maximum.

## Suggested routes and templates

### Routes

Likely touch points:

- `app.py`
- `blueprints/hr_module.py`

Suggested additions:

- `/login/mfa` for the second-factor challenge
- `/account/mfa/setup` for enrollment
- `/account/mfa/disable` for controlled disable/reset

### Templates

Likely touch points:

- `templates/public/login.html`
- new template for MFA challenge
- optional new template for MFA setup
- `templates/hr/profile.html` for admin visibility/reset actions

## Admin and support workflow

### Good first rollout

- Allow admins to enable/reset MFA per employee.
- Require recovery codes to be regenerated on reset.
- Log all MFA setup, disable, reset, and recovery-code use events.

### Password resets

When an admin resets a password, decide whether MFA should remain enabled.

Recommended first behavior:

- keep MFA enabled on password reset
- provide a separate explicit "Reset MFA" action

That avoids silently weakening the account and prevents password reset from becoming an MFA bypass path.

### Account recovery edge case

If a user loses the password, MFA device, and recovery codes, recovery should require an explicit admin-driven MFA reset workflow instead of silently bypassing MFA.

Recommended recovery policy:

- require an admin to perform password reset and MFA reset as separate actions
- log both events with actor and target identifiers
- if the deployment has multiple admins, require a second admin approval outside the app or through a documented ops procedure
- if the deployment has only one admin, require a short delay or manual out-of-band identity check before re-enabling access

## Security details worth keeping

### TOTP secret handling

Recommended minimum production behavior: store the TOTP secret in the auth JSON file only after encrypting it with an application key sourced from environment configuration.

Recommended cryptography approach:

- use AES-256-GCM for authenticated encryption
- generate a fresh random nonce for every encryption operation, never reuse it with the same key, and store it alongside the ciphertext
- load a 32-byte application key from environment configuration
- if the deployment supplies a passphrase instead of a raw key, derive the actual encryption key with scrypt using at least `N=131072`, `r=8`, and `p=1`, and raise the work factor further if deployment capacity allows
- do not invent custom crypto primitives or ad hoc reversible obfuscation

Because this secret is sensitive:

- treat the auth JSON file as security-sensitive
- use an environment-backed encryption key so file disclosure alone does not disclose the TOTP seed
- ensure deployment guidance uses restrictive filesystem permissions
- never log the secret or recovery codes

App-level secret encryption should be the implemented approach for the MFA seed.

Deployment-side encryption should be treated as additional hardening, not a replacement, because a leaked JSON file should not by itself become an MFA bypass artifact.

### Recovery codes

- Hash them with existing bcrypt helpers.
- Each code should be single use.
- Mark a code as used or remove it immediately after successful use.

### Brute-force controls

MFA should be paired with basic rate limiting behavior in the existing account metadata:

- increment `failed_login_attempts` on password failure
- optionally add `mfa_failed_attempts`
- reset failure counters on successful login
- consider temporary lockout after repeated failures

### Session safety

- Clear any pending MFA state on logout.
- Expire pending MFA state quickly.
- Do not store roles in session before MFA succeeds.

## Practical implementation order

### Phase 1

1. Add MFA helper module.
2. Extend auth record schema.
3. Add enrollment page with manual secret entry.
4. Add recovery code generation and storage.
5. Split login into password step and MFA step.
6. Mirror `mfa_enabled` into HR access display data.

### Phase 2

1. Add admin reset/disable controls.
2. Record `last_login`, `mfa_last_used_at`, and failure counters consistently.
3. Enforce Turnstile on login POST.

### Phase 3

1. Require MFA for admin accounts.
2. Require MFA for all technician accounts once rollout is proven stable.
3. Optionally add QR rendering for convenience.

## Acceptance criteria for a first good version

- Password-only accounts still work when MFA is not enabled.
- MFA-enabled accounts require a second factor before any privileged session is created.
- Recovery codes work once each.
- Admin can reset password without automatically disabling MFA.
- Admin can explicitly reset MFA when needed.
- Login flow does not leak whether the username or MFA state is valid beyond normal auth responses.
- TOTP secrets and recovery codes are never written to logs.

## Recommended summary

Best low-barrier path: implement TOTP plus bcrypt-hashed recovery codes, keep auth JSON as the source of truth, use a short-lived partial login session, and defer QR/passkey work until after the first rollout is stable.
