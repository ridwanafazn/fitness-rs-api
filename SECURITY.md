# Security policy

## Reporting a vulnerability

Please do not open a public issue for a security problem. Contact the
maintainer privately (GitHub: `@ridwanafazn`) with:

- affected endpoint/version
- reproduction steps
- expected vs. actual behavior
- any suggested fix

## Deployment expectations

- Set `API_KEY` for any public deployment.
- Set explicit `CORS_ORIGINS` and `ALLOWED_HOSTS`.
- Keep `TRUST_PROXY_HEADERS=false` unless the API is behind a proxy you
  control.
- Use a shared Redis store for rate limiting when running multiple instances.
- The app checks `Content-Length`; also enforce a body-size limit at your
  reverse proxy for chunked requests.
- Keep dependencies current; Dependabot is configured for pip, Docker, and
  GitHub Actions.
- The API is stateless and does not store user health data. Do not add
  persistence without a privacy/security review.

## Scope

This is a fitness recommendation API, not a medical device. It must not be
used as a substitute for medical advice, diagnosis, or treatment.
