"""Asistente local: pide token sin mostrarlo y encuentra grupos mediante /config."""
from getpass import getpass
import os
import sys
from bot import BotError, telegram


def main():
    token = getpass("Pegá el token de BotFather (no se verá ni se guardará): ").strip()
    os.environ["TELEGRAM_BOT_TOKEN"] = token
    me = telegram("getMe", {})
    username = me["username"]
    webhook = telegram("getWebhookInfo", {})
    if webhook.get("url"):
        raise BotError("Este bot ya tiene un webhook. Creá uno dedicado para no alterar otro servicio.")
    print(f"Bot verificado: @{username}")
    print(f"Agregalo a tu grupo y enviá allí /config@{username}")
    input("Presioná Enter después de enviar ese comando... ")
    updates = telegram("getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
    groups = {}
    for update in updates:
        msg = update.get("message", {})
        chat = msg.get("chat", {})
        if (chat.get("type") in ("group", "supergroup") and
                msg.get("text", "").split()[:1] == [f"/config@{username}"]):
            groups[chat["id"]] = chat.get("title", "Grupo")
    if not groups:
        raise BotError("No encontré /config dirigido al bot en un grupo. Repetí el asistente.")
    print("\nGuardá estos datos en GitHub > Settings > Secrets and variables > Actions:")
    print("TELEGRAM_BOT_TOKEN: el token que recibiste de BotFather")
    for ident, title in groups.items():
        print(f"TELEGRAM_CHAT_ID: {ident}  (grupo: {title})")
    print("Elegí un solo grupo. El asistente no envió mensajes ni guardó tu token.")


if __name__ == "__main__":
    try:
        main()
    except (BotError, KeyboardInterrupt, EOFError) as error:
        print(str(error) if isinstance(error, BotError) else "Cancelado.", file=sys.stderr)
        sys.exit(1)
    finally:
        os.environ.pop("TELEGRAM_BOT_TOKEN", None)
