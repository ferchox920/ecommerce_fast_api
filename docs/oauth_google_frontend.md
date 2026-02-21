# OAuth Google: Backend + Frontend

Este proyecto expone un flujo OAuth para frontend basado en Google Identity Services.

## Backend

Variables de entorno:

- `GOOGLE_OAUTH_CLIENT_ID`

Endpoints:

- `GET /api/v1/auth/oauth/config`: devuelve proveedores OAuth habilitados y su `client_id`.
- `POST /api/v1/auth/oauth/exchange`: recibe `provider` e `id_token`, valida contra Google y retorna `TokenPair` del backend.

Request `oauth/exchange`:

```json
{
  "provider": "google",
  "id_token": "eyJhbGciOi..."
}
```

## Frontend (ejemplo)

```ts
type OAuthProvider = { provider: string; client_id: string };

async function loginWithGoogle() {
  const cfg = await fetch("/api/v1/auth/oauth/config").then(r => r.json()) as { providers: OAuthProvider[] };
  const google = cfg.providers.find(p => p.provider === "google");
  if (!google) throw new Error("Google OAuth no configurado");

  // Requiere cargar https://accounts.google.com/gsi/client
  // google.accounts.id.initialize(...) y obtener credential (id_token).
  const idToken = await getGoogleIdTokenFromGIS(google.client_id);

  const session = await fetch("/api/v1/auth/oauth/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ provider: "google", id_token: idToken }),
  }).then(r => {
    if (!r.ok) throw new Error("OAuth exchange falló");
    return r.json();
  });

  localStorage.setItem("access_token", session.access_token);
  localStorage.setItem("refresh_token", session.refresh_token);
}
```

`getGoogleIdTokenFromGIS` representa el código de tu frontend para abrir el prompt/botón de Google y recuperar `credential`.
