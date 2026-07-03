import os
import requests
import telebot
import urllib.parse
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ⚙️ VARIABLES D'ENVIRONNEMENT ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
C411_API_KEY = os.environ.get("C411_API_KEY") 
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY")
ALLDEBRID_TOKEN = os.environ.get("ALLDEBRID_TOKEN")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

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

    status_msg = bot.reply_to(message, f"🔍 Recherche sécurisée de *{query}*...", parse_mode="Markdown")

    # 1. On prépare l'URL de l'API C411
    target_url = f"https://www.c411.org/api.php?apikey={C411_API_KEY}&t=search&q={query}&o=json"
    
    # 2. On l'encode proprement pour le proxy
    encoded_url = urllib.parse.quote(target_url)
    
    # 3. On fait passer la requête par ScraperAPI (sans render=true pour que ce soit rapide et au format JSON)
    proxy_url = f"https://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={encoded_url}"

    try:
        response = requests.get(proxy_url, timeout=25)
        
        if response.status_code != 200:
            bot.edit_message_text(f"❌ Le proxy a renvoyé une erreur {response.status_code}.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        data = response.json()
        
        # Extraction intelligente selon la structure renvoyée
        items = []
        if isinstance(data, dict):
            if 'channel' in data and isinstance(data['channel'], dict):
                items = data['channel'].get('item', [])
            else:
                items = data.get('item', []) or data.get('results', [])
        elif isinstance(data, list):
            items = data

        if not items:
            bot.edit_message_text(f"😕 Aucun résultat trouvé pour : *{query}*.", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
            return

        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        bot.send_message(message.chat.id, f"🍿 **Résultats C411 pour *{query}* :**", parse_mode="Markdown")

        count = 0
        for item in items:
            if count >= 5:
                break
                
            title = item.get('title') or item.get('name')
            torrent_link = item.get('link') or item.get('enclosure', {}).get('@url') or item.get('download')
            
            if not title or not torrent_link:
                continue

            if "DV" in title.upper() and "HDR" not in title.upper():
                continue

            torrent_id = f"t_{hash(torrent_link) & 0xffffffff}"
            torrent_storage[torrent_id] = {
                "title": title,
                "link": torrent_link
            }

            markup = InlineKeyboardMarkup()
            btn_debrid = InlineKeyboardButton(text="🚀 Envoyer au NAS (AllDebrid)", callback_data=torrent_id)
            markup.add(btn_debrid)

            bot.send_message(message.chat.id, f"🎬 *{title}*", reply_markup=markup, parse_mode="Markdown")
            count += 1

    except Exception as e:
        bot.edit_message_text(f"❌ Erreur de connexion ou clé API invalide.", chat_id=message.chat.id, message_id=status_msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('t_'))
def handle_debrid_click(call):
    torrent_id = call.data
    
    if torrent_id not in torrent_storage:
        bot.answer_callback_query(call.id, text="❌ Lien expiré. Veuillez relancer la recherche.", show_alert=True)
        return

    bot.answer_callback_query(call.id, text="⚡ Envoi en cours à AllDebrid...")
    torrent_data = torrent_storage[torrent_id]
    
    try:
        alldebrid_url = f"https://api.alldebrid.com/v4/magnet/upload?agent=samsungbot&apikey={ALLDEBRID_TOKEN}"
        payload = {'magnets[]': torrent_data["link"]}
        
        adb_response = requests.post(alldebrid_url, data=payload, timeout=15).json()

        if adb_response.get('status') == 'success':
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✅ *Envoyé au NAS !*\nLe film `{torrent_data['title']}` a été transmis avec succès à AllDebrid.",
                parse_mode="Markdown"
            )
        else:
            error_msg = adb_response.get('error', {}).get('message', 'Erreur de traitement')
            bot.send_message(call.message.chat.id, f"❌ Échec AllDebrid : {error_msg}")

    except Exception as e:
        bot.send_message(call.message.chat.id, f"❌ Erreur lors du transfert : {str(e)}")


if __name__ == "__main__":
    bot.remove_webhook()
    import threading
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
