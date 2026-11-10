# Running on a server

The monitor runs on a DigitalOcean Droplet (Ubuntu 24.04, 1 GB) as a
systemd service. It only makes outbound HTTPS calls. A second service
answers eBay's Marketplace Account Deletion notifications, which eBay
requires apps to subscribe to, behind Caddy for HTTPS, so the firewall
allows SSH, HTTP and HTTPS.

## Day to day

- `make deploy` copies the last commit to the server and restarts the
  service. Commit first: uncommitted changes aren't copied.
- `make logs` follows the service's log. Ctrl-C stops following.
- `ssh pokemon-monitor systemctl status pokemon-deal-monitor` shows whether
  it's running.

Run the monitor in one place only: two copies send duplicate alerts and
share eBay's daily call limit.

## Setting up a new server

These steps assume an SSH config entry named `pokemon-monitor` that logs in
as root.

1. Update the server and allow only SSH in:

       apt-get update && apt-get upgrade -y
       apt-get install -y make sqlite3
       ufw allow OpenSSH && ufw allow 80,443/tcp && ufw --force enable

   Then install Caddy from its apt repository, following
   https://caddyserver.com/docs/install#debian-ubuntu-raspbian. Put the
   new server's IP in `deploy/Caddyfile`'s sslip.io name.

2. Create the user the monitor runs as, with the project as its home:

       useradd --system --create-home --home-dir /opt/pokemon-deal-monitor \
           --shell /usr/sbin/nologin monitor

3. From your computer, copy the code:

       git archive HEAD | ssh pokemon-monitor tar -x -C /opt/pokemon-deal-monitor

4. Copy `.env`, and the database if you have one so listings already
   alerted on aren't alerted again. Take the database copy while the
   monitor is stopped.

       scp .env pokemon-monitor:/opt/pokemon-deal-monitor/.env
       sqlite3 data/monitor.db ".backup /tmp/monitor.db"
       scp /tmp/monitor.db pokemon-monitor:/opt/pokemon-deal-monitor/data/monitor.db
       ssh pokemon-monitor chmod 600 /opt/pokemon-deal-monitor/.env \
           /opt/pokemon-deal-monitor/data/monitor.db

5. `make deploy` sets ownership, installs the service and starts it. The
   first time, also enable it so it starts on boot:

       ssh pokemon-monitor systemctl enable pokemon-deal-monitor ebay-account-deletion

6. On eBay's developer portal, under Application Keysets, open the
   production keyset's Notifications, choose Marketplace Account Deletion,
   and enter the endpoint and token from `.env`
   (`EBAY_DELETION_ENDPOINT`, `EBAY_DELETION_TOKEN`). eBay checks the
   endpoint when you save; "Send Test Notification" should then show in
   `journalctl -u ebay-account-deletion`.
