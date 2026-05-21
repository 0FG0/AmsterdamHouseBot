# Amsterdam House Bot

Telegram bot that scans Amsterdam rental listings and sends a message when a new listing matches a user's filters.

Supported sources:

- Pararius
- Funda
- Kamernet
- Huurwoningen
- Roofz

The bot stores user filters and already-seen listings in SQLite, so duplicate listings are not sent twice.

## What it does

- Runs a scheduled scan every `POLL_INTERVAL_SECONDS` seconds
- Lets each Telegram user save their own Kamernet property type, rent, bedroom/room, and surface-area filters
- Sends new listings directly in Telegram
- Supports an on-demand scan with `/test`

## Prerequisites

- Python 3
- A Telegram bot token from BotFather

## Setup From Zero

### 1. Open the project

If you already have the folder locally, just open it in VS Code or your terminal.

### 2. Create a virtual environment

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

With pip:

```bash
pip install -r requirements.txt
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

### 4. Install browser drivers

Two scrapers require browser automation. Run these once after installing dependencies:

```bash
# For Roofz (Playwright)
playwright install chromium

# For Funda (Camoufox)
python -m camoufox fetch
```

### 5. Create the environment file

Create a `.env` file in the project root with the following content:

```env
TELEGRAM_TOKEN=123456789:replace-with-your-real-token
POLL_INTERVAL_SECONDS=300
DB_PATH=listings.db
TELEGRAM_ALLOWED_CHAT_IDS=123456789
```

Environment variables:

- `TELEGRAM_TOKEN`: required, Telegram bot token from BotFather
- `POLL_INTERVAL_SECONDS`: optional, scan interval in seconds, defaults to `300`
- `DB_PATH`: optional, SQLite database path, defaults to `listings.db`
- `TELEGRAM_ALLOWED_CHAT_IDS`: optional, comma-separated Telegram chat IDs allowed to use the bot. Leave empty for local unrestricted use.

### 6. Start the bot

```bash
python main.py
```

Expected startup message:

```text
Bot started. Press Ctrl+C to stop.
```

On first boot the bot automatically creates the SQLite database and its tables.

## First Use In Telegram

1. Open your bot in Telegram.
2. Send `/start`.
3. Send `/search` to configure:
   - Kamernet property type
   - max monthly rent
   - minimum bedrooms/rooms
   - minimum surface area in square meters
4. Send `/test` to trigger an immediate scan.

After that, the scheduled scanner will keep running in the background while the process stays alive.

## Available Commands

- `/start` - initialize the bot and show help
- `/search` - save or update filters
- `/filters` - show current filters
- `/test` - run a scan immediately
- `/pause` - pause notifications
- `/resume` - resume notifications
- `/clear` - clear the seen listings database
- `/cancel` - cancel the filter setup flow

## How the bot works

1. `main.py` starts the Telegram application.
2. `bot.py` registers commands and schedules the recurring scan job.
3. `scanner.py` runs all scrapers for each active user.
4. `db.py` stores filters and deduplicates listings in SQLite.

## Project Structure

```text
.
|-- bot.py
|-- config.py
|-- db.py
|-- main.py
|-- pyproject.toml
|-- requirements.txt
|-- scanner.py
|-- scrapers/
|   |-- base.py
|   |-- funda.py
|   |-- huurwoningen.py
|   |-- kamernet.py
|   |-- pararius.py
|   `-- roofz.py
`-- uv.lock
```

## Troubleshooting

### `TELEGRAM_TOKEN not found`

Your `.env` file is missing or the token is empty.

### No listings are being sent

- Make sure you ran `/start` and `/search`
- Run `/test` to check whether listings are available right now
- Verify that your Kamernet property type, rent, bedroom/room, and size filters are not too restrictive

### I want to start fresh

Delete `listings.db`, or use `/clear` to clear previously seen listings.

## Run Without VS Code

The bot does not depend on VS Code. Any terminal is fine as long as the virtual environment is active and `.env` is configured.

## Run On A DigitalOcean VPS

The bot uses Telegram polling, so the VPS does not need a public web port for the bot. Keep SSH open for deployment and make sure the droplet can make outbound HTTPS requests.

This setup assumes:

- Ubuntu droplet
- SSH access as `root`
- Your local `.env` contains a valid `TELEGRAM_TOKEN`
- Your local `.env` contains `TELEGRAM_ALLOWED_CHAT_IDS` if the VPS bot should be private
- The VPS should start with a fresh SQLite database

### Deploy From Windows PowerShell

From the project root:

```powershell
.\scripts\deploy.ps1 -Host YOUR_DROPLET_IP
```

If your SSH key is not the default key:

```powershell
.\scripts\deploy.ps1 -Host YOUR_DROPLET_IP -IdentityFile C:\path\to\key
```

The deploy script uploads the project to `/opt/amsterdam-house-bot`, uploads `.env` to `/etc/amsterdam-house-bot/bot.env`, creates `/var/lib/amsterdam-house-bot/listings.db` on first boot, installs dependencies, and starts a `systemd` service.

The local `.env`, `.venv`, `.git`, `__pycache__`, and local database files are excluded from the code archive. The `.env` file is uploaded separately as the service environment file.

### Manage The VPS Service

SSH into the droplet:

```bash
ssh root@YOUR_DROPLET_IP
```

Check status:

```bash
systemctl status amsterdam-house-bot
```

Follow logs:

```bash
journalctl -u amsterdam-house-bot -f
```

Restart the bot:

```bash
systemctl restart amsterdam-house-bot
```

Stop the bot:

```bash
systemctl stop amsterdam-house-bot
```

Show recent logs:

```bash
journalctl -u amsterdam-house-bot -n 100 --no-pager
```

### After Deployment

Open Telegram and send:

```text
/start
/search
/test
```

The bot will continue running after you close your terminal because `systemd` owns the process.
