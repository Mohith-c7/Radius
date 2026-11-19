Optional signup allowlist for the dashboard (R7): `RADIUS_SIGNUP_ALLOWED_EMAILS` and
`RADIUS_SIGNUP_ALLOWED_DOMAINS`. When set, other addresses cannot sign up, sign in with a password
or through Google/GitHub, or keep a session; uat/production keep the anti-enumeration answers. Empty
keeps open signup, and production logs a startup warning. The login form shows the "Quick Demo
Sign-In" button only in development (`next dev` or `NEXT_PUBLIC_RADIUS_DEMO_SIGNIN=true`, set by
`docker-compose.dev.yml`).
