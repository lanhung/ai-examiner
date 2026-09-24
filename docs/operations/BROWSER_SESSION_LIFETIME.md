# Browser Session Lifetime

The AutoDL deployment opts into independently revocable application sessions:

```dotenv
OIDC_SESSION_LIFETIME_POLICY=application
OIDC_SESSION_IDLE_MINUTES=120
OIDC_SESSION_MAX_MINUTES=480
```

OIDC login still validates the authorization code, PKCE, state, nonce, signatures,
issuer, audience, token expiry and token identity binding. After successful login,
the browser uses a random HttpOnly cookie backed by a hashed server-side session,
not an expired access token. Direct Bearer API tokens retain strict expiry checks.

The session ends after two hours without authenticated requests, or eight hours
after login, whichever comes first. Successful authenticated requests update the
idle timestamp but never extend the absolute deadline. An expired, revoked or
inactive-principal session cannot be renewed by activity. Membership checks and
RLS remain unchanged. No database migration is needed.

"Idle" means no authenticated requests, not no mouse movement: typing without
sending requests does not renew the session, while active job polling and voice
event uploads count as activity. Merely leaving an otherwise idle page open does
not add a keepalive. This change does not add OAuth refresh-token storage or claim
to implement automatic token refresh or an expiry-warning UI.

Existing sessions keep their original deadlines. Log out and log in once after
deployment to receive the new eight-hour cookie. Expiry is enforced server-side;
an open page can display stale login status until its next request.

The default policy remains `token_bound` for other deployments, preserving their
previous dependency on login-token expiry. `application` is an explicit tradeoff:
IdP-only revocation is not automatically propagated to the application session.
Use local session revocation/principal disabling for immediate application logout;
deployments requiring IdP lifecycle enforcement should retain `token_bound` until
back-channel logout or a fully validated refresh/revocation integration is added.

Rollback: set `OIDC_SESSION_LIFETIME_POLICY=token_bound`, revoke outstanding
application sessions, restart, and require a fresh login. Changing the policy alone
does not shorten already-issued cookies; each request still enforces idle and
configured maximum age. Never extend existing session rows manually.
