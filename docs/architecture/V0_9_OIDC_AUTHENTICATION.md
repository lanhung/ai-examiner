# v0.9 OIDC Authentication

Status: WP-03 implemented on `research/v0.9.0`

## 1. Scope

WP-03 introduces authenticated principal identity without enabling capability RBAC or
tenant row-level security. It provides:

- OpenID Provider discovery with exact issuer validation;
- bounded metadata and JWKS caches;
- strict JWT access-token validation;
- Authorization Code flow with PKCE S256 and nonce validation;
- external `(issuer, subject)` principal resolution;
- configurable just-in-time principal provisioning;
- hashed, revocable browser sessions;
- logout and current-principal APIs;
- fail-closed production configuration and live readiness checks.

The branch remains research-only. WP-04 must add capability authorization before
enterprise business APIs are exposed.

## 2. Trust boundaries

```text
Browser
  -> /api/v1/auth/login
  -> external authorization endpoint
  -> /api/v1/auth/callback
  -> token endpoint

API client
  -> Authorization: Bearer <access token>
  -> strict JWT validator
  -> Principal(issuer, subject)
```

The application trusts only:

1. discovery metadata fetched from the configured issuer;
2. signing keys fetched from that metadata's `jwks_uri`;
3. tokens whose algorithm, type, signature, issuer, audience, time and scope claims
   pass all configured checks;
4. browser session secrets whose SHA-256 hash matches an active database session.

Organization or principal request headers are not identity proof. In OIDC mode,
`/api/v1/context` uses the verified principal and ignores
`X-AI-Examiner-Principal`.

## 3. Discovery and JWKS cache

`OIDCDiscoveryCache`:

- derives discovery from the configured issuer;
- requires the returned issuer to match exactly;
- rejects endpoint URLs with credentials or fragments;
- requires HTTPS, except explicit localhost-only test mode;
- disables HTTP redirects;
- limits discovery to 256 KB and JWKS to 1 MB/100 keys;
- intersects provider-advertised algorithms with the local allowlist;
- caches discovery and JWKS independently with bounded TTLs;
- refreshes JWKS once when a known-valid token header presents an unknown `kid`;
- negatively caches unknown key IDs for a short bounded interval to prevent refresh
  storms;
- rejects duplicate matching signing keys;
- never follows token-provided `jku` or `x5u`.

The cache is process-local and protected by a reentrant lock. Multiple API workers
maintain independent bounded caches, which is acceptable for v0.9 single-host
deployment.

## 4. Strict access-token validation

The access-token validator requires:

```text
alg in OIDC_ALLOWED_ALGORITHMS
typ in OIDC_ACCESS_TOKEN_TYPES
kid present
signature valid
iss exact
aud contains OIDC_AUDIENCE
exp valid
iat valid and not in the future
nbf valid when present
sub present and bounded
required scopes present
```

The default access-token type is `at+jwt`. An ID token using `typ=JWT` is rejected
when presented as an API access token. A provider using another explicit access-token
type must be configured deliberately; the validator never infers trust from an
unverified token.

Scope extraction supports the standards-oriented `scope` claim and the commonly used
`scp` array/string form. ID-token validation additionally enforces nonce, `azp` for
multi-audience tokens and `at_hash` whenever the provider includes it.

Only normalized identity fields are returned from validation. Raw tokens and arbitrary
claims are not persisted, returned or included in exceptions.

## 5. Browser Authorization Code + PKCE

Login start generates:

- 256-bit state;
- high-entropy PKCE verifier;
- S256 code challenge;
- high-entropy OIDC nonce.

The database stores only:

- SHA-256 state;
- Fernet-encrypted verifier;
- SHA-256 nonce;
- exact redirect URI;
- expiry and one-time consumption state.

The callback marks the transaction consumed before exchanging the code. It validates
both the access token and ID token, checks nonce, and requires their issuer/subject
identity to match.

The browser receives an opaque session secret in an `HttpOnly`, `SameSite=Lax`
cookie. The database stores only its SHA-256 hash. Session expiry is bounded by both
the access-token expiry and `OIDC_SESSION_MAX_MINUTES`. Logout revokes the database
session and removes the cookie.

The code verifier is encrypted only to support a server-side callback. The encryption
key is derived from `AUTH_SESSION_SECRET`, which must be a high-entropy deployment
secret and must not be committed.

## 6. Principal provisioning

`OIDC_PRINCIPAL_PROVISIONING` supports:

```text
existing_only  unknown identities are denied
auto_pending   create a pending principal, then deny access
auto_active    create an active principal
```

`existing_only` is the recommended enterprise default. Provisioning never grants an
organization membership or role. WP-04 owns invitation, membership and capability
administration.

Existing `pending`, `suspended` or `disabled` principals are denied.

## 7. API

```text
GET  /api/v1/auth/login
GET  /api/v1/auth/callback
POST /api/v1/auth/logout
GET  /api/v1/me
GET  /api/v1/context
GET  /ready
GET  /health
```

`/health` reports process health and whether production is running with explicitly
unsafe disabled authentication. `/ready` checks:

- database connectivity;
- static authentication configuration;
- live discovery and JWKS availability when OIDC is enabled.

Readiness output contains stable reason codes, not endpoint payloads, tokens, claims
or secrets.

## 8. Production configuration

Minimum OIDC configuration:

```env
APP_ENV=production
AUTH_MODE=oidc
OIDC_ISSUER_URL=https://identity.example.edu
OIDC_AUDIENCE=ai-examiner-api
OIDC_CLIENT_ID=ai-examiner-web
OIDC_CLIENT_SECRET=
OIDC_REDIRECT_URI=https://examiner.example.edu/api/v1/auth/callback
OIDC_POST_LOGIN_REDIRECT=/
OIDC_ALLOWED_ALGORITHMS=RS256,ES256
OIDC_ACCESS_TOKEN_TYPES=at+jwt
OIDC_PRINCIPAL_PROVISIONING=existing_only
AUTH_SESSION_SECRET=<high-entropy-secret>
```

Production startup refuses `AUTH_MODE=disabled` unless
`ALLOW_UNSAFE_AUTH_DISABLED_IN_PRODUCTION=true` is explicitly set. That override is
visible as an unsafe flag on `/health`.

Never enable `OIDC_ALLOW_INSECURE_HTTP` outside localhost test environments.

## 9. Data model and migration

Migration `20260727_0009` adds:

```text
oidc_login_transactions
browser_auth_sessions
```

It is additive and preserves WP-02 organizations, principals and memberships.
Downgrade to `20260727_0008` removes only the WP-03 tables.

## 10. Test matrix

The deterministic WP-03 suite uses ephemeral RSA keys and a local `httpx`
transport. It covers:

- valid signed access token;
- discovery/JWKS cache reuse;
- unknown-key refresh and key rotation;
- unknown-key negative-cache refresh-storm protection;
- expired token;
- future `nbf`;
- wrong issuer;
- wrong audience;
- missing subject;
- ID token used as access token;
- future `iat`;
- missing required scope;
- forbidden remote key URL;
- unknown `kid`;
- disallowed algorithm before key lookup;
- PKCE/nonce callback and one-time state;
- ID-token authorized-party and access-token-hash checks;
- principal provisioning;
- browser session hashing, authentication and revocation;
- unavailable OIDC readiness;
- untrusted principal-header rejection;
- migration upgrade/downgrade preservation.

## 11. Integration with WP-04

WP-04 now converts this authenticated identity into organization capability decisions
for `/api/v1` administration and the template-authoring seam. It still does not:

- assign organization roles from token claims;
- protect every legacy unversioned route;
- propagate tenant ownership across all business resources;
- add service accounts;
- enable PostgreSQL RLS.

Those controls remain separate work packages so authentication and authorization can
be tested without claiming complete tenant isolation prematurely.
