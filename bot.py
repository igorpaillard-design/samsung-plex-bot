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

# Mots-clés indispensables pour valider la présence de la Version Française
MOCLES_FR = ["FRENCH", "TRUEFRENCH", "VFF", "MULTI", "VOSTFR", "FR"]

@app.route('/')
def home():
    return "Your service is live 🎉", 200

@bot.message_handler(commands=['search'])
def search_torrent(message):
    query = message.text.replace('/search ', '').strip()
    if not query:
        bot.reply_to(message, "❌ Saisis un film.\nExemple : `/search Gladiator`")
        return

    status_msg = bot.reply_to(message, f"🔍 Recherche filtrée de *{query}* (Filtres FR activés)...", parse_mode="Markdown")
    encoded_query = urllib.parse.quote(query)
    
    # Utilisation d'une API d'indexation ouverte et publique (non bloquée par Render)
    url = f"https:// thosekan.onrender.com/api/v1/search?q={encoded_query}" 
    # Note : On utilise ici un relai d'indexation open-source stable
    url = f"https://api.apilayer.com/torrent/search?q={encoded_query}" # Exemple d'API miroir publique
    
    # Utilisation d'un fallback direct et universel via l'API Open-Torrents
    url = f"https:// torrent-api-py.vercel.app/api/v1/search?site=1377x&query={encoded_query}"

    try:
        response = requests.get(url, timeout=15)
        if response.status_code != 200:
            # Fallback sur un autre indexeur si le premier tousse
            url = f"https://torrent-api-py.vercel.app/api/v1/search?site=tgx&query={encoded_query}"
            response = requests.get(url, timeout=15)
            
        data = response.json()
        items = data if isinstance(data, list) else data.get('data', [])

        if not items:
            bot.edit_message_text(f"😕 Aucun résultat trouvé pour : *{query}*.", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
            return

        valid_results = []
        
        for item in items:
            title = item.get('title') or item.get('name', '')
            title_upper = title.upper()

            # --- 🛡️ TRIPLEX DE FILTRES QUALITÉ & AUDIO ---
            
            # 1. Vérification stricte de la Version Française / Multi
            is_fr = any(token in title_upper for token in MOCLES_FR)
            if not is_fr:
                continue # On rejette si c'est purement d'origine anglaise sans piste FR
                
            # 2. Sécurité formats (Exclusion Dolby Vision seul sans HDR)
            if "DV" in title_upper and "HDR" not in title_upper:
                continue
                
            # 3. Extraction du lien (magnet ou torrent)
            link = item.get('magnet') or item.get('link') or item.get('torrent')
            if not link:
                continue

            valid_results.append({"title": title, "link": link})

        if not valid_results:
            bot.edit_message_text(f"❌ Aucun résultat en **Version Française (VFF/MULTI)** trouvé pour *{query}* sur cette source ouverte.", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
            return

        # Nettoyage et affichage
        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        bot.send_message(message.chat.id, f"🍿 ** releases FR trouvées pour *{query}* :**", parse_mode="Markdown")

        # Affichage des 5 meilleurs résultats correspondants aux critères
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
        bot.edit_message_text(f"❌ Une erreur réseau est survenue avec l'indexeur ouvert.", chat_id=message.chat.id, message_id=status_msg.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('t_'))
def handle_debrid_click(call):
    torrent_id = call.data
    if torrent_id not in torrent_storage:
        bot.answer_callback_query(call.id, text="❌ Lien expiré.", show_alert=True)
        return

    bot.answer_callback_query(call.id, text="⚡ Envoi au NAS...")
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
            bot.send_message(call.message.chat.id, "❌ Échec du transfert AllDebrid.")
    except Exception as e:
        bot.send_message(call.message.chat.id, "❌ Erreur réseau.")

if __name__ == "__main__":
    bot.remove_webhook()
    import threading
    threading.Thread(target=lambda: bot.infinity_polling(skip_pending=True), daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
