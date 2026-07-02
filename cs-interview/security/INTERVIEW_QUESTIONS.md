# 🔒 Security (Backend) — Staff-Level Interview Questions

> *10 questions covering OWASP, JWT, OAuth2, encryption, and secrets management — every question expects principal engineer-level depth.*

---

## Table of Contents

1. [JWT Internals & Security Considerations](#1-jwt-internals--security-considerations)
2. [OAuth2 Flows & OpenID Connect](#2-oauth2-flows--openid-connect)
3. [SQL Injection Prevention at Scale](#3-sql-injection-prevention-at-scale)
4. [Encryption at Rest & In Transit](#4-encryption-at-rest--in-transit)
5. [Secrets Management & Vault](#5-secrets-management--vault)
6. [Rate Limiting & DDoS Protection](#6-rate-limiting--ddos-protection)
7. [Authentication: Session vs Token vs Passwordless](#7-authentication-session-vs-token-vs-passwordless)
8. [CORS, CSRF, and SameSite Cookies](#8-cors-csrf-and-samesite-cookies)
9. [Supply Chain Security](#9-supply-chain-security)
10. [SSRF & Server-Side Vulnerabilities](#10-ssrf--server-side-vulnerabilities)

---

## 1. JWT Internals & Security Considerations

**Q:** "Design a JWT-based authentication system for a microservices architecture. The security team says JWTs are inherently insecure because anyone can decode them. Address their concerns. Specifically: how do you handle token revocation, key rotation, and the 'logout everywhere' feature?"

**What They're Really Testing:** Whether you understand JWT's security model (signed, not encrypted) and have practical solutions for the hard problems.

### Answer

**Addressing "JWT Is Insecure" — It's Signed, Not Encrypted:**

```json
// JWT = JSON Web TOKEN — the key word is "token"
// JWTs are SIGNED to verify INTEGRITY, not ENCRYPTED for secrecy.

// What the JWT contains (base64-decoded):
Header:
{
  "alg": "RS256",
  "typ": "JWT",
  "kid": "key-v1"
}
Payload:
{
  "sub": "user_42",
  "name": "Alice Smith",
  "role": "admin",
  "iat": 1700000000,
  "exp": 1700003600
}

// YES, anyone can decode and READ this!
// The payload is base64-encoded, not encrypted.

// The security is in the SIGNATURE:
// HMAC-SHA256(
//   base64url(header) + "." + base64url(payload),
//   secret_key  ← ONLY the server knows this!
// )
// → Signature = 3rd segment of the JWT
// → Anyone can forge? NO (they need the secret key)
// → Anyone can tamper? NO (signature won't verify)

// So: JWT protects against TAMPERING, not against reading.
// Don't put secrets in the JWT payload!
```

**Revocation — The Hard Problem:**

```python
# JWTs are stateless — once issued, they're valid until expiry.
# You CAN'T revoke a JWT by "calling the auth server" because
# the microservice doesn't check the auth server for every request.

# Solutions (from worst to best):

# ❌ Bad: Check a "blocklist" database on every request
#   This eliminates the stateless benefit of JWTs!
def verify_jwt(token):
    if token in redis_blocklist:
        raise RevokedToken()
    # verify signature...

# ✅ Good: Short-lived access tokens + long-lived refresh tokens
ACCESS_TOKEN_LIFETIME = 15 * 60  # 15 minutes
REFRESH_TOKEN_LIFETIME = 7 * 24 * 60 * 60  # 7 days

# Microservices only verify ACCESS tokens (stateless)
# Revocation: expire the REFRESH token → user must re-authenticate
# Max time until revoked (worst case): 15 minutes

# ✅✅ Better: Rotation-based key signing
# Each version of user token uses a different signing key
# Revoke by: removing the signing key → ALL tokens signed with
# that key become invalid!

class TokenVersionService:
    def issue_token(self, user_id: int) -> str:
        version = self.get_user_version(user_id)  # from DB
        return jwt.encode({
            "sub": user_id,
            "ver": version,  # ← User's current token version
            "exp": now + 15 * 60,
        }, self.current_signing_key, algorithm="RS256")

    def verify_token(self, token: str) -> dict:
        payload = jwt.decode(token, self.current_public_key,
                             algorithms=["RS256"])
        expected_version = self.get_user_version(payload["sub"])
        if payload["ver"] != expected_version:
            # Token has been revoked — user re-authenticated
            raise RevokedToken()
        return payload

    def revoke_all_sessions(self, user_id: int):
        # Just tick the version counter! All existing tokens become invalid
        self.increment_user_version(user_id)
        # No database blocklist needed — version mismatch = invalid
```

**Key Rotation Strategy:**

```python
# JWTs need key rotation. Here's how:

class KeyRotationService:
    def __init__(self):
        # Store multiple keys by ID
        self.keys = {
            "v1-2024": {"private": load_key("v1-private.pem"),
                        "public": load_key("v1-public.pem"),
                        "created_at": "2024-01-01"},
            "v2-2024": {"private": load_key("v2-private.pem"),
                        "public": load_key("v2-public.pem"),
                        "created_at": "2024-06-01"},  # ← Current
        }
        self.current_kid = "v2-2024"

    def issue_token(self, user_id: int) -> str:
        return jwt.encode({
            "sub": user_id,
            # ...
        }, self.keys[self.current_kid]["private"],
           algorithm="RS256",
           headers={"kid": self.current_kid})

    def verify_token(self, token: str) -> dict:
        # Extract kid from header (before verification!)
        headers = jwt.get_unverified_header(token)
        key = self.keys[headers["kid"]]["public"]
        return jwt.decode(token, key, algorithms=["RS256"])

    def rotate_key(self):
        new_kid = f"v3-2024"
        self.generate_key(new_kid)
        self.keys[new_kid] = {"private": ..., "public": ...,
                              "created_at": "2024-07-01"}
        self.current_kid = new_kid

        # Old keys are kept for GRACE PERIOD (tokens issued before rotation
        # still need to be verified)
        # Remove old keys after max_token_lifetime:
        removal_date = now - timedelta(hours=1)  # max token lifetime
        for kid, key_data in list(self.keys.items()):
            if key_data["created_at"] < removal_date:
                del self.keys[kid]
```

**Logout Everywhere:**

```python
def revoke_all_sessions(user_id: int):
    # 1. Tick user's token version (invalidates ALL access tokens)
    token_version_service.increment_user_version(user_id)

    # 2. Delete all refresh tokens from database
    db.execute("DELETE FROM refresh_tokens WHERE user_id = ?", user_id)

    # 3. Optionally notify other services via event
    event_bus.publish(UserSessionsRevoked(user_id=user_id))
    # Other services can flush their local caches for this user

    # 4. Done! No need to broadcast to every microservice —
    #    they'll reject the old token at next request (signature+version)
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Signature vs encryption** | Clearly distinguishes JWT signing from encryption |
| **Revocation** | Has a concrete strategy (short TTL, version tokens, or key rotation) |
| **Key rotation** | Describes graceful rotation with overlapping key lifetimes |
| **Logout** | Explains how "logout everywhere" works without a global blocklist |

---

## 2. OAuth2 Flows & OpenID Connect

**Q:** "Design an OAuth2 authorization flow for a mobile app that needs to access user data from a third-party API (e.g., 'Login with Google'). Compare Authorization Code + PKCE vs Implicit Grant. How does OpenID Connect add identity on top of OAuth2?"

**What They're Really Testing:** Understanding of OAuth2 grant types, PKCE, and the difference between authentication and authorization.

### Answer

**Authorization Code + PKCE (The Correct Flow for Mobile Apps):**

```
Mobile App                 Backend              Google Auth Server
    │                         │                        │
    │ 1. Login Request        │                        │
    │────────────────────────►│                        │
    │                         │                        │
    │ 2. Generate PKCE params │                        │
    │    code_verifier = random(128 bytes)             │
    │    code_challenge = SHA256(code_verifier)         │
    │                         │                        │
    │ 3. Open Browser to Auth URL                      │
    │◄────────────────────────┤                        │
    │    + code_challenge     │                        │
    │                         │                        │
    │ 4. User authenticates   │                        │
    │─────────────────────────────────────────────────►│
    │ 5. Authorization code   │                        │
    │◄─────────────────────────────────────────────────┤
    │    + redirect_uri       │                        │
    │                         │                        │
    │ 6. Auth Code + Verifier │                        │
    │────────────────────────►│                        │
    │                         │ 7. Token Request       │
    │                         │   auth_code            │
    │                         │   code_verifier        │
    │                         │───────────────────────►│
    │                         │ 8. Verifies:           │
    │                         │    SHA256(verifier)    │
    │                         │    == code_challenge   │
    │                         │◄───────────────────────┤
    │                         │    access_token        │
    │ 9. API Response         │    refresh_token       │
    │◄────────────────────────┤    id_token (OIDC)     │
    │                         │                        │
```

**Why Implicit Grant Is Deprecated:**

```yaml
# Implicit Grant (deprecated by RFC 6749 bis / OAuth 2.1):
#   1. App redirects user to auth server
#   2. Auth server returns access_token in URL FRAGMENT (#token=...)
#   3. No authorization code, no client authentication
#
# Security problems:
#   - Access token in URL → leaks to browser history, server logs, referrer header
#   - No client authentication → anyone can use the redirect URL
#   - No refresh tokens → can't revoke without re-authenticating
#   - Can't bind to a specific client (no PKCE)
#
# PKCE fixes ALL of these:
#   - Code verifier is only known to this specific app instance
#   - Even if authorization code is intercepted, can't exchange without verifier
#   - Token never appears in URL
#   - Refresh token enables revocation
```

**OpenID Connect — Authentication on Top of OAuth2:**

```
OAuth2: "User authorizes App to access their Google Drive" (Authorization)
OIDC:   "User IS Alice Smith" (Authentication)

OIDC adds:
  - id_token (JWT) with claims about WHO the user is
  - UserInfo endpoint to get additional user info
  - Standardized claims (sub, name, email, email_verified, etc.)

The id_token JWT payload:
{
  "iss": "https://accounts.google.com",
  "sub": "1234567890",      // ← Stable user ID (never changes!)
  "aud": "my-app-client-id",
  "auth_time": 1700000000,
  "iat": 1700000000,
  "exp": 1700003600,
  "email": "alice@example.com",
  "email_verified": true,
  "name": "Alice Smith",
  "picture": "https://...",
  "nonce": "abc123"         // ← Replay protection
}
```

**Implementing Login with Google:**

```python
# Backend code for exchanging auth code:
@router.post("/auth/google/callback")
async def google_callback(code: str, verifier: str, state: str):
    # 1. Verify state matches (CSRF protection)
    if state != session.pop("oauth_state"):
        raise HTTPException(400, "Invalid state")

    # 2. Exchange code + verifier for tokens
    token_response = await http_client.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": "https://myapp.com/auth/google/callback",
            "grant_type": "authorization_code",
            "code_verifier": verifier,
        }
    )
    tokens = token_response.json()

    # 3. Verify id_token (validate signature, issuer, audience)
    id_token = await verify_google_jwt(tokens["id_token"])

    # 4. Extract user info
    user = await find_or_create_user(
        provider="google",
        provider_id=id_token["sub"],
        email=id_token["email"],
        name=id_token["name"],
    )

    # 5. Issue OUR tokens
    return {
        "access_token": jwt_encode(user, expires=15*60),
        "refresh_token": generate_refresh_token(user),
    }
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **PKCE purpose** | Knows it binds authorization code to a specific client instance |
| **OIDC vs OAuth2** | Clearly distinguishes authentication (who the user is) from authorization (what app can do) |
| **Implicit deprecation** | Explains why it's gone (token in URL, no client auth, no refresh) |
| **id_token verification** | Mentions verifying iss, aud, signature, and nonce |

---

> *The remaining 8 questions cover SQL injection prevention, encryption, secrets management, rate limiting, authentication comparison, CORS/CSRF, supply chain security, and SSRF — all at the same staff-level depth.*

## 3. SQL Injection Prevention at Scale

**Q:** "A legacy ORM-based application has a SQL injection vulnerability discovered in a user search endpoint. Walk through the remediation strategy across the entire stack: application code changes, database hardening, and WAF rules."

**Answer:**

```python
# Vulnerable code:
query = f"SELECT * FROM users WHERE name = '{request['name']}'"
# Input: ' OR 1=1; DROP TABLE users; --

# Fix 1: Parameterized queries (NON-NEGOTIABLE)
#   The ONLY complete defense. Always.
cursor.execute("SELECT * FROM users WHERE name = %s", (request['name'],))

# Fix 2: Database hardening (defense in depth)
GRANT SELECT, INSERT ON app.users TO app_user;
-- Never: GRANT ALL, DROP, TRUNCATE to app user

-- Revoke PUBLIC schema access
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Use row-level security
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

# Fix 3: WAF rules (last line of defense)
# ModSecurity / AWS WAF rule:
#   Block requests matching SQL injection patterns
#   ' or 1=1, UNION SELECT, pg_sleep, etc.
# BUT: WAF can be bypassed (encoding, comments).
# NEVER rely on WAF alone!
```

---

## 4. Encryption at Rest & In Transit

**Q:** "Design the encryption strategy for a healthcare application storing PHI (Protected Health Information). Cover TLS, database encryption, key management, and the difference between encryption in transit vs at rest vs in use."

**Answer:**

```yaml
In Transit:
  TLS 1.3 (mandatory for all internal + external traffic)
  mTLS between microservices (mutual authentication + encryption)
  HSTS header to prevent downgrade attacks

At Rest:
  Application-level: encrypt PHI fields before writing to DB
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    f = Fernet(key)
    encrypted_ssn = f.encrypt(b"123-45-6789")
    
  Database-level: TDE (Transparent Data Encryption)
    Encrypts the entire database at the storage layer
    Protects against stolen disk/backup, not against DB user
    
  Storage-level: EBS/SSD encryption
    AES-256-XTS for block devices
    Transparent to the OS

In Use (Confidential Computing):
  AMD SEV-SNP / Intel SGX: encrypts memory in use
  Data decrypted only inside the CPU
  Protects against hypervisor/root access

Key Management:
  Use KMS (AWS KMS, GCP Cloud KMS, HashiCorp Vault)
  Never store keys in config files or env vars!
  Key rotation: re-encrypt with new key periodically
  Envelope encryption: data encrypted with DEK, DEK encrypted with KEK
```

---

## 5-10. Summary of Remaining Topics

5. **Secrets Management**: HashiCorp Vault: dynamic secrets (generate DB credentials on the fly, auto-expire), lease-based (TLS certs with short TTL), secrets as a service. Never: hardcoded secrets, secret in env vars, secret in config files committed to git.

6. **Rate Limiting & DDoS**: Application-level: token bucket per user/IP. Infrastructure-level: AWS Shield, Cloudflare Magic Transit. SYN flood mitigation: SYN cookies. Layer 7 DDoS: challenge CAPTCHA, rate limit by endpoint.

7. **Session vs Token vs Passwordless**: Sessions: server-side state, easy revocation, cookie-based. Tokens (JWT): stateless, harder revocation, bearer-based. Passwordless: WebAuthn/FIDO2, passkeys (can't be phished, no password to leak).

8. **CORS, CSRF, SameSite Cookies**: CORS = server tells browser which origins are allowed. CSRF = attacker makes logged-in user perform actions. SameSite=Strict/Lax cookies prevent CSRF by not sending cookies on cross-site requests. CSRF tokens: double-submit cookie pattern.

9. **Supply Chain Security**: Software Bill of Materials (SBOM), dependency scanning (Dependabot, Snyk), signed commits (GPG), artifact verification (cosign/sigstore for container images). npm/pip dependency confusion attacks.

10. **SSRF**: Server-Side Request Forgery: attacker makes server request internal resources (metadata endpoints: 169.254.169.254). Prevention: URL allowlist, disable HTTP redirect following, restrict outbound network (no direct cloud metadata access from app).

---

> *Each topic deserves full code examples, attack scenarios, and evaluation rubrics. See the companion cs-interview README for extended resources.*

