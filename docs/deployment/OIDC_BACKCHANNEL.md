# OIDC Backchannel Deployment

Some container platforms cannot connect from an instance to its own public
port-mapping address. Discovery, JWKS and code exchange then time out even though
the browser can reach the public login page.

The optional `OIDC_BACKCHANNEL_BASE_URL` changes only server-to-server transport
for URLs underneath `OIDC_ISSUER_URL`. Public discovery metadata, the browser
authorization URL, the redirect URI and JWT issuer validation remain unchanged.
The default is unset and preserves existing deployments.

Example for a private test issuer on the same machine:

```env
OIDC_ISSUER_URL=https://login.example.com
OIDC_REDIRECT_URI=https://examiner.example.com/api/v1/auth/callback
OIDC_BACKCHANNEL_BASE_URL=http://127.0.0.1:6009
OIDC_ALLOW_INSECURE_HTTP=true
```

HTTP backchannels require explicit permission and are limited to literal
`127.0.0.1` or `localhost`. All other backchannels require HTTPS. Credentials,
query strings, fragments and invalid ports are rejected. An issuer path prefix
is replaced by the backchannel base prefix; configure the complete internal
base path when using a realm-based identity service.

Keep the issuer's internal port bound to loopback. Never expose the repository's
automatic test issuer directly: it does not authenticate a person. A preview
deployment must protect its authorization endpoint with an independent password
gate. Production deployments should use a proper identity provider with named
users, account recovery and MFA.

No change is made to signature, audience, token-type, expiry, nonce, PKCE or
issuer checks. TLS verification is not disabled. A public URL from another
issuer is never rewritten to the internal endpoint.
