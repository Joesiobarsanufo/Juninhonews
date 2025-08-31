import html
import logging
import os
import random
import time
import json
from datetime import datetime

import ephem
import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup

# --- Configuração básica de logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s')

# --- Constantes Globais ---
NEWS_API_URL = "https://newsapi.org/v2/everything"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
BIBLE_GATEWAY_VOTD_URL = "https://www.biblegateway.com/votd/get/?format=xml&version=ARC"
PENSADOR_URL = "https://www.pensador.com/frases_de_pensadores_famosos/"
E_FARSAS_FEED_URL = "https://www.e-farsas.com/feed" # <-- NOVA FONTE DE FAKE NEWS
EXCHANGE_RATE_API_BASE_URL = "https://v6.exchangerate-api.com/v6"
COMMODITIES_API_BASE_URL = "https://api.commodities-api.com/v1" # <-- API DE COMMODITIES

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
FUSO_BRASIL = pytz.timezone('America/Sao_Paulo')
FILE_PATH_DATAS_COMEMORATIVAS = "datas comemorativas.xlsx"

# --- Carregar Segredos das Variáveis de Ambiente ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
EXCHANGE_RATE_API_KEY = os.getenv('EXCHANGE_RATE_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
COMMODITIES_API_KEY = os.getenv('COMMODITIES_API_KEY') # <-- NOVA CHAVE CARREGADA

# --- Funções Utilitárias e de Busca ---

def safe_request_get(url, params=None, timeout=15, max_retries=2, delay_seconds=3):
    headers = {'User-Agent': USER_AGENT}
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as req_err:
            logging.error(f"Erro na requisição para {url}: {req_err}")
        if attempt < max_retries - 1:
            logging.info(f"Tentando novamente {url} em {delay_seconds}s... (Tentativa {attempt + 1}/{max_retries})")
            time.sleep(delay_seconds)
        else:
            logging.error(f"Máximo de tentativas ({max_retries}) atingido para {url}.")
    return None

def get_commodity_prices(api_key: str | None) -> dict[str, str] | str:
    """Busca preços de commodities da API internacional, converte de USD para BRL e retorna um dict formatado."""
    if not api_key:
        return "⚠️ Cotação de commodities indisponível (API não configurada)."
    
    dolar_str = get_exchange_rate_api("USD", "BRL", EXCHANGE_RATE_API_KEY)
    try:
        dolar_brl_rate = float(dolar_str.replace('.', '').replace(',', '.'))
    except (ValueError, AttributeError):
        logging.error(f"Não foi possível converter a cotação do dólar '{dolar_str}' para conversão.")
        return "⚠️ Erro ao obter taxa do dólar para conversão."

    commodities_map = {"SOYBEAN": "Soja", "CORN": "Milho", "WHEAT": "Trigo", "COFFEE": "Café", "BRENTOIL": "Petróleo (Brent)"}
    symbols_list = ",".join(commodities_map.keys())
    
    url = f"{COMMODITIES_API_BASE_URL}/latest?access_key={api_key}&base=USD&symbols={symbols_list}"
    response = safe_request_get(url)

    if not response: return "❌ Falha na conexão com a API de commodities."
    try:
        data = response.json()
        if data.get("success"):
            rates = data.get("data", {}).get("rates", {})
            if not rates: return "Nenhuma cotação de commodity retornada."
            
            formatted_prices = {}
            for symbol, name in commodities_map.items():
                if symbol in rates:
                    price_usd = 1 / rates[symbol]
                    price_brl = price_usd * dolar_brl_rate
                    formatted_prices[name] = f"R$ {price_brl:,.2f}"
                else:
                    formatted_prices[name] = "Indisponível"
            return formatted_prices
        else:
            error_info = data.get('error', {}).get('info', 'Erro desconhecido.')
            logging.error(f"Erro da API de Commodities: {error_info}")
            return f"⚠️ Erro na API de Commodities."
    except Exception as e:
        logging.exception(f"Erro ao processar dados de commodities: {e}")
        return "❌ Erro ao processar a resposta da API de commodities."

def get_fact_check_feed() -> dict | str :
    response = safe_request_get(E_FARSAS_FEED_URL)
    if response:
        try:
            soup = BeautifulSoup(response.content, 'xml')
            items = soup.find_all("item")
            if items:
                latest_item = items[0] 
                titulo_tag, link_tag = latest_item.find("title"), latest_item.find("link")
                if titulo_tag and link_tag:
                    return {"title": titulo_tag.text.strip(), "link": link_tag.text.strip()}
                return "⚠️ Formato inesperado no feed."
        except Exception as e:
            logging.exception(f"Erro ao processar feed RSS: {e}")
    return "❌ Erro ao buscar notícias de checagem."
    
# ... (demais funções: get_saudacao, fase_da_lua, obter_datas_comemorativas, get_crypto_price, etc. permanecem aqui)
def get_saudacao() -> str:
    hora_atual = datetime.now(FUSO_BRASIL).hour
    if 5 <= hora_atual < 12: return "Bom dia!"
    elif 12 <= hora_atual < 18: return "Boa tarde!"
    else: return "Boa noite!"
def fase_da_lua(data_str_ephem_format: str) -> str:
    try:
        date_observer = ephem.Date(data_str_ephem_format)
        moon = ephem.Moon(date_observer)
        illumination = moon.phase * 100
        if 0 <= illumination < 3: return "Lua Nova 🌑"
        if 3 <= illumination < 48:
            return "Lua Crescente Côncava 🌒" if illumination < 25 else "Lua Crescente Gibosa 🌔"
        if 48 <= illumination < 52: return "Lua Cheia 🌕"
        if 52 <= illumination < 97:
            return "Lua Minguante Gibosa 🌖" if illumination > 75 else "Lua Minguante Côncava 🌘"
        if illumination >= 97: return "Lua Nova (final) 🌑"

        # Fallback for crescent/waning quarters based on trend
        prev_date = ephem.Date(date_observer - 1)
        is_waxing = moon.phase > ephem.Moon(prev_date).phase
        if 23 <= illumination <= 27:
            return "Quarto Crescente 🌓" if is_waxing else "Quarto Minguante 🌗"

        return "Fase Crescente (aprox.) 🌔" if is_waxing else "Fase Minguante (aprox.) 🌖"
    except Exception: return "Fase da lua indisponível"
def obter_datas_comemorativas(file_path: str, sheet_name='tabela') -> str:
    if not os.path.exists(file_path): return "⚠️ Arquivo de datas comemorativas não encontrado."
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        df.columns = ['DataRaw', 'DescricaoRaw'] + list(df.columns[2:])
        df['Data'] = pd.to_datetime(df['DataRaw'], errors='coerce').dt.date
        df = df.dropna(subset=['Data'])
        today = datetime.now(FUSO_BRASIL).date()
        datas_hoje = df[df['Data'] == today]
        if not datas_hoje.empty:
            return "\n".join(f"- {row['DescricaoRaw']}" for _, row in datas_hoje.iterrows())
        return f"Nenhuma data comemorativa listada para hoje ({today.strftime('%d/%m')})."
    except Exception as e:
        logging.exception(f"Erro ao ler/processar datas: {e}")
        return "⚠️ Erro ao carregar datas comemorativas."
def get_crypto_price(coin_id: str, coin_name: str) -> float | None:
    url = f"{COINGECKO_API_URL}?ids={coin_id}&vs_currencies=brl"
    response = safe_request_get(url)
    if response:
        try: return float(response.json().get(coin_id, {}).get("brl"))
        except (ValueError, TypeError, AttributeError): pass
    return None
def get_biblical_verse() -> str:
    response = safe_request_get(BIBLE_GATEWAY_VOTD_URL)
    if response:
        try:
            soup = BeautifulSoup(response.text, 'xml')
            text = soup.find("text").text.strip()
            ref = soup.find("reference").text.strip()
            return f"{html.unescape(text)} ({html.unescape(ref)})"
        except Exception: pass
    return "Não foi possível obter o versículo."
def get_quote_pensador() -> str:
    response = safe_request_get(PENSADOR_URL)
    if response:
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            frase_el = random.choice(soup.select("p.frase"))
            texto_frase = frase_el.text.strip()
            autor_el = frase_el.find_next_sibling("p", class_="autor")
            autor = autor_el.text.strip() if autor_el else "Desconhecido"
            return f'"{texto_frase}" - {autor}'
        except Exception: pass
    return "⚠️ Nenhuma frase encontrada."
def get_exchange_rate_api(base_currency: str, target_currency: str, api_key: str | None) -> str:
    if not api_key: return "Indisponível"
    url = f"{EXCHANGE_RATE_API_BASE_URL}/{api_key}/latest/{base_currency}"
    response = safe_request_get(url)
    if response:
        try:
            data = response.json()
            if data.get("result") == "success":
                rate = data.get("conversion_rates", {}).get(target_currency)
                if rate: return f"{rate:,.2f}"
        except Exception: pass
    return "Erro"
def buscar_noticias_newsapi(query_term: str, max_articles: int = 5) -> tuple[list[dict], str | None]:
    if not NEWS_API_KEY: return [], "⚠️ Chave API NewsAPI não configurada."
    params = {'q': query_term, 'language': 'pt', 'sortBy': 'publishedAt', 'pageSize': max_articles + 10, 'apiKey': NEWS_API_KEY}
    response = safe_request_get(NEWS_API_URL, params=params)
    if not response: return [], f"❌ Falha na conexão com NewsAPI."
    try:
        data = response.json()
        if data.get('status') == 'ok' and data.get('totalResults', 0) > 0:
            articles, titles = [], set()
            for art in data.get('articles', []):
                if art.get('title') not in titles and "[Removed]" not in art.get('title', ''):
                    titles.add(art['title'])
                    articles.append({
                        "title": art['title'],
                        "source": art.get('source', {}).get('name', 'N/A'),
                        "description": (art.get('description') or '')[:150] + '...',
                        "url": art.get('url')
                    })
                if len(articles) >= max_articles: break
            return articles, None
    except Exception: return [], "❌ Erro ao processar notícias da NewsAPI."
    return [], f"Nenhuma notícia encontrada para '{query_term}'."

def formatar_para_telegram_plain(jornal_data: dict) -> str:
    plain_list = [
        f"📰 Juninho News - {jornal_data['data_display']}",
        f"📌 De Pires do Rio-GO",
        f"🌒 Fase da Lua: {jornal_data['fase_lua']}",
        "",
        "💭 Frase de Hoje",
        jornal_data['frase_dia'],
        "",
        "📖 Versículo do Dia",
        jornal_data['versiculo_dia'],
        "",
        "🙏 Agradecemos por acompanhar nosso jornal",
        "!Se gostou do conteúdo e quer apoiar nosso trabalho, qualquer contribuição via Pix é muito bem-vinda! 💙",
        "📌 Chave Pix: 64992115946",
        "Seu apoio nos ajuda a continuar trazendo informações com qualidade e dedicação. Obrigado! 😊",
        "",
        f"🗓 HOJE É DIA... {jornal_data['data_display']}:",
        jornal_data['datas_comemorativas'],
        "",
        f" 💵 Cotação do Dólar: R$ {jornal_data['cotacoes']['dolar']}",
        f" 💶 Cotação do Euro: R$ {jornal_data['cotacoes']['euro']}",
        f" 🪙 Cotação do Ethereum: R${jornal_data['cotacoes']['eth_plain_str']}",
        f" 🪙 Cotação do Bitcoin: R$ {jornal_data['cotacoes']['btc_plain_str']}",
        ""
    ]
    
    # Seção de Commodities (API Internacional)
    plain_list.append(f"🌾 Cotação de Commodities (ref. Dólar)")
    commodities_data = jornal_data.get('commodities')
    if isinstance(commodities_data, dict):
        for name, price in commodities_data.items():
            plain_list.append(f" - {name}: {price}")
        plain_list.append("Fonte: commodities-api.com")
    else:
        plain_list.append(str(commodities_data))
    plain_list.append("")
    
    # Notícias
    for secao, artigos in jornal_data['noticias'].items():
        plain_list.extend([f"\n{secao}  ", f"📢 Últimas notícias de {secao.split(' ', 1)[-1].strip()}:\n"])
        if isinstance(artigos, str):
            plain_list.append(artigos)
        else:
            for art in artigos:
                plain_list.append(f"📰 {art['title']}")
                plain_list.append(f"🏷 Fonte: {art['source']}")
                if art['description']: plain_list.append(f"📝 {art['description']}")
                if art['url']: plain_list.append(f"🔗 {art['url']}")
                plain_list.append("")
        plain_list.append("")

    # Checagem de Fatos
    plain_list.append("🔎 CHECAGEM DE FATOS") 
    fact_check_data = jornal_data['fact_check']
    if isinstance(fact_check_data, dict):
        plain_list.extend([
            f"🛑 {fact_check_data['title']}",
            f"🔗 {fact_check_data['link']}",
            "Fonte: E-Farsas.com"
        ])
    else: 
        plain_list.append(str(fact_check_data))
    plain_list.append("")
    
    return "\n".join(plain_list)

def send_telegram_message(bot_token: str, chat_id: str, message_text: str):
    # ... (função de envio para o Telegram permanece a mesma)
    if not bot_token or not chat_id: return False
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    max_length = 4096
    if len(message_text) <= max_length:
        messages_to_send = [message_text]
    else:
        messages_to_send = []
        temp_message = ""
        for line in message_text.splitlines(keepends=True):
            if len(temp_message) + len(line) > max_length:
                messages_to_send.append(temp_message)
                temp_message = line
            else:
                temp_message += line
        if temp_message: messages_to_send.append(temp_message)

    success = True
    for part in messages_to_send:
        payload = {'chat_id': chat_id, 'text': part, 'disable_web_page_preview': False}
        try:
            response = requests.post(send_url, data=payload, timeout=30)
            if response.status_code != 200:
                logging.error(f"Falha envio Telegram: {response.text}")
                success = False
            time.sleep(2)
        except requests.exceptions.RequestException as e:
            logging.exception(f"Exceção envio Telegram: {e}")
            success = False
    return success

def main_automated():
    logging.info("Iniciando execução do Juninho News Automatizado.")
    if not all([NEWS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, COMMODITIES_API_KEY]):
        logging.critical("ERRO CRÍTICO: Variáveis de ambiente essenciais não configuradas!")
        return

    current_time = datetime.now(FUSO_BRASIL)
    eth, btc = get_crypto_price('ethereum', 'ETH'), get_crypto_price('bitcoin', 'BTC')
    
    jornal_data = {
        'data_display': current_time.strftime('%d/%m/%Y'),
        'fase_lua': fase_da_lua(current_time.strftime('%Y/%m/%d')),
        'frase_dia': get_quote_pensador(),
        'versiculo_dia': get_biblical_verse(),
        'datas_comemorativas': obter_datas_comemorativas(FILE_PATH_DATAS_COMEMORATIVAS),
        'cotacoes': {
            'dolar': get_exchange_rate_api("USD", "BRL", EXCHANGE_RATE_API_KEY),
            'euro': get_exchange_rate_api("EUR", "BRL", EXCHANGE_RATE_API_KEY),
            'eth_plain_str': f"{eth:,.2f}" if eth else "Indisponível",
            'btc_plain_str': f"{btc:,.2f}" if btc else "Indisponível",
        },
        'commodities': get_commodity_prices(COMMODITIES_API_KEY),
        'noticias': {},
        'fact_check': get_fact_check_feed()
    }

    news_sections = {
        "🇧🇷 BRASIL GERAL": "Brasil", "🟢 Goiás (Estado)": "Goiás", "🌍 Geopolítica": "Geopolítica",
        "🌐 INTERNACIONAL": "Mundo", "⚽ Futebol": "Futebol Brasileiro", "💰 ECONOMIA & NEGÓCIOS": "Economia Brasil",
        "🍀 LOTERIAS": "Mega-Sena OR Quina OR Lotofácil", "🌟 FAMA & ENTRETENIMENTO": "Celebridades Brasil",
        "✈️ TURISMO": "Turismo Brasil", "🏆 ESPORTES": "Esportes Brasil -futebol", "💻 Tecnologia": "Tecnologia Brasil"
    }
    for title, query in news_sections.items():
        articles, error_msg = buscar_noticias_newsapi(query)
        jornal_data['noticias'][title] = articles if articles else error_msg or "Nenhuma notícia encontrada."

    message = formatar_para_telegram_plain(jornal_data)
    if send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, message):
        logging.info("Juninho News enviado com sucesso para o Telegram!")
    else:
        logging.error("Falha CRÍTICA ao enviar a mensagem completa para o Telegram.")

if __name__ == "__main__":
    try:
        main_automated()
    except Exception as e:
        logging.critical(f"Erro inesperado na execução principal: {e}", exc_info=True)
        # O try/except de debug mais detalhado foi removido para a versão final,
        # mas a exceção ainda será logada como CRITICAL.
