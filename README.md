# Amsterdam House Bot

Telegram bot that scans Amsterdam rental listings and sends a message when a new listing matches a user's filters.

Supported sources:

- Pararius
- Funda
- Kamernet
- Roofz

The bot stores user filters and already-seen listings in SQLite, so duplicate listings are not sent twice.

## What it does

- Runs a scheduled scan every `POLL_INTERVAL_SECONDS` seconds
- Lets each Telegram user save their own price, room, and neighborhood filters
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

```bash
pip install -r requirements.txt
```

### 4. Create the environment file

Copy `.env.example` to `.env`.

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

macOS/Linux:

```bash
cp .env.example .env
```

Then edit `.env` and set your Telegram token.

Example:

```env
TELEGRAM_TOKEN=123456789:replace-with-your-real-token
POLL_INTERVAL_SECONDS=900
DB_PATH=listings.db
```

Environment variables:

- `TELEGRAM_TOKEN`: required, Telegram bot token from BotFather
- `POLL_INTERVAL_SECONDS`: optional, scan interval in seconds, defaults to `900`
- `DB_PATH`: optional, SQLite database path, defaults to `listings.db`

### 5. Start the bot

```bash
python main.py
```

Expected startup message:

```text
Bot avviato. Premi Ctrl+C per fermare.
```

On first boot the bot automatically creates the SQLite database and its tables.

## First Use In Telegram

1. Open your bot in Telegram.
2. Send `/start`.
3. Send `/cerca` to configure:
   - max monthly rent
   - minimum rooms
   - neighborhoods, or `tutte` for all Amsterdam
4. Send `/test` to trigger an immediate scan.

After that, the scheduled scanner will keep running in the background while the process stays alive.

## Available Commands

- `/start` - initialize the bot and show help
- `/cerca` - save or update filters
- `/filtri` - show current filters
- `/test` - run a scan immediately
- `/pausa` - pause notifications
- `/riprendi` - resume notifications
- `/svuota` - clear the seen listings database
- `/annulla` - cancel the filter setup flow

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
|-- scanner.py
|-- scrapers/
|   |-- base.py
|   |-- funda.py
|   |-- kamernet.py
|   |-- pararius.py
|   `-- roofz.py
`-- requirements.txt
```

## Troubleshooting

### `TELEGRAM_TOKEN non trovato`

Your `.env` file is missing or the token is empty.

### No listings are being sent

- Make sure you ran `/start` and `/cerca`
- Run `/test` to check whether listings are available right now
- Verify that your price and room filters are not too restrictive

### I want to start fresh

Delete `listings.db`, or use `/svuota` to clear previously seen listings.

## Run Without VS Code

The bot does not depend on VS Code. Any terminal is fine as long as the virtual environment is active and `.env` is configured.