# Security Policy

## Reporting a vulnerability

Please report security issues privately via
[GitHub Security Advisories](https://github.com/Kavyvachhani/SysDock/security/advisories/new)
rather than opening a public issue. We aim to acknowledge reports within 72
hours. Do not include exploit details in public issues or pull requests.

## Bind and authentication model

SysDock collects system data; some of it is sensitive. The web/API surface is
designed around least privilege:

- **Localhost by default.** The web server binds `127.0.0.1`. Nothing is exposed
  to the network unless you explicitly pass `--host`.
- **Authentication required for remote exposure.** Binding to a non-loopback
  address requires an auto-generated bearer token; unauthenticated requests to a
  remotely-bound server are rejected. The token is printed once and can be
  regenerated with a flag. *(Enforced from the Phase 4 web rewrite onward.)*
- **No secrets in logs or URLs.** Tokens and anything resembling a secret are
  redacted from logs by `sysdock.core.logging`; tokens are never placed in URLs.
- **No telemetry.** The only network listener is the web server you start.
- **TLS is out of scope.** For remote use, place SysDock behind a reverse proxy
  that terminates TLS, and restrict the port with your host firewall or cloud
  security group. SysDock does not roll its own TLS.

## Subprocess safety

Every external command runs through a single audited helper
(`sysdock.core.proc.run`): argument lists only, never a shell, always a timeout,
tolerant of missing binaries and non-zero exits, and all output is treated as
untrusted input. Dynamic values are never interpolated into command strings.

## Least privilege

SysDock does not require root/admin for anything that does not need it. When not
elevated it shows what is readable and marks the rest unavailable rather than
failing. Any operation that needs elevation is documented at the point of use.

## Supported versions

SysDock is pre-1.0; security fixes land on the latest release line.
