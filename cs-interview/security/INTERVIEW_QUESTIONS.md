# 🔒 Security (Backend) — Staff-Level Interview Questions

> *10 questions covering tokens, OAuth/OIDC, injection, encryption, secrets, abuse protection, authentication, browser security, supply chain and SSRF. Each answer leads with the 30-second version, then the mechanism, then trade-offs and what the interviewer probes next. Current as of October 2026 (OWASP Top 10:2025, RFC 9700, NIST SP 800-63B-4).*

---

### OWASP Top 10 (2025) Mapping

The OWASP Top 10 was revised in 2025. Changes from 2021 worth knowing: **Software Supply Chain Failures** (A03) replaces "Vulnerable and Outdated Components" and widens it; **SSRF** (A10:2021) was folded into **Broken Access Control**; **Mishandling of Exceptional Conditions** (A10) is new; Security Misconfiguration rose to A02.

| Question # | Topic | OWASP Top 10:2025 category |
|-----------|-------|----------------|
| 1 | JWT Internals | A07:2025 — Authentication Failures; A04:2025 — Cryptographic Failures |
| 2 | OAuth2 & OIDC | A07:2025 — Authentication Failures; A01:2025 — Broken Access Control |
| 3 | SQL Injection | A05:2025 — Injection |
| 4 | Encryption | A04:2025 — Cryptographic Failures |
| 5 | Secrets Mgmt | A02:2025 — Security Misconfiguration; A04:2025 — Cryptographic Failures |
| 6 | Rate Limiting | A06:2025 — Insecure Design (resource consumption is also OWASP **API** Top 10 API4:2023) |
| 7 | Auth Methods | A07:2025 — Authentication Failures |
| 8 | CORS/CSRF | A01:2025 — Broken Access Control; A02:2025 — Security Misconfiguration |
| 9 | Supply Chain | A03:2025 — Software Supply Chain Failures; A08:2025 — Software or Data Integrity Failures |
| 10 | SSRF | A01:2025 — Broken Access Control |

The full 2025 list: A01 Broken Access Control, A02 Security Misconfiguration, A03 Software Supply Chain Failures, A04 Cryptographic Failures, A05 Injection, A06 Insecure Design, A07 Authentication Failures, A08 Software or Data Integrity Failures, A09 Security Logging and Alerting Failures, A10 Mishandling of Exceptional Conditions.

---

## Table of Contents

1. [JWT Internals & Security Considerations](#1-jwt-internals-security-considerations)
2. [OAuth2 Flows & OpenID Connect](#2-oauth2-flows-openid-connect)
3. [SQL Injection Prevention at Scale](#3-sql-injection-prevention-at-scale)
4. [Encryption at Rest & In Transit](#4-encryption-at-rest-in-transit)
5. [Secrets Management & Vault](#5-secrets-management-vault)
6. [Rate Limiting & DDoS Protection](#6-rate-limiting-ddos-protection)
7. [Authentication: Session vs Token vs Passwordless](#7-authentication-session-vs-token-vs-passwordless)
8. [CORS, CSRF, and SameSite Cookies](#8-cors-csrf-and-samesite-cookies)
9. [Supply Chain Security](#9-supply-chain-security)
10. [SSRF & Server-Side Vulnerabilities](#10-ssrf-server-side-vulnerabilities)

---

## 1. JWT Internals & Security Considerations

**Q:** "Design a JWT-based authentication system for a microservices architecture. The security team says JWTs are inherently insecure because anyone can decode them. Address their concerns. Specifically: how do you handle token revocation, key rotation, and the 'logout everywhere' feature?"

**What They're Really Testing:** Whether you understand JWT's security model (signed, not encrypted) and have practical solutions for the hard problems.

### Answer

!!! tip "30-second answer"
    A JWS-signed JWT is **readable but tamper-proof**: integrity comes from the signature, not secrecy, so never put secrets or sensitive PII in it (use JWE or an opaque token if you must hide claims). Make verification strict: pin the algorithm, check `iss`, `aud`, `exp`, and the token type; use asymmetric keys (ES256/EdDSA) published via a **JWKS** endpoint with `kid`-based rotation. Revocation is the real trade-off of self-contained tokens: keep access tokens short-lived (5–15 min), make refresh tokens stateful and rotating, and for "logout everywhere" revoke the refresh tokens and push a small **deny-list** (by `jti` or by "tokens for user X issued before T") to services for the remaining access-token lifetime. Any per-request revocation check is state; be explicit about where it lives and what it costs. Follow RFC 8725 (JWT BCP, being updated by the 8725bis draft) and RFC 9068 for access-token JWTs.

**Signed, not encrypted:**

```
header.payload.signature        (each part base64url-encoded)

header:  {"alg": "ES256", "typ": "at+jwt", "kid": "2026-10"}
payload: {"iss": "https://auth.example.com", "aud": "orders-api",
          "sub": "user_42", "scope": "orders:read",
          "iat": 1791331200, "exp": 1791331800, "jti": "8f1c..."}

signature = ECDSA_P256_SHA256(private_key, base64url(header) + "." + base64url(payload))
```

- Anyone can **read** it; only the issuer can **mint** it; any change breaks the signature.
- Base64 is encoding, not encryption. For confidentiality, use JWE (encrypted JWT) or opaque reference tokens that the API introspects (RFC 7662).

**Classic JWT attacks and their fixes:**

| Attack | How it works | Fix |
|---|---|---|
| `alg: none` | Token claims to be unsigned | Library-level allowlist of algorithms |
| Algorithm confusion | Server expects RS256; attacker sends HS256 signed with the **public** key as the HMAC secret | Pin `algorithms=[...]` per key; never let the header choose; modern libraries refuse to use a PEM public key as an HMAC secret |
| `kid` / `jku` / `x5u` injection | Header points at an attacker-controlled key or a file path / SQL | Treat `kid` as a lookup key into **your** JWKS only; ignore `jku`/`x5u` unless allowlisted |
| Token substitution across services | A token for service A is accepted by service B | Validate `aud` (and `iss`) on every service |
| Cross-JWT confusion | An ID token or other JWT is accepted as an access token | Check `typ` (`at+jwt`, RFC 9068) and the expected claim set |
| Weak HMAC secrets | HS256 secrets brute-forced offline | Asymmetric keys; if HMAC, ≥ 256-bit random secrets |
| Stolen bearer token | Whoever holds it can use it | Short TTLs; sender-constrained tokens (**DPoP**, RFC 9449, or mTLS-bound, RFC 8705) |

**Issuing and verifying (PyJWT, tested):**

```python
from datetime import datetime, timedelta, timezone
import uuid

import jwt

ISSUER = "https://auth.example.com"
AUDIENCE = "orders-api"


def issue_access_token(user_id: str, kid: str, private_key) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "iss": ISSUER,
            "aud": AUDIENCE,
            "sub": user_id,                    # must be a string (PyJWT ≥ 2.10 enforces this)
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "jti": uuid.uuid4().hex,           # lets you deny-list a single token
            "scope": "orders:read",
        },
        private_key,
        algorithm="ES256",
        headers={"kid": kid, "typ": "at+jwt"},  # RFC 9068 access-token type
    )


def verify_access_token(token: str, keys_by_kid: dict) -> dict:
    kid = jwt.get_unverified_header(token).get("kid")
    key = keys_by_kid.get(kid)
    if key is None:
        raise jwt.InvalidTokenError("unknown kid")   # refetch JWKS once (rate-limited), then reject
    return jwt.decode(
        token,
        key,
        algorithms=["ES256"],                         # pinned, never taken from the header
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        leeway=30,                                    # small clock-skew allowance
    )
```

**Revocation — options and their real cost:**

| Approach | Revocation delay | State per request | Notes |
|---|---|---|---|
| Short-lived access token + rotating refresh token | Up to access-token TTL | None | The baseline. Refresh tokens live server-side and can be revoked instantly |
| Deny-list of `jti` (or user + "not before" timestamp) | Seconds (push to services) | Local lookup in a small in-memory set/Bloom filter fed by an event stream | Entries only need to live until the token's `exp`, so the list stays small |
| Per-user `token_version` claim checked against a DB/cache | Immediate | A cache read per request | Simple "logout everywhere", but it **is** a stateful check, the same cost class as a session lookup |
| Token introspection (RFC 7662) / opaque tokens | Immediate | A call (cacheable) to the auth server | Use for high-risk operations |
| Rotating the signing key | Immediate for **all** users | None | A break-glass response to key compromise, not a per-user tool |

**Refresh-token rotation with reuse detection** (required for public clients by RFC 9700 unless tokens are sender-constrained): each refresh returns a **new** refresh token and invalidates the old one. If an old refresh token is ever presented again, someone has a copy: revoke the whole token family and force re-authentication.

**Key rotation:**

1. Generate the new key pair and **publish** its public key in the JWKS (`kid = "2026-11"`) **before** signing with it, so verifiers that cache the JWKS already know it.
2. After the JWKS cache TTL has passed, start **signing** with the new key.
3. Keep the old public key in the JWKS until the **last token it signed has expired** (i.e. max access-token TTL after it stopped signing, not after it was created).
4. Remove the old key. Verifiers that see an unknown `kid` refetch the JWKS once (rate-limited) before rejecting.

Keep private keys in a KMS/HSM and sign through it, so they never sit on application hosts.

**Logout everywhere:**

```python
def revoke_all_sessions(user_id: str) -> None:
    now = int(time.time())
    db.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE user_id = %s", (user_id,))
    # Services reject access tokens for this user with iat < now until they expire naturally.
    event_bus.publish("user.tokens_revoked", {"sub": user_id, "not_before": now,
                                              "expires_at": now + MAX_ACCESS_TOKEN_TTL})
```

Every service keeps the `{sub: not_before}` entries in memory and drops them after `expires_at`, so the deny-list stays tiny and the check needs no network call.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Signature vs encryption** | Clearly distinguishes JWS signing from JWE encryption; no secrets in claims |
| **Validation** | Pinned alg, iss/aud/exp/typ checks, JWKS with kid; knows alg confusion and kid injection |
| **Revocation** | Short TTL + rotating refresh tokens + small pushed deny-list; honest about state |
| **Key rotation** | Publish-before-sign, retire after last token expires, KMS-held keys |
| **Token theft** | Mentions DPoP/mTLS sender-constrained tokens |

---

## 2. OAuth2 Flows & OpenID Connect

**Q:** "Design an OAuth2 authorization flow for a mobile app that needs to access user data from a third-party API (e.g., 'Login with Google'). Compare Authorization Code + PKCE vs Implicit Grant. How does OpenID Connect add identity on top of OAuth2?"

**What They're Really Testing:** Understanding of OAuth2 grant types, PKCE, and the difference between authentication and authorization.

### Answer

!!! tip "30-second answer"
    Use **Authorization Code + PKCE** in the **system browser** (ASWebAuthenticationSession on iOS, Custom Tabs on Android, per RFC 8252), never an embedded WebView. The app creates a random `code_verifier`, sends only its SHA-256 hash (`code_challenge`, method `S256`) with the authorization request, and must present the verifier to redeem the code, so an intercepted code is useless. The **implicit** grant returned tokens in the URL fragment with nothing binding them to the client; current guidance (RFC 9700, the OAuth 2.0 Security BCP, January 2025, and the OAuth 2.1 draft) says don't use it, and forbids the password grant. **OAuth** answers "may this client access this API?"; **OpenID Connect** adds an **ID token** that answers "who is the user?", which the client must validate (signature, `iss`, `aud`, `exp`, `nonce`).

**Authorization Code + PKCE for a mobile app with a backend:**

```
Mobile app                         Google (authorization server)        Your backend
    │ 1. code_verifier = 32 random bytes, base64url (43-128 chars)
    │    code_challenge = BASE64URL(SHA256(code_verifier))
    │    state = random, nonce = random
    │
    │ 2. open system browser:
    │    /authorize?response_type=code&client_id=...&redirect_uri=https://app.example.com/cb
    │      &scope=openid%20email&code_challenge=...&code_challenge_method=S256
    │      &state=...&nonce=...
    │──────────────────────────────────►│
    │         3. user signs in, consents │
    │◄──────────────────────────────────│ 4. redirect to claimed https link (Universal/App Link)
    │    ?code=...&state=...                with the code
    │ 5. check state
    │ 6. POST code + code_verifier (+ nonce) over TLS ───────────────────────────►│
    │                                    │◄── 7. token request: code, verifier,    │
    │                                    │        client authentication            │
    │                                    │ 8. checks SHA256(verifier) == challenge │
    │                                    │──► id_token, access_token, refresh ────►│
    │                                                     9. validate id_token,    │
    │◄──────────────────────────────── 10. your own session / tokens ─────────────│
```

Two valid shapes: the app redeems the code itself as a **public client** (no client secret can be kept in a mobile binary), or it forwards code + verifier to its backend, which redeems it as a **confidential client** (shown above). Either way PKCE is required (RFC 9700 requires it for public clients and recommends it for all).

**Why `S256`, not `plain`:** with `plain` the challenge equals the verifier, so anyone who sees the authorization request (logs, a malicious app watching the redirect) learns the verifier. Servers should reject `plain` when the client can do `S256`.

**Grants in 2026:**

| Grant | Status | Why |
|---|---|---|
| Authorization code + PKCE | Use it | Code bound to the client instance; tokens never in the URL |
| Implicit | Don't (RFC 9700; removed in OAuth 2.1 draft) | Tokens in the URL fragment leak via history, logs, referrers, browser extensions; no sender binding; no refresh tokens |
| Resource owner password | Must not | App handles the user's password; defeats MFA and phishing resistance |
| Client credentials | Use for machine-to-machine | No user involved |
| Device authorization (RFC 8628) | TVs, CLIs | User approves on another device |
| Refresh token | Use with rotation or sender-constraining | RFC 9700 requires one of the two for public clients |

Other RFC 9700 requirements interviewers like: exact string matching of redirect URIs, no open redirectors, and sender-constrained tokens (DPoP or mTLS) where possible. For high-value APIs, **PAR** (Pushed Authorization Requests, RFC 9126) sends the authorization request over a back channel so it can't be tampered with in the browser.

**OpenID Connect — identity on top of OAuth:**

```
OAuth 2.0:  "The user lets this app read their Google Drive"   (authorization; access token for the API)
OIDC:       "The user is Google account 1234567890"           (authentication; ID token for the client)

ID token payload:
{
  "iss": "https://accounts.google.com",
  "sub": "1234567890",          ← stable identifier: key your account link on (iss, sub)
  "aud": "my-app-client-id",    ← must be YOUR client id
  "exp": 1791334800, "iat": 1791331200,
  "nonce": "n-0S6_WzA2Mj",      ← must equal the nonce you sent (binds token to this login)
  "email": "alice@example.com", "email_verified": true
}
```

Rules that prevent real breaches:

- **Link accounts by `(iss, sub)`, never by email.** Emails change, can be unverified, and in multi-tenant identity providers can be set by the tenant admin (the "nOAuth" class of bugs).
- **Don't send ID tokens to APIs as access tokens.** The ID token's audience is your client, not the API.
- **Validate everything**: signature against the provider's JWKS, `iss`, `aud`, `exp`, `nonce`, and `azp` when present.

**Backend callback (confidential client):**

```python
@router.post("/auth/google/callback")
async def google_callback(body: CallbackBody, session: Session):
    # 1. state was checked by the app; check the nonce we stored for this login attempt
    expected_nonce = session.pop("oidc_nonce", None)

    # 2. redeem code + verifier
    resp = await http.post("https://oauth2.googleapis.com/token", data={
        "grant_type": "authorization_code",
        "code": body.code,
        "code_verifier": body.code_verifier,
        "redirect_uri": "https://app.example.com/cb",
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,     # from a secret manager, not source code
    }, timeout=5)
    resp.raise_for_status()
    tokens = resp.json()

    # 3. validate the ID token (signature via Google's JWKS, iss, aud, exp, nonce)
    claims = verify_google_id_token(tokens["id_token"], audience=GOOGLE_CLIENT_ID,
                                    nonce=expected_nonce)

    # 4. find or create the local account by (iss, sub)
    user = await upsert_user(issuer=claims["iss"], subject=claims["sub"],
                             email=claims.get("email") if claims.get("email_verified") else None)

    # 5. issue YOUR session or tokens; keep Google's refresh token only if you need offline access
    return await create_app_session(user)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **PKCE purpose** | Binds the code to the client instance; S256; verifier format |
| **Native app specifics** | System browser, claimed https redirects, public vs confidential client |
| **Current guidance** | RFC 9700: no implicit, no password grant, refresh token rotation/sender-constraining |
| **OIDC vs OAuth2** | Authentication vs authorization; ID token vs access token |
| **id_token verification** | Signature, iss, aud, exp, nonce; links accounts by (iss, sub) |

---

## 3. SQL Injection Prevention at Scale

**Q:** "A legacy ORM-based application has a SQL injection vulnerability discovered in a user search endpoint. Walk through the remediation strategy across the entire stack: application code changes, database hardening, and WAF rules. Also address blind SQLi, second-order injection, and NoSQL injection variants."

**What They're Really Testing:** Whether you understand that SQL injection is not a single vulnerability but a class of attacks, and have defense-in-depth strategies that go beyond just parameterized queries.

### Answer

!!! tip "30-second answer"
    Fix the root cause: **every value goes through a bound parameter**, including values read back from your own database (second-order injection). Parameters can't be used for identifiers or keywords, so column names, sort direction and table names come from an **allowlist**. Then add defence in depth: a least-privilege database role (no DDL, only the tables it needs), row-level security for tenant isolation, generic error messages, and a WAF as a speed bump while you patch, not as the fix. Find the rest of the bug class with code search for string-built SQL, SAST rules in CI, and DAST. NoSQL has the same bug in a different shape: user input interpreted as **query operators**.

**Three variants:**

```python
# 1. In-band (classic)
query = f"SELECT * FROM users WHERE name = '{name}'"
# name = "' OR 1=1 --"           → returns every row
# name = "'; DROP TABLE users --" → stacked query; works only if the driver allows
#   multiple statements per call (psycopg's simple query protocol does; most MySQL
#   drivers don't by default)

# 2. Blind (boolean- or time-based): no data in the response, but behaviour leaks it
# name = "x' OR (SELECT ascii(substr(password,1,1)) FROM admins LIMIT 1) > 109 --"
# Compare responses (or response time with pg_sleep / SLEEP) and binary-search each
# character: ~7 requests per character. sqlmap automates this.

# 3. Second-order: payload stored safely, executed later
# Signup stores username "x'; UPDATE users SET role='admin' WHERE id=42; --"
# via a parameterized INSERT (fine). Months later a reporting job does:
#   f"SELECT * FROM audit WHERE changed_by = '{row.username}'"   ← executes the payload
# Lesson: data from your own DB is still untrusted input.
```

**NoSQL (operator) injection:**

```javascript
// Express parses JSON bodies into objects, so this:
//   {"username": "admin", "password": {"$ne": ""}}
// turns into a query that matches the admin with ANY password.
const user = await users.findOne({ username: req.body.username, password: req.body.password });

// Fix 1: validate types at the boundary (schema validation: zod, joi, JSON Schema)
// Fix 2: force equality semantics when building queries
const user = await users.findOne({ username: { $eq: String(req.body.username) } });
// Fix 3: never compare passwords in the query; fetch the user, then verify a password HASH
const ok = user && await argon2.verify(user.passwordHash, String(req.body.password));
// Also disable server-side JavaScript ($where, mapReduce) unless you need it.
```

**Layer 1: application code — bound parameters everywhere:**

```python
# psycopg 3
cur.execute("SELECT id, name FROM users WHERE name = %s AND status = %s", (name, status))

# SQLAlchemy 2.0
stmt = select(User).where(User.name == name)                      # ORM builds parameters
stmt = text("SELECT * FROM users WHERE name = :name").bindparams(name=name)

# Django
User.objects.filter(name=name)
User.objects.raw("SELECT * FROM users WHERE name = %s", [name])   # params, not f-strings
```

```python
# Identifiers can't be parameters: allowlist them
SORTABLE = {"created_at": "created_at", "name": "name"}
DIRECTIONS = {"asc": "ASC", "desc": "DESC"}

def search_users(cur, name: str, sort: str, direction: str):
    col = SORTABLE.get(sort, "created_at")
    dir_ = DIRECTIONS.get(direction.lower(), "DESC")
    cur.execute(f"SELECT id, name FROM users WHERE name ILIKE %s ORDER BY {col} {dir_} LIMIT 50",
                (f"%{name}%",))
    # (psycopg also offers sql.Identifier for safe quoting of dynamic identifiers)
```

Escaping functions are not a substitute: they depend on the connection's character set (the classic GBK multi-byte bypass of `mysql_real_escape_string`) and on every developer remembering every call site.

**Stored procedures aren't automatically safe:**

```sql
-- Vulnerable: dynamic SQL inside the procedure (SQL Server)
CREATE PROCEDURE search_users @name NVARCHAR(100) AS
    EXEC('SELECT * FROM users WHERE name = ''' + @name + '''');

-- Safe: static SQL, or sp_executesql with parameters
CREATE PROCEDURE search_users @name NVARCHAR(100) AS
    SELECT * FROM users WHERE name = @name;
```

**Layer 2: database hardening (limits the blast radius):**

```sql
-- The app role gets DML on what it needs, nothing else (no DDL, no superuser)
CREATE ROLE app_user LOGIN;
GRANT SELECT, INSERT, UPDATE, DELETE ON app.users TO app_user;
GRANT SELECT ON app.orders TO app_user;
-- Separate migration role owns the schema and runs DDL during deploys only.

-- Since PostgreSQL 15, ordinary users can no longer CREATE in the public schema by
-- default; on older versions revoke it:
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Row-level security: even an injected query only sees the current tenant's rows
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;          -- applies to the table owner too
CREATE POLICY tenant_isolation ON users
    USING (tenant_id = current_setting('app.tenant_id')::int);
-- Superusers and roles with BYPASSRLS still bypass it; the app role must have neither.
```

Also: statement timeouts (limit time-based blind extraction and runaway queries), and alerts on SQL syntax errors from the app role (attack probes cause them).

**Layer 3: WAF (virtual patch, not a fix):**

- Managed rules (OWASP Core Rule Set's libinjection-based rule 942100, AWS `AWSManagedRulesSQLiRuleSet`, Cloudflare managed rules) block common payloads while the code fix ships.
- Bypasses are routine: encodings, comments inside keywords (`UN/**/ION`), case games, JSON-wrapped payloads, HTTP parameter pollution. Run in block mode for the vulnerable endpoint, and log mode elsewhere to tune false positives.

**Finding the rest of the bug class:**

```bash
# Static: string-built SQL in Python
semgrep --config p/python --config p/sql-injection .
# Dynamic, against staging only, with permission
sqlmap -u "https://staging.example.com/search?name=test" --batch --level 3
```

Also return generic errors to clients and log details server-side (without logging parameter values that contain PII or secrets), since detailed SQL errors make injection far easier.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Parameterized queries** | The only complete defence; allowlists for identifiers; why escaping isn't enough |
| **Blind SQLi** | Boolean/time-based exfiltration, ~7 requests per character |
| **Second-order injection** | Treats data from its own database as untrusted |
| **NoSQL injection** | Operator injection ($ne, $gt, $where), type validation, hash comparison |
| **Defense in depth** | Least privilege, RLS (FORCE, BYPASSRLS caveats), WAF as virtual patch, SAST/DAST |

---

## 4. Encryption at Rest & In Transit

**Q:** "Design the encryption strategy for a healthcare application storing PHI (Protected Health Information). Cover TLS, database encryption, key management, and the difference between encryption in transit vs at rest vs in use. The security team is concerned about key compromise — how do you rotate keys without decrypting all data?"

**What They're Really Testing:** Whether you understand encryption as a layered system (not a single knob), know the difference between encryption types, and have practical key management strategies at scale.

### Answer

!!! tip "30-second answer"
    **In transit**: TLS 1.3 everywhere (1.2 only with AEAD suites for legacy clients), mTLS between services for workload identity, HSTS at the edge; hybrid post-quantum key exchange (X25519MLKEM768) comes free with current browsers and OpenSSL 3.5. **At rest**: storage encryption (EBS/RDS with KMS keys) protects against lost disks and snapshots, but anyone who can query the database sees plaintext, so the most sensitive PHI fields also get **application-level envelope encryption**: a per-record data key (DEK) encrypts the field with AES-GCM, and a KMS-held key-encryption key (KEK) encrypts the DEK. **Rotation**: rotating the KEK only re-wraps the small DEKs (or, with KMS automatic rotation, nothing at all), so terabytes of data are never re-encrypted. If a **DEK** or the data itself may have leaked, re-wrapping doesn't help: those records must be re-encrypted. **In use**: confidential computing (AMD SEV-SNP, Intel TDX, AWS Nitro Enclaves) for the few workloads that justify it.

**The three states of data:**

| | In transit | At rest | In use |
|---|---|---|---|
| Mechanism | TLS 1.3, mTLS, HSTS | Disk/volume encryption, TDE, field-level envelope encryption | Confidential VMs (SEV-SNP, TDX), enclaves (Nitro Enclaves, SGX), confidential GPUs |
| Protects against | Eavesdropping, tampering, MITM | Stolen disks, leaked snapshots/backups, (field-level) DB admins and SQL injection | Malicious or compromised host/hypervisor operators |
| Doesn't protect against | A compromised endpoint | A compromised application with key access | Bugs in the workload itself |

**In transit:**

- TLS 1.3 handshake is **1 RTT** (TLS 1.2: 2), forward secrecy is mandatory, and downgrade protection is built in (the server signals a downgrade in its random value).
- Cipher suites: `TLS_AES_128_GCM_SHA256`, `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`. For TLS 1.2, ECDHE + AEAD (GCM/ChaCha20) only; no CBC, RC4, 3DES; TLS 1.0/1.1 disabled.
- **Post-quantum:** hybrid `X25519MLKEM768` key exchange is on by default in Chrome, Firefox, Apple platforms, Cloudflare and OpenSSL 3.5+, protecting recorded traffic from future quantum decryption ("harvest now, decrypt later"), relevant for long-lived PHI.

```python
import ssl

ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)   # server-side context
ctx.minimum_version = ssl.TLSVersion.TLSv1_2
ctx.set_ciphers("ECDHE+AESGCM:ECDHE+CHACHA20")   # affects TLS 1.2 only; 1.3 suites are all AEAD
ctx.load_cert_chain("server.crt", "server.key")
```

```nginx
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-CHACHA20-POLY1305;
ssl_prefer_server_ciphers off;    # Mozilla's current guidance: let clients pick among strong suites
add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
```

**mTLS between services:** gives each workload a cryptographic **identity** (SPIFFE IDs, mesh-issued short-lived certs via Istio/Linkerd/Vault) and encrypts every hop. It does **not** replace authorization or end-user context: services still check "is service A allowed to call this endpoint for this user?", using the propagated user token.

**At rest, in layers:**

| Layer | Example | Protects against | Doesn't protect against |
|---|---|---|---|
| Storage / volume | EBS, RDS storage encryption, LUKS | Physical theft, snapshot sharing mistakes (if the key policy blocks it) | Anyone who can connect to the DB or read files on the running host |
| Database TDE | SQL Server/Oracle TDE; for PostgreSQL, Percona's `pg_tde` extension or vendor forks (core PostgreSQL has none) | Copied data files and backups | DB users, SQL injection |
| **Field-level (application) envelope encryption** | SSN, diagnosis codes, notes | DB admins, SQL injection, log/backup/analytics leaks | A compromised application that can call KMS |

Note: `pgcrypto` is a library of SQL functions for field-level encryption inside the database, not TDE; keys passed to it travel in SQL and can end up in logs, so application-side encryption is usually preferable.

**Envelope encryption with KMS and AES-GCM (tested with a stub KMS):**

```python
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EnvelopeEncryption:
    def __init__(self, kms_client, kek_id: str):
        self.kms = kms_client          # e.g. boto3.client("kms")
        self.kek_id = kek_id           # KEK never leaves KMS

    def encrypt(self, plaintext: bytes, record_id: str) -> dict:
        ctx = {"table": "patients", "record_id": record_id}   # KMS encryption context:
        dk = self.kms.generate_data_key(KeyId=self.kek_id,     # logged in CloudTrail and
                                        KeySpec="AES_256",     # required again to decrypt
                                        EncryptionContext=ctx)
        nonce = os.urandom(12)                                  # unique per encryption
        ciphertext = AESGCM(dk["Plaintext"]).encrypt(nonce, plaintext, record_id.encode())
        # record_id as associated data: a ciphertext copied to another row fails to decrypt
        return {"ciphertext": ciphertext, "nonce": nonce,
                "encrypted_dek": dk["CiphertextBlob"], "kek_id": self.kek_id}

    def decrypt(self, blob: dict, record_id: str) -> bytes:
        ctx = {"table": "patients", "record_id": record_id}
        dek = self.kms.decrypt(CiphertextBlob=blob["encrypted_dek"],
                               EncryptionContext=ctx)["Plaintext"]
        return AESGCM(dek).decrypt(blob["nonce"], blob["ciphertext"], record_id.encode())
```

At scale, calling KMS per record is slow and costly: cache plaintext DEKs briefly in memory (the AWS Encryption SDK's caching materials manager does this with limits on age and use count), or use one DEK per tenant/partition. Searching encrypted fields needs a separate design: a keyed hash (HMAC) column for exact-match lookups, or tokenization.

**Key rotation and compromise — distinguish three cases:**

| Situation | What to do | Data re-encryption? |
|---|---|---|
| Routine KEK rotation | AWS KMS automatic rotation (configurable period, plus on-demand rotation) keeps the same key ID and retains old key material, so old DEKs still decrypt. Or create a new KEK and `ReEncrypt` the stored DEKs in a background job | **No** |
| KEK suspected compromised (e.g. leaked credentials with `kms:Decrypt`) | Revoke access first (key policy, grants, IAM), review CloudTrail for Decrypt calls, re-wrap all DEKs under a new KEK, then disable and schedule deletion of the old key (7–30 day waiting period; `ScheduleKeyDeletion` takes a key ID or ARN, not an alias) | No, unless audit shows Decrypt calls on your DEKs |
| DEKs or plaintext exposed (memory dump, logs) | The DEK itself is compromised: generate new DEKs and **re-encrypt the affected records** | **Yes**, for affected records |

**Protecting the keys:** least-privilege key policies (only the PHI service role can `Decrypt`, only with the right encryption context), separate keys per environment and data class, CloudTrail alerts on unusual Decrypt volume, and dual control for key deletion. With KMS `Decrypt` permission and the ciphertext, an attacker **can** decrypt; envelope encryption reduces exposure, it doesn't make KMS access harmless.

**In use — confidential computing:** AMD SEV-SNP and Intel TDX encrypt and integrity-protect a whole VM's memory against the hypervisor and host operators, with remote **attestation** so a key service releases keys only to a verified VM image. AWS Nitro Enclaves isolate a process with no network or persistent storage, again gated by attestation. Use them for multi-party analytics on PHI or key-handling services; they add operational complexity and have had side-channel research findings, so they complement, not replace, the controls above.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Envelope encryption** | DEK vs KEK, AES-GCM with associated data, encryption context |
| **Three states** | Clearly distinguishes in-transit, at-rest (and its layers), in-use |
| **Key rotation** | KMS automatic rotation vs re-wrap; when data must be re-encrypted |
| **mTLS** | Workload identity, not a replacement for authorization |
| **Currency** | TLS 1.3 details, hybrid PQ key exchange, SEV-SNP/TDX/Nitro Enclaves |

---

## 5. Secrets Management & Vault

**Q:** "Design a secrets management strategy for a 200-microservice architecture. How do you handle database credential rotation, API key distribution, and preventing secrets from leaking into logs or source control?"

**What They're Really Testing:** Whether you understand that secrets management is a platform problem, not a config problem, and know production-grade solutions like HashiCorp Vault.

### Answer

!!! tip "30-second answer"
    Treat secrets as a **service**, not config. Workloads authenticate with their **platform identity** (Kubernetes service account token, AWS IAM role, SPIFFE ID), never with a bootstrap secret, and fetch short-lived credentials from a secrets manager (HashiCorp Vault or its open-source fork OpenBao, AWS Secrets Manager, GCP Secret Manager). Prefer **dynamic secrets** (a unique DB user per service instance with a TTL) and cloud **workload identity federation** over static keys, so there's little to leak and nothing long-lived to rotate. Deliver secrets through an agent or CSI driver to a memory-backed file, not env vars or images. Prevent leaks with pre-commit and push-protection scanning, log redaction by construction (secret types that don't print), and audit logs on every read.

**What goes wrong without a platform:**

```yaml
# config.yaml committed to the repo
DATABASE_URL: "postgresql://admin:SuperSecret1!@prod-db:5432/mydb"
STRIPE_KEY:   "sk_live_..."
# Leaks via: git history (forever, even after deletion), CI logs, container image layers,
# crash dumps and error pages, `env` in debug endpoints, /proc/<pid>/environ,
# copied .env files on laptops. And it never gets rotated because nobody knows who uses it.
```

**Architecture for 200 services:**

```
Pod (service account "orders")
  │ 1. projected, audience-bound SA token (short-lived JWT)
  ▼
Vault / OpenBao  ── Kubernetes auth: validates the token with the API server,
  │                 maps (namespace, service account) → policy "orders"
  │ 2. issues a Vault token with TTL + policy
  │ 3. orders reads database/creds/orders-rw → a NEW Postgres user, TTL 1h
  ▼
Vault Agent sidecar / Secrets Store CSI driver
  │ 4. renders creds to a tmpfs file, renews the lease, re-renders on rotation
  ▼
App reads the file (and reloads on change)        Audit device logs every read
```

**Dynamic database credentials:**

```bash
vault secrets enable database
vault write database/config/orders-db \
    plugin_name=postgresql-database-plugin \
    connection_url="postgresql://{{username}}:{{password}}@orders-db:5432/orders" \
    username="vault_admin" password="..." allowed_roles="orders-rw"
vault write -f database/rotate-root/orders-db      # now only Vault knows the admin password

vault write database/roles/orders-rw db_name=orders-db \
    creation_statements="CREATE ROLE \"{{name}}\" LOGIN PASSWORD '{{password}}' VALID UNTIL '{{expiration}}' IN ROLE orders_rw;" \
    default_ttl=1h max_ttl=24h
```

```python
import hvac

client = hvac.Client(url="https://vault.internal:8200")
with open("/var/run/secrets/tokens/vault-token") as f:          # projected SA token
    client.auth.kubernetes.login(role="orders", jwt=f.read())

resp = client.secrets.database.generate_credentials(name="orders-rw")
username, password = resp["data"]["username"], resp["data"]["password"]
lease_id, ttl = resp["lease_id"], resp["lease_duration"]        # lease info is top-level
```

Operational details that matter:

- **Connection pools vs TTLs:** a pool holding connections opened with credentials that expire will fail on reconnect. Renew the lease, or re-read credentials and recycle connections before `max_ttl` (most pools support a max connection lifetime).
- **Grant through a group role** (`IN ROLE orders_rw`): objects created by a short-lived user would otherwise be owned by it and break when it's dropped.
- **Static secrets** (third-party API keys) can't be dynamic: store them in the secrets manager, rotate on a schedule with **two valid keys** overlapping (issue new, deploy, revoke old), and scope them as narrowly as the vendor allows.
- **Cloud access without keys:** IRSA / EKS Pod Identity, GKE Workload Identity, and GitHub Actions OIDC → cloud roles remove long-lived cloud credentials entirely.
- **Licensing note:** HashiCorp moved Vault to the Business Source License in 2023 (and was acquired by IBM in 2025); **OpenBao** is the Linux Foundation fork under MPL 2.0 with a compatible API.

**Short-lived TLS certificates:** issue workload certs from an internal CA with short TTLs (hours to days) via the mesh, cert-manager, or Vault PKI, and renew at about two-thirds of the lifetime with retries and backoff. Monitor expiry; expired internal certs are a classic self-inflicted outage.

**Preventing leaks:**

```python
# Make secrets hard to log by accident: a type that never prints its value
from dataclasses import dataclass


@dataclass(frozen=True)
class Secret:
    _value: str

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(****)"

    __str__ = __repr__


db_password = Secret(password)
logger.info("connecting with %s", db_password)   # → "connecting with Secret(****)"
```

- **Source control:** pre-commit scanning (gitleaks, trufflehog), GitHub secret scanning **push protection**, and if a secret is committed, **rotate it**; rewriting history isn't enough because clones and forks keep it.
- **Logs:** redaction at the logging layer (structured logs with deny-listed field names) as a backstop, plus the typed wrapper above as the primary control.
- **Images and CI:** no secrets in Dockerfiles (`--mount=type=secret` for build-time secrets), CI jobs get short-lived OIDC credentials, and CI egress is restricted (Q9).
- **Audit:** every secret read is logged with the workload identity; alert on unusual readers or volumes.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Identity-based access** | Workload identity (K8s auth, IAM roles, OIDC), no bootstrap secrets |
| **Dynamic vs static** | Dynamic DB creds with TTLs; overlapping-key rotation for static secrets |
| **Operational detail** | Pools vs TTLs, ownership via group roles, agent/CSI delivery |
| **Leak prevention** | Push protection, rotate-on-leak, typed secrets, redaction, no secrets in images |
| **Currency** | OpenBao/BSL change, cloud workload identity federation |

---

## 6. Rate Limiting & DDoS Protection

**Q:** "Design a multi-layered rate limiting and DDoS protection system for a public API serving 100K requests/second. The system must distinguish between a legitimate flash crowd and a coordinated botnet attack. Cover application-level, infrastructure-level, and edge protection."

**What They're Really Testing:** Whether you understand rate limiting as a distributed systems problem and can layer defenses at different levels of the stack.

### Answer

!!! tip "30-second answer"
    Defend in layers, cheapest first. **Edge/network** (Cloudflare, AWS Shield + CloudFront, Akamai): absorb volumetric L3/L4 floods with anycast capacity, SYN cookies and scrubbing, and filter L7 floods with WAF rules, bot management and challenges. **Gateway**: per-API-key / per-user / per-IP limits with a token bucket or GCRA, plus per-endpoint cost-based limits for expensive operations. **Service**: concurrency limits and load shedding so overload degrades gracefully. A flash crowd and a botnet both look like "lots of traffic"; distinguish them by **behaviour and reputation** (request mix, session history, TLS/HTTP fingerprints, challenge pass rates), and design so legitimate crowds are served from cache even when you can't tell the difference.

**Layer 1: edge and network:**

| Attack | Defence |
|---|---|
| Volumetric (UDP/DNS/NTP amplification, multi-Tbps) | Anycast scrubbing capacity at the CDN/DDoS provider (Cloudflare including Magic Transit for whole IP prefixes, AWS Shield Advanced, Akamai Prolexic); you can't absorb this in your own VPC |
| SYN flood | SYN cookies (stateless handshake), provider-side filtering |
| L7 HTTP floods, including HTTP/2 "Rapid Reset" (2023) style protocol abuse | WAF rate-based rules, bot management, JS/managed challenges, patched HTTP/2 servers with stream limits |
| Origin bypass | Lock the origin to the CDN (allowlist provider IPs or authenticated origin pulls / mTLS), so attackers can't go around the edge |

**Layer 2: rate limiting algorithms:**

| Algorithm | Behaviour | Trade-offs |
|---|---|---|
| Fixed window counter | `INCR key:minute` | Cheap; allows 2× bursts at window boundaries |
| Sliding window log | Sorted set of timestamps per key | Exact; memory grows with request rate (bad at 100K rps) |
| Sliding window counter | Weighted mix of current and previous window counts | Cheap and close enough; widely used |
| Token bucket | Tokens refill at rate r up to capacity b; each request takes one | Allows controlled bursts; two numbers to store |
| GCRA (generic cell rate algorithm) | Token bucket expressed as one "theoretical arrival time" | One value per key; used by redis-cell, Envoy-style limiters |

```python
import threading
import time


class TokenBucket:
    """In-process token bucket: capacity = burst size, refill_rate = sustained rate."""

    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = float(capacity)
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def try_acquire(self, cost: float = 1.0) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.refill_rate)
            self.last = now
            if self.tokens >= cost:
                self.tokens -= cost
                return True
            return False
```

**Distributed limiting (Redis, atomic Lua, server-side clock):**

```python
# Token bucket in Redis: one hash per key, evaluated atomically
TOKEN_BUCKET_LUA = """
local capacity = tonumber(ARGV[1])
local rate     = tonumber(ARGV[2])          -- tokens per second
local cost     = tonumber(ARGV[3])
local t        = redis.call('TIME')         -- Redis clock: no skew between app servers
local now      = tonumber(t[1]) + tonumber(t[2]) / 1e6
local state    = redis.call('HMGET', KEYS[1], 'tokens', 'ts')
local tokens   = tonumber(state[1]) or capacity
local ts       = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + (now - ts) * rate)
local allowed = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
end
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', KEYS[1], math.ceil(capacity / rate) + 1)
return allowed
"""

bucket = redis_client.register_script(TOKEN_BUCKET_LUA)

def allow(key: str, capacity: int, rate: float, cost: int = 1) -> bool:
    return bucket(keys=[f"rl:{{{key}}}"], args=[capacity, rate, cost]) == 1
    # {key} hash tag keeps the key on one Redis Cluster slot
```

Design decisions at 100K rps:

- **Don't put a global limit on one Redis key**: that's a hot key. Enforce global/system-wide limits locally per gateway node (divide the budget by node count) or with approximate counters; use Redis for per-tenant fairness.
- **Fail open or closed?** If Redis is down, most APIs fail **open** with a local fallback limiter rather than taking the API down.
- **Cost-based limits:** a search or export should cost more tokens than a GET by ID.
- **Identify the client correctly:** per API key/user for authenticated traffic; per IP only as a coarse backstop (carrier-grade NAT puts thousands of users behind one IP; IPv6 users can rotate through a /64, so limit per /64 prefix).

**Tiers:**

```yaml
limits:
  per_api_key:      { rate: 100/s,  burst: 200 }      # fairness between customers
  per_user_write:   { rate: 10/min }                  # abuse of mutations
  per_ip_anonymous: { rate: 60/min }                  # unauthenticated endpoints, login
  login_per_account:{ rate: 5/min, then: challenge }  # credential stuffing / brute force
  export_endpoint:  { concurrency: 2 per tenant }     # expensive operations
service_protection:
  max_inflight_requests: adaptive                     # load shedding (Q8 in Concurrency)
```

**Flash crowd vs botnet:**

| Signal | Flash crowd | Botnet / L7 flood |
|---|---|---|
| Request mix | Concentrated on the popular page, then normal navigation (assets, follow-up pages) | Hammers one expensive endpoint or random cache-busting URLs |
| Sessions | Mix of returning users with cookies, logged-in sessions | Few cookies or sessions; sessions don't progress |
| Client fingerprints | Diverse but realistic browser TLS/HTTP fingerprints (e.g. JA4) | Repeated fingerprints from automation libraries; user agent doesn't match TLS fingerprint |
| Network origin | Residential and mobile ISPs, matching your user geography | Data-center ASNs, or residential **proxy** networks (hard), unusual geography |
| Challenges | Pass JS/managed challenges | Fail or solve them at suspicious rates |
| Referrers | Social, news, search | Absent or forged |

Modern botnets use residential proxies and real browsers, so no single signal is decisive. Combine signals into a risk score at the edge, apply **graduated responses** (allow → rate limit → challenge → block), and protect the system regardless: serve flash crowds from the CDN cache (`stale-while-revalidate`), queue or waiting-room the expensive path (checkout), and shed load before the origin falls over.

**Response format:**

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 30
RateLimit-Policy: "default";q=100;w=60
RateLimit: "default";r=0;t=30
Content-Type: application/problem+json

{"type": "https://api.example.com/errors/rate-limited", "title": "Too many requests", "status": 429}
```

(`RateLimit`/`RateLimit-Policy` are the IETF httpapi draft headers; many APIs still use the older `X-RateLimit-*` convention.)

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-layer approach** | Edge (volumetric, L7), gateway limits, service load shedding, origin lock-down |
| **Algorithm choice** | Token bucket/GCRA vs windows; memory and accuracy trade-offs |
| **Distributed implementation** | Atomic Lua, server-side time, hot keys, fail-open policy, cluster hash tags |
| **False positive prevention** | Behavioural/fingerprint signals, graduated responses, cache-first for crowds |

---

## 7. Authentication: Session vs Token vs Passwordless

**Q:** "You're designing authentication for a new fintech application handling high-value transactions. Compare and contrast session-based, token-based (JWT), and passwordless (WebAuthn/passkeys) authentication. Which would you choose and why?"

**What They're Really Testing:** Understanding of the fundamental tradeoffs between stateful vs stateless auth, and knowledge of the emerging passwordless standard (WebAuthn).

### Answer

!!! tip "30-second answer"
    These answer two different questions. **Passkeys/WebAuthn** (vs passwords and OTPs) is how the user **proves who they are**: a per-site key pair where the private key never leaves the authenticator and signatures are bound to your domain, so it's **phishing-resistant** and there's no shared secret to steal or stuff. **Sessions vs JWTs** is how the user **stays authenticated** afterwards. For fintech: passkeys as the primary login, a server-side session (opaque ID in a `__Host-` cookie) for the web app so revocation is instant, short-lived sender-constrained tokens (DPoP) for mobile/API clients, and **step-up** re-authentication with a fresh passkey assertion for high-risk actions like adding a payee. Keep passwords only as a migration path, hashed with Argon2id, plus phishing-resistant MFA.

**Two layers, often confused:**

| Layer | Options | Key property |
|---|---|---|
| Authentication (prove identity) | Password, password + OTP/push, **passkey (WebAuthn)**, federated (OIDC) | Phishing resistance, resistance to credential stuffing |
| Session (stay signed in) | Server-side session, self-contained JWT, opaque token + introspection, DPoP-bound token | Revocation speed, scalability, theft resistance |

**Server-side sessions:**

```python
@router.post("/login/complete")
async def login_complete(user: User, response: Response):
    session_id = secrets.token_urlsafe(32)                      # 256 bits, unguessable
    await redis.set(f"session:{session_id}",
                    json.dumps({"uid": user.id, "aal": 2, "auth_time": int(time.time())}),
                    ex=15 * 60)                                  # idle timeout, refreshed on use
    response.set_cookie(
        "__Host-session", session_id,                            # __Host-: Secure, Path=/, no Domain
        httponly=True, secure=True, samesite="lax", path="/",
    )
    # Always issue a NEW session ID at login (prevents session fixation).

# Revocation: delete the key. "Log out everywhere": index sessions by user id and delete all.
```

**Self-contained tokens (JWT) for API/mobile clients:**

```python
def issue_tokens(user) -> dict:
    access = issue_access_token(str(user.id), CURRENT_KID, SIGNING_KEY)   # Q1: ES256, 10 min
    refresh = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO refresh_tokens (token_hash, user_id, family_id, expires_at)"
        " VALUES (%s, %s, %s, now() + interval '30 days')",
        (sha256(refresh), user.id, uuid.uuid4()),
    )
    return {"access_token": access, "refresh_token": refresh, "expires_in": 600}


def refresh(refresh_token: str) -> dict:
    row = db.fetch_one("SELECT * FROM refresh_tokens WHERE token_hash = %s", (sha256(refresh_token),))
    if row is None or row.expires_at < now():
        raise Unauthorized()
    if row.used_at is not None:                    # reuse = theft: kill the whole family
        db.execute("UPDATE refresh_tokens SET revoked_at = now() WHERE family_id = %s",
                   (row.family_id,))
        raise Unauthorized()
    db.execute("UPDATE refresh_tokens SET used_at = now() WHERE id = %s", (row.id,))
    return issue_rotated_tokens(row.user_id, row.family_id)   # new refresh token, same family
```

**Passkeys with WebAuthn (py_webauthn 2.x/3.x API):**

```python
from webauthn import (generate_registration_options, verify_registration_response,
                      generate_authentication_options, verify_authentication_response,
                      options_to_json)
from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, ResidentKeyRequirement,
                                      UserVerificationRequirement, PublicKeyCredentialDescriptor)

RP_ID, ORIGIN = "fintech-app.com", "https://fintech-app.com"

@router.post("/passkeys/register/options")
async def register_options(user: User):
    opts = generate_registration_options(
        rp_id=RP_ID, rp_name="Fintech App",
        user_id=user.webauthn_handle,          # random bytes, not the email or DB id
        user_name=user.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,             # discoverable = passkey
            user_verification=UserVerificationRequirement.REQUIRED,   # biometric/PIN
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c.credential_id)
                             for c in await user_credentials(user)],
    )
    await redis.set(f"webauthn:reg:{user.id}", opts.challenge, ex=300)
    return options_to_json(opts)

@router.post("/passkeys/register/verify")
async def register_verify(user: User, credential: dict):
    challenge = await redis.getdel(f"webauthn:reg:{user.id}")       # single use
    reg = verify_registration_response(
        credential=credential, expected_challenge=challenge,
        expected_rp_id=RP_ID, expected_origin=ORIGIN,
        require_user_verification=True,      # default is False: set it explicitly
    )
    await save_credential(user, reg.credential_id, reg.credential_public_key, reg.sign_count)

@router.post("/passkeys/login/options")
async def login_options(login_attempt_id: str):
    # Discoverable credentials: no username needed, no allow-list → no account enumeration,
    # and the browser can offer passkeys in the username field's autofill ("conditional UI").
    opts = generate_authentication_options(
        rp_id=RP_ID, user_verification=UserVerificationRequirement.REQUIRED)
    await redis.set(f"webauthn:auth:{login_attempt_id}", opts.challenge, ex=300)
    return options_to_json(opts)

@router.post("/passkeys/login/verify")
async def login_verify(login_attempt_id: str, credential: dict):
    challenge = await redis.getdel(f"webauthn:auth:{login_attempt_id}")
    stored = await find_credential(credential["rawId"])               # identifies the user
    auth = verify_authentication_response(
        credential=credential, expected_challenge=challenge,
        expected_rp_id=RP_ID, expected_origin=ORIGIN,
        credential_public_key=stored.public_key,
        credential_current_sign_count=stored.sign_count,
        require_user_verification=True,
    )
    # The library rejects a non-increasing NON-ZERO counter (possible cloned authenticator).
    # Synced passkeys (iCloud Keychain, Google Password Manager) always report 0; don't treat
    # 0 as an attack or you'll lock out most passkey users.
    await update_sign_count(stored, auth.new_sign_count)
    return await create_session(stored.user)
```

Why passkeys resist phishing: the browser puts the **origin** into the signed client data and the authenticator scopes the key to the **RP ID**, so a look-alike domain can't obtain a valid assertion for your site, however convincing the page.

**Comparison:**

| Aspect | Server sessions | Self-contained JWT | Passkeys (WebAuthn) |
|---|---|---|---|
| What it is | Session mechanism | Session/token mechanism | Authentication method |
| Revocation | Instant (delete) | At expiry unless you add state (Q1) | Remove the credential; existing sessions handled by the session layer |
| Scaling | Shared store lookup per request (cheap with Redis) | Local verification | Server stores public keys only |
| Theft impact | Stolen cookie works until revoked/expired (mitigate: HttpOnly, short idle timeout, device binding) | Stolen bearer token works until expiry (mitigate: DPoP) | Nothing reusable to steal from the server; phishing-resistant |
| Fits | Browser apps | Mobile/API clients, service-to-service | Primary login and step-up everywhere |

**If you keep passwords (migration period):**

- Hash with **Argon2id** (OWASP minimum: m = 19 MiB, t = 2, p = 1; tune upward to ~0.5 s on your hardware), or bcrypt (cost ≥ 10, 72-byte input limit) for legacy; never fast hashes.
- **NIST SP 800-63B-4** (final, 2025): at least 15 characters when the password is the only factor, at least 8 when it's part of MFA; accept at least 64; no composition rules; no forced periodic rotation; check new passwords against breached-password lists; allow paste and password managers. It also recognises syncable passkeys for AAL2.
- Defend login endpoints against credential stuffing: per-account and per-IP throttling, breached-password checks (k-anonymity range API of Have I Been Pwned), and risk-based challenges.

**Recommendation for fintech:**

1. **Passkeys first**, with recovery designed as carefully as login (recovery is where account takeover happens: verified identity checks, cooling-off periods, notifications).
2. **Web**: server-side sessions in `__Host-` cookies, idle timeout ~15 min, absolute timeout, rotation on privilege change.
3. **Mobile/API**: short-lived access tokens bound with **DPoP** (RFC 9449) to a key in the device's secure enclave/keystore, plus rotating refresh tokens.
4. **Step-up**: fresh WebAuthn assertion (check `auth_time` / authentication context) for transfers, new payees, changing contact details; consider transaction signing that shows the amount and payee.
5. Monitoring: anomalous device, geography or velocity triggers step-up or holds.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Layering** | Separates "how you authenticate" from "how you stay authenticated" |
| **Tradeoff analysis** | Stateful vs stateless revocation, theft impact, DPoP |
| **WebAuthn depth** | Challenge single use, origin/RP binding, UV required, sign-count nuance for synced passkeys |
| **Password hygiene** | Argon2id parameters, NIST 800-63B-4 rules, credential-stuffing defences |
| **Practical recommendation** | Passkeys + sessions + step-up, recovery flow, based on the threat model |

---

## 8. CORS, CSRF, and SameSite Cookies

**Q:** "After migrating your frontend from 'app.example.com' to 'app.newdomain.com', users report they can't log in — their session cookie isn't being sent. Walk through the diagnosis and fix, covering CORS, CSRF, and SameSite cookies."

**What They're Really Testing:** Whether you understand the browser security model (same-origin policy) and can debug real-world cross-origin authentication issues.

### Answer

!!! tip "30-second answer"
    The key word is **site**, not origin. `app.example.com` → `api.example.com` was cross-**origin** but **same-site** (same registrable domain), so a `SameSite=Lax` session cookie was sent on `fetch` calls. `app.newdomain.com` → `api.example.com` is **cross-site**: `Lax` cookies aren't sent on cross-site subresource requests, and the cookie is now a **third-party cookie**, which Safari blocks outright and Firefox partitions. Setting `SameSite=None; Secure` plus credentialed CORS makes it work only in some browsers. The robust fix is to make the API **same-site** again: serve it as `api.newdomain.com` (or proxy `/api` through the frontend's host, the backend-for-frontend pattern) and issue the cookie there. Then CSRF protection: `SameSite=Lax`, a token or Fetch Metadata check for state-changing requests, and strict CORS.

**Diagnosis checklist:**

```
DevTools → Network → the failing API request
  - Cookie header missing?  → Application tab shows the cookie with a warning icon:
      "blocked because SameSite=Lax and the request is cross-site"  or
      "blocked: third-party cookie"
  - Is fetch() using credentials: 'include'? (default 'same-origin' never sends cookies cross-origin)
  - CORS error in console? → response lacks Access-Control-Allow-Origin: https://app.newdomain.com
      and Access-Control-Allow-Credentials: true (and "*" is not allowed with credentials)
  - Preflight (OPTIONS) failing? → custom headers / JSON content type trigger it
```

**Definitions that decide everything:**

| Term | Defined by | Example |
|---|---|---|
| Origin | scheme + host + port | `https://app.example.com` ≠ `https://api.example.com` |
| Site | scheme + registrable domain (eTLD+1, per the Public Suffix List) | `https://example.com` covers both of the above |
| CORS | Origin-based: may JavaScript **read** the response? | Doesn't decide whether cookies are **sent** |
| SameSite | Site-based: is the cookie **sent** with this request? | |

**SameSite modes:**

| Mode | Sent on | Notes |
|---|---|---|
| `Strict` | Same-site requests only | Even top-level navigation from an email link arrives without the cookie |
| `Lax` | Same-site requests + cross-site **top-level GET navigations** | Chrome/Edge treat cookies without `SameSite` as Lax; Firefox and Safari don't apply that default |
| `None` (requires `Secure`) | All requests, including cross-site | Subject to third-party cookie blocking: Safari (ITP) blocks, Firefox partitions per top-level site (Total Cookie Protection), Chrome still allows them by default after Google abandoned its 2024–25 deprecation plan, but users can block them |

**Fix A (recommended): make it same-site again**

```
Option 1: api.newdomain.com → cookie set by api.newdomain.com (or Domain=newdomain.com)
Option 2: app.newdomain.com/api/* reverse-proxied to the backend → cookie is first-party,
          no CORS at all (same origin)
```

```python
response.set_cookie(
    "__Host-session", session_id,    # host-only, Secure, Path=/ (hardest to tamper with)
    httponly=True, secure=True, samesite="lax", path="/",
)
```

**Fix B (if the API must stay on another site): credentialed CORS + `SameSite=None`**

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://app.newdomain.com"],   # exact origins; never reflect arbitrary Origin
    allow_credentials=True,                        # → Access-Control-Allow-Credentials: true
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
    max_age=600,                                   # browsers cap preflight caching (Chrome: 2 h)
)

response.set_cookie("session", session_id, httponly=True, secure=True,
                    samesite="none", path="/")     # still blocked by Safari; partitioned in Firefox
```

```javascript
await fetch("https://api.example.com/transfer", {
  method: "POST",
  credentials: "include",                          // send cookies cross-origin
  headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
  body: JSON.stringify(data),
});
```

Common CORS mistakes: reflecting the request's `Origin` header back with credentials allowed (any site can read authenticated responses), allowing `null` origin, regex allowlists like `.*example.com` that match `evilexample.com`.

**CSRF: what still protects you:**

```
Attack: user is logged in to bank.com; evil.com auto-submits
  <form action="https://bank.com/transfer" method="POST">
The browser attaches bank.com cookies if their SameSite policy allows it.
```

| Defence | Notes |
|---|---|
| `SameSite=Lax`/`Strict` session cookies | Blocks cross-site POSTs carrying the cookie. Not sufficient alone: same-site attackers (a compromised subdomain), GET endpoints with side effects, and browsers without Lax-by-default |
| **Fetch Metadata** check | Reject state-changing requests with `Sec-Fetch-Site: cross-site` (allow `same-origin`/`same-site` and `none` for typed URLs); supported by all major browsers |
| Synchronizer token / **signed** double-submit token | Token bound to the session (HMAC of session ID), sent in a header or form field. A naive double-submit cookie (unsigned random value) can be defeated by an attacker who can write cookies from a sibling subdomain |
| Custom header requirement for JSON APIs | Cross-site forms can't set custom headers; a cross-site `fetch` with them triggers a CORS preflight your server rejects |

Note for Fix B: JavaScript on `app.newdomain.com` **can't read** cookies set by `api.example.com`, so a "read the CSRF cookie and echo it in a header" scheme breaks across sites; return the CSRF token in a response body (e.g. from `GET /csrf`) instead.

```python
import hashlib
import hmac
import secrets


def csrf_token_for(session_id: str) -> str:
    nonce = secrets.token_urlsafe(16)
    mac = hmac.new(CSRF_KEY, f"{session_id}!{nonce}".encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{mac}"


def verify_csrf(request) -> None:
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise Forbidden("cross-site request")
    token = request.headers.get("X-CSRF-Token", "")
    nonce, _, mac = token.partition(".")
    expected = hmac.new(CSRF_KEY, f"{request.session_id}!{nonce}".encode(),
                        hashlib.sha256).hexdigest()
    if not mac or not hmac.compare_digest(mac, expected):
        raise Forbidden("bad CSRF token")
```

**Related headers worth setting:**

| Header | Purpose |
|---|---|
| `Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-…'; frame-ancestors 'none'` | XSS mitigation; `frame-ancestors` supersedes `X-Frame-Options` for clickjacking |
| `Strict-Transport-Security: max-age=63072000; includeSubDomains; preload` | HTTPS only (and makes `Secure` cookies meaningful) |
| `X-Content-Type-Options: nosniff` | No MIME sniffing |
| `Referrer-Policy: strict-origin-when-cross-origin` | Limit URL leakage |
| `Cross-Origin-Opener-Policy: same-origin` | Isolate the browsing context from cross-origin popups |

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Site vs origin** | Explains why the migration turned a same-site cookie into a third-party one |
| **SameSite understanding** | Three modes, browser differences, third-party cookie blocking |
| **CORS configuration** | Exact origins with credentials, no Origin reflection; CORS controls reads, not cookie sending |
| **CSRF mechanism** | Fetch Metadata, session-bound tokens, why naive double-submit is weak |
| **Fix quality** | Prefers making the API same-site (subdomain or BFF proxy) over SameSite=None |

---

## 9. Supply Chain Security

**Q:** "Your company was alerted that a popular npm package you depend on was compromised — the attacker injected malicious code that exfiltrates environment variables. Design a supply chain security strategy that would detect and prevent this at multiple stages: development, CI/CD, and deployment."

**What They're Really Testing:** Whether you understand modern software supply chain attacks (SolarWinds, event-stream, codecov) and have a practical defense-in-depth strategy.

### Answer

!!! tip "30-second answer"
    Assume a dependency **will** be malicious, and limit what it can reach. **Respond now**: find every build and deployment that pulled the bad version (lockfiles, SBOMs), rotate every secret those environments could see, and pin to a known-good version. **Prevent**: lockfiles with integrity hashes and `npm ci`; a **cooldown** before adopting new releases (most malicious versions are caught within days); block install scripts by default; route installs through an internal registry proxy that can quarantine packages; malware scanning, not just CVE scanning. **Contain**: CI jobs with no long-lived secrets (OIDC to the cloud), restricted egress, and builds isolated from deploy credentials, so stolen environment variables are worthless. **Verify**: SLSA provenance and signatures (Sigstore/cosign) checked at admission. The 2025 npm worms (e.g. Shai-Hulud, which stole tokens from developer machines and CI and republished infected packages) are exactly this scenario; npm responded by revoking classic tokens and pushing trusted publishing.

**Threat model:**

| Vector | Examples | Primary defence |
|---|---|---|
| Hijacked maintainer account / token → malicious release | event-stream (2018), ua-parser-js (2021), the chalk/debug compromise and Shai-Hulud worm (2025) | Cooldown, malware scanning, install-script blocking, egress limits |
| Dependency confusion | Internal package name published publicly with a higher version | Scoped/namespaced packages, single proxy registry, exclusive repository rules |
| Typosquatting / slopsquatting (names hallucinated by AI assistants) | `crossenv` vs `cross-env` | Allowlisted registry, review of new dependencies |
| Build system compromise | SolarWinds (2020), Codecov bash uploader (2021) | Hermetic, ephemeral builds; provenance; least-privilege CI |
| Compromised maintainer with long-term access | xz-utils backdoor (2024) | Hard; reproducible builds, diverse review, distro vigilance |

**Stage 0: incident response for this alert**

1. Identify exposure: search lockfiles and SBOMs across repos and images for the bad version; check CI logs for builds in the exposure window.
2. **Rotate** every secret present in affected developer machines, CI jobs and runtime environments (cloud keys, npm/GitHub tokens, DB passwords). Exfiltration already happened; patching doesn't undo it.
3. Pin or roll back, rebuild from clean runners, redeploy.
4. Hunt for follow-on activity: new tokens, packages published from your org, unusual cloud API calls.

**Stage 1: development and dependency intake**

```bash
npm ci --ignore-scripts          # exact lockfile versions + integrity hashes; no lifecycle scripts
npm config set ignore-scripts true   # or allowlist the few packages that need build scripts
                                     # (pnpm ≥ 10 doesn't run dependency scripts unless allowlisted)
```

```yaml
# .github/dependabot.yml: update regularly, but let new releases age first
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule: { interval: "weekly" }
    cooldown:
      default-days: 7            # don't propose versions younger than 7 days
    groups:
      minor-and-patch: { update-types: ["minor", "patch"] }
```

Equivalent cooldowns exist in Renovate (`minimumReleaseAge`) and pnpm (`minimumReleaseAge`). Pair with a **malware-aware** scanner (Socket, OSV's malicious-packages feed, registry-proxy quarantine) because `npm audit`, Trivy and Grype only know about **published CVEs**, which a fresh malicious release won't have.

**Stage 2: CI/CD — contain and attest**

```yaml
# GitHub Actions sketch
permissions:
  contents: read
  id-token: write                       # OIDC → short-lived cloud creds; no stored cloud keys
jobs:
  build:
    runs-on: ubuntu-latest              # ephemeral runner
    steps:
      - uses: actions/checkout@<full-commit-sha>        # pin actions by SHA, not tag
      - uses: step-security/harden-runner@<sha>          # egress allowlist / audit
        with: { egress-policy: block, allowed-endpoints: "registry.npmjs.org:443 ghcr.io:443" }
      - run: npm ci --ignore-scripts
      - run: npm test
      - run: |
          trivy fs --severity CRITICAL,HIGH --exit-code 1 .
          syft . -o cyclonedx-json > sbom.cdx.json
      - name: build, push, sign by digest (keyless)
        run: |
          docker build -t ghcr.io/acme/app:${GITHUB_SHA} .
          DIGEST=$(docker push ghcr.io/acme/app:${GITHUB_SHA} | awk '/digest:/ {print $3}')
          cosign sign --yes ghcr.io/acme/app@${DIGEST}                    # Sigstore OIDC identity
          cosign attest --yes --type cyclonedx --predicate sbom.cdx.json ghcr.io/acme/app@${DIGEST}
```

- **Separate build from deploy:** the job that runs third-party code (install, tests) must not hold deploy or publish credentials.
- **Provenance:** SLSA Build Level 3 means provenance generated by a hardened, isolated build platform (e.g. GitHub's artifact attestations or the SLSA generator), so a consumer can verify which repo, commit and workflow produced an artifact.
- **Publishing your own packages:** npm **trusted publishing** (OIDC from CI, no tokens; npm revoked all classic tokens in December 2025) and `npm publish --provenance`; PyPI has trusted publishing and attestations too.

**Stage 3: deployment — verify before running**

```yaml
# Kyverno: only admit images signed by our CI workflow identity (keyless)
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signatures
spec:
  rules:
    - name: require-ci-signature
      match:
        any:
          - resources: { kinds: ["Pod"] }
      verifyImages:
        - imageReferences: ["ghcr.io/acme/*"]
          failureAction: Enforce
          mutateDigest: true           # pin the tag to the verified digest
          attestors:
            - entries:
                - keyless:
                    issuer: "https://token.actions.githubusercontent.com"
                    subject: "https://github.com/acme/app/.github/workflows/release.yml@refs/heads/main"
```

Sigstore's policy-controller and cloud equivalents (GKE Binary Authorization) do the same. At runtime, egress network policies and runtime detection (Falco, Tetragon) catch exfiltration attempts from compromised code.

**SBOMs — useful when queried, not when filed:**

```bash
syft ghcr.io/acme/app@sha256:... -o spdx-json > sbom.spdx.json
grype sbom:./sbom.spdx.json                 # match against current vulnerability data
```

Feed SBOMs into an inventory (Dependency-Track, GUAC, your registry's SBOM features) so "which services run package X version Y?" is a query that takes minutes, not a week of grepping.

**Dependency confusion prevention:**

```ini
# .npmrc: internal scope always resolves to the internal registry
@acme:registry=https://npm.internal.acme.com/
```

```ini
# pip.conf: ONE index that proxies PyPI and hosts internal packages
[global]
index-url = https://pypi.internal.acme.com/simple
# Never: extra-index-url = ...  → pip picks the highest version across BOTH indexes
```

```bash
pip install --require-hashes -r requirements.txt   # every pin has --hash=sha256:...
# uv defaults to the first index that has a package ("first-index" strategy), which avoids
# the extra-index-url confusion by design.
```

```kotlin
// Gradle: internal groups may only come from the internal repo
repositories {
    exclusiveContent {
        forRepository { maven("https://artifacts.acme.com/releases") }
        filter { includeGroupByRegex("com\\.acme\\..*") }
    }
    mavenCentral()
}
```

**Signed commits and protected branches:** require signed commits (SSH or GPG, or Sigstore's gitsign) and reviews on protected branches, and keep CI workflow files under CODEOWNERS review; a malicious workflow change is a supply-chain attack on yourself. OpenSSF Scorecard gives a quick read on an upstream project's practices.

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Incident response** | Rotates secrets first; uses lockfiles/SBOMs to scope exposure |
| **Prevention** | Cooldowns, install-script blocking, malware (not just CVE) scanning, proxy registry |
| **Containment** | CI without long-lived secrets (OIDC), egress control, build/deploy separation |
| **Verification** | Keyless signing by digest, SLSA provenance, admission policies |
| **Dependency confusion** | Scopes, single index, hashes, exclusive repository content |

### 🔐 Zero Trust Security Quick Reference

```yaml
# Zero Trust Architecture for Microservices:
#   "Never trust, always verify"
#
# Key principles applied to this pipeline:
#   1. Verify every artifact: signature and provenance check before deployment
#   2. Least privilege: minimal IAM roles, short-lived credentials, network policies
#   3. Assume breach: no long-lived secrets in CI, audit logging, egress control
#   4. Micro-segmentation: network policies and service identity (mTLS) between services
#
# For supply chain specifically:
#   - Never trust upstream packages without verification and an aging period
#   - Verify signatures at every stage (dev → CI → deploy)
#   - Continuously rescan running images and SBOMs for new CVEs
```

---

## 10. SSRF & Server-Side Vulnerabilities

**Q:** "Your application has an SSRF vulnerability. The attacker used it to access the AWS metadata endpoint (169.254.169.254) and retrieved IAM credentials. Design a comprehensive SSRF prevention strategy covering application code, network architecture, and cloud configuration."

**What They're Really Testing:** Whether you understand Server-Side Request Forgery (SSRF) — one of the most dangerous and commonly missed vulnerabilities in modern web applications.

### Answer

!!! tip "30-second answer"
    First contain: revoke the role's sessions, rotate anything it could read, and audit CloudTrail for use of the stolen credentials from outside your network. Then fix in layers. **Cloud**: enforce **IMDSv2** with hop limit 1 (most SSRF can't send the required PUT with a custom header), shrink the instance role to least privilege, and use pod-level identities. **Network**: user-supplied-URL fetches go through an **egress proxy** (e.g. Stripe's Smokescreen) that resolves DNS and blocks private, loopback and link-local addresses at **connect time**, and default-deny egress elsewhere. **Application**: allowlist destinations when you can; otherwise allow only `https`, resolve once, reject any non-public address, **connect to that exact IP** (defeats DNS rebinding) while verifying TLS for the hostname, and don't follow redirects automatically. OWASP Top 10:2025 files SSRF under **A01 Broken Access Control**.

**The attack:**

```python
@router.get("/preview")
async def preview(url: str):
    return requests.get(url).text      # attacker: url=http://169.254.169.254/latest/meta-data/iam/security-credentials/web-role
# IMDSv1 answers a plain GET with temporary AccessKeyId / SecretAccessKey / Token.
# The attacker uses them from anywhere until they expire (hours), with every permission
# the instance role has: read S3, query DynamoDB, launch instances...
```

The 2019 Capital One breach (data on ~100 million US customers) followed this path: SSRF through a misconfigured WAF to the metadata service, then an over-privileged role that could list and read S3 buckets.

**Other SSRF targets:** internal admin panels and APIs (no auth because "it's internal"), Kubernetes API and kubelet, Redis/Memcached (via `gopher://` in clients that support it), cloud metadata on other providers (GCP/Azure also use 169.254.169.254, with required headers), and `file://` reads.

**Defense layer 1: cloud configuration (fastest risk reduction):**

```bash
# Require IMDSv2 tokens; hop limit 1 stops containers (one extra network hop) from reaching it
aws ec2 modify-instance-metadata-options --instance-id i-0abc... \
    --http-tokens required --http-put-response-hop-limit 1 --http-endpoint enabled

# Account-level default for new instances in a region
aws ec2 modify-instance-metadata-defaults --http-tokens required --http-put-response-hop-limit 1
```

- IMDSv2 requires `PUT /latest/api/token` with an `X-aws-ec2-metadata-token-ttl-seconds` header, then the token in a header on each GET. A typical SSRF controls only a URL for a GET, so it can't complete this. Many recent AMIs (e.g. Amazon Linux 2023) default to IMDSv2-only. Monitor the `MetadataNoToken` CloudWatch metric before enforcing.
- **Least privilege** for the role, and **no instance role at all** for workloads that don't need one. On EKS use **Pod Identity** or IRSA so each pod gets its own narrowly scoped role and the node role isn't reachable.
- Detect use of stolen credentials: GuardDuty flags instance credentials used from outside AWS; data-perimeter policies (`aws:SourceVpc`, `aws:ec2InstanceSourceVPC`) make them useless off-network.

**Defense layer 2: network:**

- Put fetches of user-supplied URLs behind an **egress proxy** that enforces "public internet only" at connect time, after DNS resolution (Smokescreen does exactly this). The application can't bypass it because the workload has no other route out.
- Default-deny egress with network policies; allow only what each service needs.

```yaml
# Kubernetes: allow DNS and public internet, block metadata and private ranges
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: link-preview-egress
spec:
  podSelector:
    matchLabels: { app: link-preview }
  policyTypes: ["Egress"]
  egress:
    - to:                                   # DNS must be allowed explicitly, or nothing resolves
        - namespaceSelector: {}
          podSelector:
            matchLabels: { k8s-app: kube-dns }
      ports:
        - { protocol: UDP, port: 53 }
        - { protocol: TCP, port: 53 }
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 169.254.0.0/16              # link-local, incl. metadata endpoints
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
              - 100.64.0.0/10               # carrier-grade NAT / some cloud internals
      ports:
        - { protocol: TCP, port: 443 }
```

(Whether `ipBlock` applies to traffic that the node itself handles differs by CNI; verify with a test pod. On EKS, also block IMDS via hop limit 1.)

**Defense layer 3: application code (tested):**

```python
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit


class SSRFError(Exception):
    pass


ALLOWED_PORTS = {443}


def resolve_public_ip(host: str, port: int) -> str:
    """Resolve ALL addresses and refuse if any of them is non-public."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise SSRFError(f"cannot resolve {host}") from e
    ips = {info[4][0] for info in infos}
    for ip in ips:
        addr = ipaddress.ip_address(ip)
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped                     # ::ffff:169.254.169.254
        if not addr.is_global:                          # private, loopback, link-local
            raise SSRFError(f"{host} resolves to non-public {addr}")   # (all of 169.254/16),
    return sorted(ips)[0]                               # CGNAT, reserved, unspecified, ...


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a pre-validated IP, but do SNI and certificate checks for the hostname."""

    def __init__(self, host: str, ip: str, port: int = 443, timeout: float = 5.0):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch_untrusted_url(url: str, max_bytes: int = 1_000_000) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise SSRFError("only https URLs with a hostname are allowed")
    port = parts.port or 443
    if port not in ALLOWED_PORTS:
        raise SSRFError(f"port {port} not allowed")
    ip = resolve_public_ip(parts.hostname, port)        # resolve once ...
    conn = PinnedHTTPSConnection(parts.hostname, ip, port)  # ... connect to that same IP
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    conn.request("GET", path, headers={"User-Agent": "link-preview/1.0"})
    resp = conn.getresponse()
    if 300 <= resp.status < 400:
        # A redirect is a NEW untrusted URL: validate it from scratch (with a hop limit)
        raise SSRFError("redirect not followed")
    return resp.read(max_bytes)                          # cap the response size
```

Why each piece matters:

- **`is_global` instead of a hand-written blocklist:** hand-written lists routinely miss ranges (all of `169.254.0.0/16`, `100.64.0.0/10`, `0.0.0.0`, IPv6 ULA `fc00::/7`, IPv4-mapped IPv6, AWS's IPv6 IMDS `fd00:ec2::254`). Alternative encodings (`http://2852039166/`, `0xA9FEA9FE`, `169.254.169.254.nip.io`) are handled because you validate the **resolved address**, not the string.
- **DNS rebinding:** if you validate one resolution and then let the HTTP library resolve again, an attacker's DNS (TTL 0) can answer with a public IP first and `169.254.169.254` second. Connecting to the exact validated IP removes the window.
- **Keep TLS verification:** replacing the hostname with the IP in the URL (a common "fix") breaks certificate verification or tempts people to disable it. Pin the socket, keep `server_hostname`.
- **Redirects** re-enter the whole validation; most libraries follow them by default (`requests` does; set `allow_redirects=False`).
- **Allowlist when possible:** webhooks to customer endpoints need the general approach above; integrations with known partners should be a fixed allowlist of hostnames.

**Blind SSRF:** the attacker sees no response but can still trigger internal actions or confirm reachability via timing or out-of-band callbacks (an attacker-controlled DNS name that logs lookups). Detect with egress-proxy logs (denied private-range attempts are a strong signal), alerts on requests to metadata addresses, and DAST tools with out-of-band detection (Burp Collaborator, interactsh).

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Containment** | Revokes/rotates credentials and audits their use before fixing code |
| **Cloud hardening** | IMDSv2 + hop limit, least privilege, pod identities, GuardDuty/data perimeter |
| **DNS rebinding** | Resolve once, validate all addresses, connect to that IP, keep TLS verification |
| **Multi-layer defense** | Egress proxy, network policy (with DNS allowed), app-level validation, redirects |
| **Blind SSRF** | Out-of-band detection and egress logging |

---

> *All 10 questions include code examples, attack scenarios, and evaluation rubrics at staff-engineer depth. For complementary resources, see the [cs-interview README](../README.md).*
