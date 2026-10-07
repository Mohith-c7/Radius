# Radius API

FastAPI application responsible for request validation, authentication, API coordination, and dispatching work to Radius domain services.

Business logic belongs in `packages/`, not in API route handlers.

## Authentication Setup

Radius API provides authentication for the dashboard, including:

- Email/password signup and login
- Email verification
- Password reset
- Google OAuth
- GitHub OAuth
- HTTP-only session cookies
- Protected dashboard access
- Logout and session invalidation

### Environment Configuration

Create a local `.env` file from `.env.example`.

The `.env` file must contain a unique `SESSION_SECRET` of at least 32 characters.

Example:

```env
SESSION_SECRET=your_secure_random_secret

GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REDIRECT_URI=http://localhost:8000/api/v1/auth/oauth/google/callback

GITHUB_CLIENT_ID=
GITHUB_CLIENT_SECRET=
GITHUB_REDIRECT_URI=http://localhost:8000/api/v1/auth/oauth/github/callback