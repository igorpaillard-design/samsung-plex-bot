import os
import requests
import telebot
from flask import Flask
from xml.etree import ElementTree
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ⚙️ ZONE DE CONFIGURATION ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
C411_PASSKEY = os.environ.get("C411_PASSKEY")
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

    status_msg = bot.reply_to(message, f"🔍 Recherche de *{query}* sur C411...", parse_mode="Markdown")

    # URL DU FLUX RSS OFFICIEL DE C411
    target_url = f"https://c411.org/rss.php?search={query}&p=torrents&passkey={C411_PASSKEY}"
    
    # Appel via ScraperAPI avec les options premium pour passer la sécurité à coup sûr
    proxy_url = f"http://api.scraperapi.com?api_key={SCRAPERAPI_KEY}&url={target_url}&render=true&premium=true&antibot=true"

    try:
        response = requests.get(proxy_url, timeout=30)
        
        if response.status_code != 200:
            bot.edit_message_text(f"❌ Le proxy a répondu par une erreur {response.status_code}.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        # Analyse du XML
        root = ElementTree.fromstring(response.content)
        items = root.findall('.//item')

        if not items:
            bot.edit_message_text("😕 Aucun résultat trouvé sur C411 pour cette recherche.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        bot.send_message(message.chat.id, f"🍿 **Résultats C411 pour *{query}* :**", parse_mode="Markdown")

        count = 0
        for item in items:
            if count >= 5:
                break
                
            title = item.find('title').text
            torrent_link = item.find('link').text

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

    except ElementTree.ParseError:
        bot.edit_message_text("⚙️ Erreur de lecture : Le flux renvoyé par C411 est mal formé ou bloqué par Cloudflare.", chat_id=message.chat.id, message_id=status_msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ Une erreur est survenue : {str(e)}", chat_id=message.chat.id, message_id=status_msg.message_id)


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

