import os

class config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "8419073003:AAFG1YujfPnjlZ29KjDw1CqCte7p_f0WLTQ")
    OWNER_ID = int(os.getenv("OWNER_ID", "8272867129"))

    # Mongo (use DB_URI as you prefer)
    DB_URI = os.getenv("DB_URI", "mongodb+srv://bikash:bikash@bikash.3jkvhp7.mongodb.net/?retryWrites=true&w=majority")
    MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "sscoverbot")

    # Optional logging channel (keep if you want, else remove)
    LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID", "-1003639320952")
