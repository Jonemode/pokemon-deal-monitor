# Running on a server

The monitor runs on a DigitalOcean Droplet (Ubuntu 24.04, 1 GB) as a
systemd service. It only makes outbound HTTPS calls, so the firewall allows
SSH alone.

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
       ufw allow OpenSSH && ufw --force enable

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

       ssh pokemon-monitor systemctl enable pokemon-deal-monitor
