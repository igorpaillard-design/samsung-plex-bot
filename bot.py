import os
import requests
import telebot
from flask import Flask
from xml.etree import ElementTree
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ⚙️ ZONE DE CONFIGURATION ---
TELEGRAM_TOKEN = "8749995509:AAGpSgdK1qjm2gul0HKoSRhJtFie_JoRLy4"
C411_PASSKEY = "6d36be5091e57dc7a92d61ae5e688bbe"
SCRAPERAPI_KEY = "aaf70e527297defc81d5bbea36fd8df2"
ALLDEBRID_TOKEN = "1j7FJtz9XDWpRaJEwrSz"

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# Base de données temporaire en mémoire pour stocker les liens des torrents
# Cela évite le bug Telegram des "callback_data" trop longs (> 64 bytes)
torrent_storage = {}

@app.route('/')
def home():
    return "Your service is live 🎉", 200

@bot.message_handler(commands=['search'])
def search_torrent(message):
    query = message.text.replace('/search ', '').strip()
    if not query:
        bot.reply_to(message, "❌ Saisis un film après la commande.\nExemple : `/search Gladiator`", parse_mode="Markdown")
        return

    status_msg = bot.reply_to(message, f"🔍 Recherche de *{query}* en cours via proxy résidentiel...", parse_mode="Markdown")

    # URL du flux RSS de C411 contenant ta passkey d'authentification
    target_url = f"https://www.wawacity.ing/index.php?search={query}&p=torrents&passkey={C411_PASSKEY}"
    
    # Encapsulation dans ScraperAPI pour contourner Cloudflare de manière transparente
    proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={target_url}"

    try:
        response = requests.get(proxy_url, timeout=25)
        
        if response.status_code != 200:
            bot.edit_message_text(f"❌ Le proxy a répondu par une erreur {response.status_code}.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        # Lecture et traitement du XML
        root = ElementTree.fromstring(response.content)
        items = root.findall('.//item')

        if not items:
            bot.edit_message_text("😕 Aucun résultat trouvé pour cette recherche.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        bot.send_message(message.chat.id, f"🍿 **Résultats pour *{query}* :**", parse_mode="Markdown")

        count = 0
        for item in items:
            if count >= 5:  # On limite aux 5 meilleurs résultats
                break
                
            title = item.find('title').text
            torrent_link = item.find('link').text

            # Filtrage automatique du Dolby Vision pur (sans HDR) pour éviter les écrans violets sur Plex
            if "DV" in title.upper() and "HDR" not in title.upper():
                continue

            # Stockage sécurisé du lien avec un identifiant unique ID court
            torrent_id = f"t_{hash(torrent_link) & 0xffffffff}"
            torrent_storage[torrent_id] = {
                "title": title,
                "link": torrent_link
            }

            # Bouton d'action interactif
            markup = InlineKeyboardMarkup()
            btn_debrid = InlineKeyboardButton(text="🚀 Envoyer au NAS (AllDebrid)", callback_data=torrent_id)
            markup.add(btn_debrid)

            bot.send_message(message.chat.id, f"🎬 *{title}*", reply_markup=markup, parse_mode="Markdown")
            count += 1

    except ElementTree.ParseError:
        bot.edit_message_text("⚙️ Erreur : Le flux du site est illisible (Blocage Cloudflare persistant).", chat_id=message.chat.id, message_id=status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Une erreur est survenue : {str(e)}", chat_id=message.chat.id, message_id=status_msg.message_id)


# --- INTERCEPTION DU CLIC SUR LE BOUTON ---
@bot.callback_query_handler(func=lambda call: call.data.startswith('t_'))
def handle_debrid_click(call):
    torrent_id = call.data
    
    if torrent_id not in torrent_storage:
        bot.answer_callback_query(call.id, text="❌ Lien expiré ou introuvable. Relancez la recherche.", show_alert=True)
        return

    bot.answer_callback_query(call.id, text="⚡ Envoi en cours à AllDebrid...")
    torrent_data = torrent_storage[torrent_id]
    
    try:
        # Requête à l'API AllDebrid pour pousser le lien du torrent (.torrent ou magnet)
        alldebrid_url = f"https://api.alldebrid.com/v4/magnet/upload?agent=samsungbot&apikey={ALLDEBRID_TOKEN}"
        payload = {'magnets[]': torrent_data["link"]}
        
        adb_response = requests.post(alldebrid_url, data=payload, timeout=15).json()

        if adb_response.get('status') == 'success':
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✅ *Envoyé au NAS !*\nLe film `{torrent_data['title']}` est pris en charge par AllDebrid.",
                parse_mode="Markdown"
            )
        else:
            error_msg = adb_response.get('error', {}).get('message', 'Erreur de traitement')
            bot.send_message(call.message.chat.id, f"❌ Échec AllDebrid : {error_msg}")

    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erreur lors du transfert : {str(e)}")


if __name__ == "__main__":
    # Nettoyage des webhooks précédents pour éviter les conflits
    bot.remove_webhook()
    
    # Lancement du processus d'écoute Telegram en arrière-plan (Non-bloquant)
    import threading
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    
    # Démarrage obligatoire du serveur Flask sur le port requis par Render
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

