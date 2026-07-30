# 🤖 FarmBot — Discord Member Farming Bot

A fully-featured Discord bot for farming authorized members into servers, with role-tier limits, OAuth2 authorization, and owner controls.

---

## ✅ Setup Checklist

### 1. Discord Developer Portal
1. Go to [discord.com/developers/applications](https://discord.com/developers/applications)
2. Create a new application (or use an existing one)
3. Under **Bot**: copy the **Token** → save as `DISCORD_BOT_TOKEN` secret in Replit
4. Under **OAuth2 → General**: copy **Client ID** → save as `DISCORD_CLIENT_ID`
5. Copy **Client Secret** → save as `DISCORD_CLIENT_SECRET`
6. Under **OAuth2 → Redirects**: add your redirect URL (see step 3)

### 2. Redirect URI
Your redirect URL is:
```
https://<your-replit-dev-domain>/api/auth/callback
```
- Find it by running `!setredirect` in Discord after the bot starts
- Add it to Discord Developer Portal → OAuth2 → Redirects
- Save it as the `REDIRECT_URI` secret in Replit

### 3. Invite the Bot
Use this URL (replace `CLIENT_ID`):
```
https://discord.com/api/oauth2/authorize?client_id=CLIENT_ID&permissions=8&scope=bot%20applications.commands
```
Or use `!lauth` → **add-bot** button.

---

## 🏷️ Role Tiers

| Role     | Members per `!farm` |
|----------|---------------------|
| member   | 2                   |
| silver   | 10                  |
| gold     | 15                  |
| diamond  | 25                  |
| premium  | 35                  |

Assign roles with `!giverole @user silver` etc.

---

## 📋 All Commands

### General
| Command | Description |
|---------|-------------|
| `!ping` | Check latency |
| `!help` | Show all commands |
| `!lauth` | Auth embed with add-bot / auth-bot buttons |
| `!myauth` | Check your authorization status |
| `!authcount` | Total authorized users + global farm stats |
| `!roles` | View role tiers |
| `!farmstats` | Your farm history |
| `!tutorial` | Show how-to guide |

### Farming
| Command | Description |
|---------|-------------|
| `!farm <server_id>` | Add members to a server (tier-limited) |

### Role Management (requires Manage Roles)
| Command | Description |
|---------|-------------|
| `!giverole @user <role>` | Give a role to a member |
| `!removerole @user <role>` | Remove a role from a member |

### Owner Only (ID: 1262731338872651856)
| Command | Description |
|---------|-------------|
| `!ownerhelp` | Full owner command list |
| `!giveaccess <user_id>` | Grant user access to `!farm` |
| `!removeaccess <user_id>` | Revoke user's farm access |
| `!listusers` | All users with farm access |
| `!clearauth <user_id>` | Remove a user's OAuth token |
| `!grantserver <server_id>` | Whitelist a server |
| `!revokeserver <server_id>` | Remove server from whitelist |
| `!listservers` | All whitelisted servers |
| `!serverinfo <server_id>` | Info about a server |
| `!resetfarm <user_id>` | Reset farm stats for a user |
| `!announce <message>` | DM all authorized users |
| `!botinfo` | Bot-wide statistics |
| `!settutorial <text>` | Edit the `!tutorial` text |
| `!setredirect` | Show redirect URI setup instructions |

---

## 🔄 How `!farm` Works

1. User runs `!farm <server_id>`
2. Bot checks: does the user have access? Is the server whitelisted? Is bot in the server?
3. Pulls N authorized users from the database (N = your role tier limit)
4. Calls Discord API `PUT /guilds/{id}/members/{user_id}` with each user's OAuth token
5. Reports how many were added

**Pre-granted server:** `1532047125742096394` is already whitelisted.

---

## 🏗️ File Structure

```
discord-bot/
├── bot.py           ← main bot file (all commands)
├── database.py      ← SQLite async helpers
├── config.py        ← constants & env var loading
├── requirements.txt ← Python dependencies
├── start.sh         ← startup script
├── bot_data.db      ← SQLite database (auto-created)
└── pending_auth/    ← OAuth token drop zone (auto-created)

artifacts/api-server/src/routes/
└── auth.ts          ← Express OAuth2 callback handler
```

---

## ⚙️ Environment Variables / Secrets

| Key | Description |
|-----|-------------|
| `DISCORD_BOT_TOKEN` | Bot token from Developer Portal |
| `DISCORD_CLIENT_ID` | OAuth2 Client ID |
| `DISCORD_CLIENT_SECRET` | OAuth2 Client Secret |
| `REDIRECT_URI` | Full redirect URL (e.g. `https://xyz.replit.dev/api/auth/callback`) |
