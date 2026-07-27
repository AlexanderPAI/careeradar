# Production TLS setup

The production Nginx configuration expects a Let's Encrypt-compatible
certificate layout outside the repository.

Before deployment:

1. Point the domain's `A`/`AAAA` record to the VPS.
2. Allow inbound TCP ports `80` and `443` in the VPS firewall.
3. Copy `.env.example` to `.env` and set:

   ```env
   DOMAIN=careeradar.example.com
   LETSENCRYPT_DIR=/etc/letsencrypt
   ```

4. Obtain a certificate on the VPS. Its files must exist at:

   ```text
   /etc/letsencrypt/live/<DOMAIN>/fullchain.pem
   /etc/letsencrypt/live/<DOMAIN>/privkey.pem
   ```

5. Start the production stack:

   ```bash
   docker compose -f docker-compose.prod.yaml up -d --build
   ```

Nginx mounts `LETSENCRYPT_DIR` read-only. Never copy certificates or private
keys into the repository.

After certificate renewal, reload Nginx without restarting the application:

```bash
docker compose -f docker-compose.prod.yaml exec nginx nginx -s reload
```
