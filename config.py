import os

BOT_TOKEN      = os.getenv("DISCORD_BOT_TOKEN", "")
CLIENT_ID      = os.getenv("DISCORD_CLIENT_ID", "")
CLIENT_SECRET  = os.getenv("DISCORD_CLIENT_SECRET", "")
REDIRECT_URI   = os.getenv("REDIRECT_URI", "https://63613fa8-a47c-4098-8285-40cbe77256cc-00-2wk32jphueo2r.sisko.replit.dev/api/auth/callback")

OWNER_ID            = 1262731338872651856
PRE_GRANTED_GUILD   = 1532047125742096394

# Role name (lower-case) → max members per !farm
ROLE_TIERS = {
    "premium": 35,
    "diamond": 25,
    "gold":    15,
    "silver":  10,
    "member":   2,
}

DISCORD_API = "https://discord.com/api/v10"
