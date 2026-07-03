import os
import requests
import telebot
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# --- ⚙️ VARIABLES D'ENVIRONNEMENT (Strictement calquées sur Render) ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
C411_API_KEY = os.environ.get("C411_API_KEY") 
ALLDEBRID_TOKEN = os.environ.get("ALLDEBRID_TOKEN")

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

# Stockage temporaire des liens torrents
torrent_storage = {}

@app.route('/')
def home():
    return "Your service is live 🎉", 200

@bot.message_handler(commands=['search'])
def search_torrent(message):
    # Récupération du mot-clé recherché
    query = message.text.replace('/search ', '').strip()
    if not query:
        bot.reply_to(message, "❌ Saisis un film après la commande.\nExemple : `/search Gladiator`", parse_mode="Markdown")
        return

    status_msg = bot.reply_to(message, f"🔍 Recherche de *{query}* sur C411...", parse_mode="Markdown")

    # URL API standard Torznab / Newznab utilisée par C411
    api_url = f"https://www.c411.org/api.php?apikey={C411_API_KEY}&t=search&q={query}&o=json"

    try:
        # Navigateur simulé pour éviter le rejet automatique du serveur
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(api_url, headers=headers, timeout=15)
        
        if response.status_code != 200:
            bot.edit_message_text(f"❌ L'API C411 a répondu par une erreur {response.status_code}.", chat_id=message.chat.id, message_id=status_msg.message_id)
            return

        data = response.json()
        
        # Extraction des résultats dans la structure JSON classique
        channel = data.get('channel', {})
        items = channel.get('item', []) if isinstance(channel, dict) else []
        
        # Si la structure est plus simple (directement une liste ou dans 'result')
        if not items and isinstance(data, dict):
            items = data.get('item', []) or data.get('results', [])
        if not items and isinstance(data, list):
            items = data

        if not items:
            bot.edit_message_text(f"😕 Aucun résultat trouvé pour : *{query}*.\nVérifie l'orthographe du film.", chat_id=message.chat.id, message_id=status_msg.message_id, parse_mode="Markdown")
            return

        # Nettoyage du message de statut avant d'afficher les films
        bot.delete_message(chat_id=message.chat.id, message_id=status_msg.message_id)
        bot.send_message(message.chat.id, f"🍿 **Résultats C411 pour *{query}* :**", parse_mode="Markdown")

        count = 0
        for item in items:
            if count >= 5: # On limite à 5 résultats pour ne pas spammer Telegram
                break
                
            title = item.get('title') or item.get('name')
            # Récupération du lien de téléchargement du fichier torrent
            torrent_link = item.get('link') or item.get('enclosure', {}).get('@url')
            
            if not title or not torrent_link:
                continue

            # Filtre pour éviter les doublons DV (Dolby Vision) si pas HDR
            if "DV" in title.upper() and "HDR" not in title.upper():
                continue

            # Création d'un identifiant unique court pour le bouton Telegram
            torrent_id = f"t_{hash(torrent_link) & 0xffffffff}"
            torrent_storage[torrent_id] = {
                "title": title,
                "link": torrent_link
            }

            # Bouton d'action AllDebrid
            markup = InlineKeyboardMarkup()
            btn_debrid = InlineKeyboardButton(text="🚀 Envoyer au NAS (AllDebrid)", callback_data=torrent_id)
            markup.add(btn_debrid)

            bot.send_message(message.chat.id, f"🎬 *{title}*", reply_markup=markup, parse_mode="Markdown")
            count += 1

    except Exception as e:
        bot.edit_message_text(f"❌ Erreur lors de la recherche. Vérifie que ta clé API dans Render est correcte.", chat_id=message.chat.id, message_id=status_msg.message_id)


@bot.callback_query_handler(func=lambda call: call.data.startswith('t_'))
def handle_debrid_click(call):
    torrent_id = call.data
    
    if torrent_id not in torrent_storage:
        bot.answer_callback_query(call.id, text="❌ Lien expiré. Veuillez relancer la recherche.", show_alert=True)
        return

    bot.answer_callback_query(call.id, text="⚡ Envoi en cours à AllDebrid...")
    torrent_data = torrent_storage[torrent_id]
    
    try:
        # Envoi du lien torrent à l'API AllDebrid pour déclencher le téléchargement sur le NAS
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
