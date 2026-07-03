import os
import requests
import telebot
import urllib.parse
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

    status_msg = bot.reply_to(message, f"🔍 Recherche & Analyse matérielle pour *{query}*...", parse_mode="Markdown")
    encoded_query = urllib.parse.quote(query)
    
    # Indexeur universel (Scrape des plateformes mondiales comme TorrentGalaxy / 1337x)
    url = f"https://torrent-api-py.vercel.app/api/v1/search?site=tgx&query={encoded_query}"

    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            # Fallback automatique sur un second catalogue si le premier est instable
            url = f"https://torrent-api-py.vercel.app/api/v1/search?site=1377x&query={encoded_query}"
            response = requests.get(url, timeout=15)
            
        data = response.json()
        items = data if isinstance(data, list) else data.get('data', [])

        if not items:
            bot.edit_message_text(f"😕 Aucun résultat trouvé sur le réseau ouvert pour : *{query}*.", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
            return

        valid_results = []
        
        for item in items:
            title = item.get('title') or item.get('name', '')
            title_upper = title.upper()

            # ==========================================
            # 🛡️ LE TRI FILTRE COMPATIBILITÉ MATÉRIEL
            # ==========================================

            # 1. Critère Langue : On exige du MULTI (VF+VO) ou des releases FR contenant des sous-titres
            is_multi_stfr = "MULTI" in title_upper or ("FRENCH" in title_upper and any(sub in title_upper for sub in ["STFR", "SUBFRENCH", "SUBS"]))
            if not is_multi_stfr:
                continue

            # 2. Critère Vidéo : Sécurité Dolby Vision (Pas de DV sans HDR)
            if "DV" in title_upper and "HDR" not in title_upper:
                continue

            # 3. Critère Audio : Priorité absolue Atmos pour ta Barre de Son
            # On cherche de l'E-AC3 (DD+ avec Atmos), du TRUEHD ou le mot clé ATMOS directement
            is_atmos = any(audio in title_upper for audio in ["ATMOS", "E-AC3", "EAC3", "TRUEHD", "DD+"])
            if not is_atmos:
                continue # On ignore si ce n'est pas le bon format audio pour ta barre

            # 4. Extraction du lien magnet
            link = item.get('magnet') or item.get('link')
            if not link:
                continue

            valid_results.append({"title": title, "link": link})

        if not valid_results:
            bot.edit_message_text(
                f"❌ Aucun fichier **MULTI / ATMOS** (compatible HDR/Atmos) trouvé pour *{query}*.\n\n"
                "_Note : Les fichiers Atmos en version française MULTI sont plus rares sur les trackers publics._", 
                chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown"
            )
            return

        # Suppression du message de recherche et affichage des résultats validés
        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        bot.send_message(message.chat.id, f"🍿 **Releases certifiées compatibles Atmos & MULTI pour *{query}* :**", parse_mode="Markdown")

        # Affichage limité aux 5 meilleures opportunités de téléchargement
        for count, torrent in enumerate(valid_results[:5]):
            torrent_id = f"t_{hash(torrent['link']) & 0xffffffff}"
            torrent_storage[torrent_id] = {
                "title": torrent['title'],
                "link": torrent['link']
            }

            markup = InlineKeyboardMarkup()
            btn_debrid = InlineKeyboardButton(text="🚀 Envoyer au NAS (AllDebrid)", callback_data=torrent_id)
            markup.add(btn_debrid)

            bot.send_message(message.chat.id, f"🎬 *{torrent['title']}*", reply_markup=markup, parse_mode="Markdown")

    except Exception as e:
        bot.edit_message_text(f"❌ Erreur lors du scan de l'indexeur public.", chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('t_'))
def handle_debrid_click(call):
    torrent_id = call.data
    if torrent_id not in torrent_storage:
        bot.answer_callback_query(call.id, text="❌ Lien expiré. Relance la recherche.", show_alert=True)
        return

    bot.answer_callback_query(call.id, text="⚡ Expédition vers AllDebrid...")
    torrent_data = torrent_storage[torrent_id]
    
    try:
        alldebrid_url = f"https://api.alldebrid.com/v4/magnet/upload?agent=mytelegramdownloaderbot&apikey={ALLDEBRID_TOKEN}"
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
            bot.send_message(call.message.chat.id, "❌ AllDebrid a refusé le lien.")
    except Exception as e:
        bot.send_message(call.message.chat.id, "❌ Erreur réseau lors du push.")

if __name__ == "__main__":
    bot.remove_webhook()
    import threading
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
