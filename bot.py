import os
import requests
import xml.etree.ElementTree as ET
import telebot
import threading
from flask import Flask
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# 🔑 CONFIGURATION (N'oublie pas de remettre tes clés !)
TELEGRAM_TOKEN = "8749995509:AAF2WPP7l4wGDJuOcbBVrujtTbPmxzfZUww"
ALLDEBRID_API_KEY = "1j7FJtz9XDWpRaJEwrSz"
C411_PASSKEY = "6d36be5091e57dc7a92d61ae5e688bbe" 

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def analyser_et_noter_torrent(nom):
    nom_clean = nom.upper()
    if "DV" in nom_clean or "DOLBY VISION" in nom_clean:
        if not any(x in nom_clean for x in ["HDR", "HDR10", "HYBRID", "REMUX", "MULTI"]):
            return -1000
            
    score = 100 
    if "HDR10PLUS" in nom_clean or "HDR10+" in nom_clean: score += 50  
    elif "HDR" in nom_clean: score += 20
    if "ATMOS" in nom_clean or "JOC" in nom_clean: score += 40  
    if "640" in nom_clean: score += 30  
    if "320" in nom_clean: score -= 20  
    if "SUPPLY" in nom_clean or "TALNOR" in nom_clean: score += 10
    return score

@bot.message_handler(commands=['search'])
def search_movie(message):
    query = message.text.replace('/search', '').strip()
    if not query:
        bot.reply_to(message, "⚠️ Exemple : `/search Gladiator`")
        return
        
    bot.reply_to(message, f"🔍 Recherche de *{query}* en direct sur C411...")
    url_rss = f"https://c411.org/rss.php?feed=search&search={query}&passkey={C411_PASSKEY}"
    
    try:
        response = requests.get(url_rss, timeout=10)
        if response.status_code != 200:
            bot.reply_to(message, "❌ Impossible de joindre le site pour le moment.")
            return
            
        root = ET.fromstring(response.content)
        items = root.findall('.//item')
        
        fichiers_valides = []
        for item in items:
            titre = item.find('title').text
            lien_torrent = item.find('link').text 
            score = analyser_et_noter_torrent(titre)
            if score > 0:
                fichiers_valides.append((score, titre, lien_torrent))
                
        fichiers_valides.sort(key=lambda x: x[0], reverse=True)
        
        if not fichiers_valides:
            bot.reply_to(message, "❌ Aucun fichier compatible ou trouvé pour ce film.")
            return
            
        for score, titre, lien in fichiers_valides[:3]:
            markup = InlineKeyboardMarkup()
            btn = InlineKeyboardButton("🚀 Envoyer au NAS", callback_data=f"alldeb:{lien}")
            markup.add(btn)
            bot.send_message(message.chat.id, f"🏆 *Score : {score}*\n📦 `{titre}`", parse_mode="Markdown", reply_markup=markup)
            
    except Exception as e:
        bot.reply_to(message, f"⚙️ Erreur : {str(e)}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('alldeb:'))
def callback_send_alldebrid(call):
    url_torrent = call.data.replace('alldeb:', '')
    bot.answer_callback_query(call.id, "Envoi à AllDebrid...")
    
    url_api = f"https://api.alldebrid.com/v4/magnet/upload?agent=samsungbot&apikey={ALLDEBRID_API_KEY}&magnets[]={url_torrent}"
    r = requests.get(url_api).json()
    
    if r.get("status") == "success":
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, 
                              text=call.message.text + "\n\n✅ *Envoyé sur AllDebrid avec succès !*")
    else:
        bot.send_message(call.message.chat.id, "❌ Erreur AllDebrid.")

# --- 🚀 HACK RENDER : Faux serveur Web pour garder le bot en vie ---
app = Flask(__name__)
@app.route('/')
def alive():
    return "Le bot tourne parfaitement !"

def run_bot():
    bot.infinity_polling()

if __name__ == "__main__":
    # Lance le bot Telegram en parallèle
    threading.Thread(target=run_bot).start()
    # Lance le serveur Web pour satisfaire Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
