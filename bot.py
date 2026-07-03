import os
import requests
import telebot
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
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
        bot.reply_to(message, "❌ Saisis un film.\nExemple : `/search Gladiator`")
        return

    status_msg = bot.reply_to(message, f"🔍 Recherche de *{query}* via AllDebrid...", parse_mode="Markdown")

    # Moteur de recherche natif de AllDebrid
    url = f"https://api.alldebrid.com/v4/user/links/search?agent=samsungbot&apikey={ALLDEBRID_TOKEN}&search={query}"

    try:
        response = requests.get(url, timeout=15).json()
        
        if response.get('status') != 'success':
            bot.edit_message_text("❌ Erreur lors de la recherche AllDebrid.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        # On récupère les torrents trouvés par AllDebrid sur leurs trackers partenaires
        items = response.get('data', {}).get('agents', [])
        
        if not items:
            bot.edit_message_text(f"😕 Aucun résultat trouvé pour : *{query}*.", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
            return

        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        bot.send_message(message.chat.id, f"🍿 **Résultats trouvés pour *{query}* :**", parse_mode="Markdown")

        count = 0
        for item in items:
            if count >= 5:
                break
                
            title = item.get('title')
            # Lien magnet ou torrent fourni par AllDebrid
            torrent_link = item.get('link') 
            
            if not title or not torrent_link:
                continue

            torrent_id = f"t_{hash(torrent_link) & 0xffffffff}"
            torrent_storage[torrent_id] = {
                "title": title,
                "link": torrent_link
            }

            markup = InlineKeyboardMarkup()
            btn_debrid = InlineKeyboardButton(text="🚀 Envoyer au NAS", callback_data=torrent_id)
            markup.add(btn_debrid)

            bot.send_message(message.chat.id, f"🎬 *{title}*", reply_markup=markup, parse_mode="Markdown")
            count += 1

    except Exception as e:
        bot.edit_message_text(f"❌ Une erreur est survenue.", chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('t_'))
def handle_debrid_click(call):
    torrent_id = call.data
    if torrent_id not in torrent_storage:
        bot.answer_callback_query(call.id, text="❌ Lien expiré.", show_alert=True)
        return

    bot.answer_callback_query(call.id, text="⚡ Envoi au NAS...")
    torrent_data = torrent_storage[torrent_id]
    
    try:
        alldebrid_url = f"https://api.alldebrid.com/v4/magnet/upload?agent=samsungbot&apikey={ALLDEBRID_TOKEN}"
        payload = {'magnets[]': torrent_data["link"]}
        adb_response = requests.post(alldebrid_url, data=payload, timeout=15).json()

        if adb_response.get('status') == 'success':
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"✅ *Envoyé au NAS !*\n`{torrent_data['title']}`",
                parse_mode="Markdown"
            )
        else:
            bot.send_message(call.message.chat.id, "❌ Échec du transfert AllDebrid.")
    except Exception as e:
        bot.send_message(call.message.chat.id, "❌ Erreur réseau.")

if __name__ == "__main__":
    bot.remove_webhook()
    import threading
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
