# v0.9 Enterprise Administration UI

Status: WP-13 implemented on `research/v0.9.0`

## 1. Scope

WP-13 adds a dedicated administration surface at `/enterprise`. It does not
replace the existing `/` answering, template, evidence or realtime voice
workspace. The enterprise console exposes:

- OIDC login state and logout;
- organization selection and effective capability context;
- organization membership and role administration;
- model policy, quota and current-month usage;
- immutable audit search and bounded export;
- retention policy, legal holds and data-subject request status;
- human review queues, case evidence and decision events.

The page uses the existing FastAPI application and same-origin OIDC session. It
does not add a second frontend framework, browser token store or client-side
authorization source of truth.

## 2. Routes and assets

```text
GET /enterprise
GET /static/enterprise.css
GET /static/enterprise.js
```

The core workspace links to `/enterprise`. The enterprise top bar links back to
`/`, so operational administration does not add steps to text or voice sessions.

WP-13 also adds:

```text
GET /api/v1/organizations/{organization_id}/data-subject-requests
```

The endpoint requires `retention.read`, is registered in the centralized route
policy table and supports bounded `status`, `request_type` and `limit` filters.
It returns only rows owned by the authorized path organization.

`GET /api/v1/me` now includes organization `display_name`, `slug` and `status`
beside the existing membership role and capabilities. Organization IDs remain
the authorization keys; names are presentation metadata only.

## 3. Authentication states

### OIDC mode

The console calls `/api/v1/me` with same-origin credentials. An unauthenticated
principal sees a login action. An authenticated principal sees only active
organization memberships returned by the server.

No access token is written to JavaScript storage. The browser session remains an
HTTP-only cookie managed by the OIDC backend.

### Disabled development mode

Development can provide an existing organization ID and principal ID. Those
values are sent through the already reviewed disabled-mode headers:

```text
X-AI-Examiner-Organization
X-AI-Examiner-Principal
```

This mode is rejected by production configuration validation. It is not a
password substitute or production login flow.

## 4. Organization-switch isolation

The browser treats organization selection as a security boundary.

On every switch it:

1. aborts all pending organization requests;
2. increments an organization epoch;
3. clears every organization-owned table, metric and detail view;
4. sends the selected organization header on every scoped request;
5. rejects a response if its captured organization or epoch no longer matches;
6. rejects a response that declares a different organization ID.

Capability-gated navigation and actions are rebuilt only after the new
`/api/v1/context` response succeeds. Client gating improves usability but never
replaces server authorization, RLS or resource ownership checks.

## 5. Capability mapping

| UI area | Read capability | Mutation capability |
|---|---|---|
| Organization summary | `organization.read` | none |
| Members | `member.read` | `member.manage` |
| Model policy and quota | `policy.read` | `policy.manage` |
| Usage | `usage.read` | none |
| Audit | `audit.read` | none |
| Retention and holds | `retention.read` | `retention.manage` |
| Data request creation | n/a | `review_case.create` |
| Human review | `review_case.review` | `review_case.review` |

The server remains authoritative. A hidden or disabled browser control is not a
security decision.

## 6. High-risk action controls

The following actions require a modal confirmation:

- membership revocation: type `REVOKE`;
- legal-hold release: type `RELEASE`;
- data export approval: type `APPROVE`;
- data deletion approval: type `DELETE`;
- human final decision: type `DECIDE`;
- data-request cancellation: explicit confirm.

Membership mutation continues to send the server-issued version using a strong
`If-Match` ETag. Concurrent changes therefore fail rather than overwrite a newer
membership state.

Data deletion still requires backend dual control. The UI cannot let the
requesting principal approve the same deletion.

## 7. Layout

The console is an operational UI:

- compact sticky top bar;
- fixed desktop navigation and horizontally scrollable mobile navigation;
- tables for membership and audit comparison;
- forms for policies and quotas;
- record lists for lifecycle and review workflows;
- two-column desktop layouts collapsing to one column below 1000 px;
- no marketing hero, decorative illustration or nested card composition.

All new framed surfaces use a maximum 7 px radius. Fixed controls have stable
minimum dimensions. Tables remain horizontally scrollable on narrow screens.

## 8. Error handling

The API helper reads each response body exactly once, then parses the cached
text. This prevents the previous `body stream already read` browser failure.

Network, validation and authorization errors are rendered as short transient
messages. Cross-organization or aborted responses produce no stale error toast
and cannot render into the new organization view.

## 9. Verification

Deterministic tests cover:

- dedicated enterprise route and asset delivery;
- organization-switch abort and epoch guards in the shipped JavaScript;
- explicit high-risk confirmation control;
- organization metadata in `/api/v1/me`;
- filtered, tenant-owned data-subject request listing;
- invalid lifecycle filters;
- exact `/api/v1` route-policy registration;
- disabled-mode `/me` compatibility.

Release hardening must still run:

```text
node --check src/ai_examiner/static/enterprise.js
ruff check .
pytest
git diff --check
```

Desktop and mobile browser screenshots and an OIDC staging session remain WP-14
release evidence. They are not replaced by static DOM assertions.
