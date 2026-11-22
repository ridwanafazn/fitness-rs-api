# Neon Auth integration

Neon Auth is the selected identity provider. The backend does **not** run its
own auth server: it verifies Neon-issued JWTs against the branch JWKS and keeps
application roles in our `user_roles` table.

This repository does not contain Neon credentials. Enable Auth on your own Neon
branch and set the environment below; no secret is committed.

## How the pieces fit

```text
Vue frontend
  └─ @neon/auth sign-in / getSession()
       └─ data.session.token (JWT, EdDSA, 15 min)
            └─ Authorization: Bearer <token>
                 └─ FastAPI verifies JWKS + iss + aud
                      └─ users / profiles / plans / ...
```

Neon Auth stores identity in the `neon_auth` schema on the Neon branch. It is
managed Better Auth: do not run `betterAuth()` or Better Auth migrations in this
repository.

## Prerequisites

- A Neon project on AWS.
- Neon Auth enabled on the branch.
- The project must not use IP Allow or Private Networking, because Managed Auth
  cannot be enabled there.
- `DATABASE_URL` for the same branch.

Enable Auth from the Neon Console, or with `neon.ts`:

```ts
import { defineConfig } from "@neon/config/v1";

export default defineConfig({
  auth: true,
});
```

```bash
neon deploy
neon neon-auth status
```

## Environment variables

Get the branch Auth URL from `neon neon-auth status`, `neon env pull`, or
`get_neon_auth_config`. It includes a path:

```text
https://ep-xxxx.aws.neon.tech/neondb/auth
```

Set:

```text
NEON_AUTH_BASE_URL=https://ep-xxxx.aws.neon.tech/neondb/auth
AUTH_ENABLED=true
AUTH_PROFILES_ENABLED=true
AUTH_ALGORITHMS=EdDSA
```

The backend derives:

| Setting | Derived value |
|---|---|
| `AUTH_ISSUER` | `https://ep-xxxx.aws.neon.tech` (origin only) |
| `AUTH_AUDIENCE` | same origin |
| `AUTH_JWKS_URL` | `<NEON_AUTH_BASE_URL>/.well-known/jwks.json` |

Explicit values override the derivation. Do not set the issuer to the full path;
Neon sets `iss` and `aud` to the **origin**.

`AUTH_DEV_MODE` is not used with Neon Auth. Keep it `false`; it is only for
local/test HS256 tokens.

## Token contract

| Claim | Use |
|---|---|
| `sub` | Stable user id; mapped to `users.auth_subject` with `auth_issuer` |
| `email` | Stored only when `emailVerified` is true |
| `emailVerified` | Camel-case claim from Neon; the backend also accepts `email_verified` |
| `name` | Optional display name |
| `iss` / `aud` | Neon Auth origin |
| `role` | Neon/Better Auth role; **not** used for app authorization |
| `exp` | 15 minutes |

The backend requires `exp`, `sub`, `iss`, and `aud`, and allows `EdDSA` by
default. Application roles always come from `user_roles`.

## Frontend (Vue/Vite)

```bash
npm install @neon/auth
```

```ts
// src/lib/auth.ts
import { createAuthClient } from "@neon/auth";
import { BetterAuthReactAdapter } from "@neon/auth/react/adapters";

export const authClient = createAuthClient(import.meta.env.VITE_NEON_AUTH_URL, {
  adapter: BetterAuthReactAdapter({
    fetchOptions: { credentials: "include" },
  }),
});
```

```ts
// before calling the API
const { data, error } = await authClient.getSession();
if (error || !data?.session?.token) {
  // redirect to sign-in
}
const token = data.session.token;
```

```ts
await fetch(`${import.meta.env.VITE_API_BASE_URL}/api/v1/me`, {
  headers: { Authorization: `Bearer ${token}` },
});
```

`VITE_NEON_AUTH_URL` is the public Auth URL for the browser. `NEON_AUTH_BASE_URL`
is the server-side name. They usually point to the same branch URL.

## Trusted domains

Neon Auth only redirects to allowlisted origins:

```bash
neon neon-auth domain add https://jymz.pages.dev
neon neon-auth domain add http://localhost:5173
neon neon-auth domain list
```

Remove localhost for production:

```bash
neon neon-auth domain delete http://localhost:5173
neon neon-auth allow-localhost disable
```

## Verification

1. Run `alembic upgrade head` against `DATABASE_URL`.
2. Start the API with the env above.
3. Sign in through the frontend.
4. Confirm the request carries `Authorization: Bearer ...`.
5. `GET /api/v1/me` returns the Neon `sub` mapped user.
6. `GET /ready` returns `database: ok`.
7. Sign out, sign in again, and refresh the page; the session must survive.

If the token is rejected, check:

- issuer/audience are the **origin**, not the full `/neondb/auth` path;
- the JWKS URL belongs to the same branch;
- `AUTH_ALGORITHMS` includes `EdDSA`;
- the token has not expired (15 minutes);
- `AUTH_PROFILES_ENABLED=true` and `AUTH_ENABLED=true`.

## Production checklist

- [ ] Neon Auth enabled on the production branch.
- [ ] Custom SMTP configured for production auth emails.
- [ ] `NEON_AUTH_BASE_URL` set on the API host.
- [ ] `AUTH_ENABLED=true`, `AUTH_PROFILES_ENABLED=true`.
- [ ] `AUTH_DEV_MODE=false`.
- [ ] `CORS_ORIGINS=https://jymz.pages.dev`.
- [ ] Trusted domains include the production frontend only.
- [ ] `alembic upgrade head` completed.
- [ ] `/ready` shows `database: ok`.
- [ ] Sign-up, sign-in, refresh, sign-out tested end to end.

Official docs: <https://neon.com/docs/auth/overview> and
<https://neon.com/docs/auth/guides/plugins/jwt>.
