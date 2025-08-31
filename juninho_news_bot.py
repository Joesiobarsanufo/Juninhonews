import html
import logging
import os
import random
import time
import json
from datetime import datetime, timedelta

import ephem
import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup # lxml precisará estar instalado para 'xml' parser

# --- Configuração básica de logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s')

# --- Constantes Globais ---
NEWS_API_URL = "https://newsapi.org/v2/everything"
COINGECKO_API_URL = "https://api.coingecko.com/api/v3/simple/price"
BIBLE_GATEWAY_VOTD_URL = "https://www.biblegateway.com/votd/get/?format=xml&version=ARC"
PENSADOR_URL = "https://www.pensador.com/frases_de_pensadores_famosos/"
BOATOS_ORG_FEED_URL = "https://www.boatos.org/feed"
EXCHANGE_RATE_API_BASE_URL = "https://v6.exchangerate-api.com/v6"

# CORRIGIDO: User-Agent de um navegador comum para evitar bloqueios
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
FUSO_BRASIL = pytz.timezone('America/Sao_Paulo')
FILE_PATH_DATAS_COMEMORATIVAS = "datas comemorativas.xlsx"

# --- Carregar Segredos das Variáveis de Ambiente ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
EXCHANGE_RATE_API_KEY = os.getenv('EXCHANGE_RATE_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

# --- Funções Utilitárias e de Busca ---

def safe_request_get(url, params=None, timeout=10, max_retries=2, delay_seconds=2):
    headers = {'User-Agent': USER_AGENT}
    if not ("newsapi.org" in url and NEWS_API_KEY) and not ("api.coingecko.com" in url):
        headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        headers['Pragma'] = 'no-cache'
        headers['Expires'] = '0'
    for attempt in range(max_retries):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as http_err:
            logging.error(f"HTTP error: {http_err} (URL: {url}, Status: {http_err.response.status_code})")
            if http_err.response.status_code in [401, 403, 404]:
                logging.error(f"Erro de Cliente ({http_err.response.status_code}). Acesso negado ou recurso não encontrado.")
                break
            if http_err.response.status_code == 429:
                logging.warning(f"Rate limit atingido. Aguardando {delay_seconds * (attempt + 2)}s.")
                time.sleep(delay_seconds * (attempt + 2))
        except requests.exceptions.ConnectionError as conn_err:
            logging.error(f"Connection error: {conn_err} (URL: {url})")
        except requests.exceptions.Timeout as timeout_err:
            logging.error(f"Timeout error: {timeout_err} (URL: {url})")
        except requests.exceptions.RequestException as req_err:
            logging.error(f"General request error: {req_err} (URL: {url})")
        if attempt < max_retries - 1:
            logging.info(f"Tentando novamente {url} em {delay_seconds}s... (Tentativa {attempt + 1}/{max_retries})")
            time.sleep(delay_seconds)
        else:
            logging.error(f"Máximo de tentativas ({max_retries}) atingido para {url}.")
            break
    return None

def get_saudacao() -> str:
    hora_atual = datetime.now(FUSO_BRASIL).hour
    if 5 <= hora_atual < 12: return "Bom dia!"
    elif 12 <= hora_atual < 18: return "Boa tarde!"
    else: return "Boa noite!"

def fase_da_lua(data_str_ephem_format: str) -> str:
    try:
        date_observer = ephem.Date(data_str_ephem_format)
        moon = ephem.Moon(date_observer)
        illumination = moon.phase 
        prev_date = ephem.Date(date_observer - 1)
        moon_prev = ephem.Moon(prev_date)
        is_waxing = illumination > moon_prev.phase
        if abs(illumination - moon_prev.phase) < 0.5 : 
            pnm = ephem.previous_new_moon(date_observer)
            pfm = ephem.previous_full_moon(date_observer)
            if date_observer == pnm or date_observer == ephem.next_new_moon(date_observer): illumination = 0
            if date_observer == pfm or date_observer == ephem.next_full_moon(date_observer): illumination = 50 
            is_waxing = True if pnm > pfm and date_observer > pnm else (False if pfm > pnm and date_observer > pfm else is_waxing)

        if illumination < 3: return "Lua Nova 🌑"
        if illumination > 97: return "Lua Nova (final) 🌑" 
        if illumination >= 48 and illumination <= 52: return "Lua Cheia 🌕"
        if illumination >= 23 and illumination <= 27:
            return "Quarto Crescente 🌓" if is_waxing else "Quarto Minguante 🌗"
        if is_waxing:
            if illumination < 23: return "Lua Crescente Côncava 🌒"
            if illumination < 48: return "Lua Crescente Gibosa 🌔"
        else: 
            if illumination > 77: return "Lua Minguante Côncava 🌘"
            if illumination > 52: return "Lua Minguante Gibosa 🌖"
        logging.warning(f"Fase da lua (ilum: {illumination}%, crescendo: {is_waxing}) não encaixou, usando fallback.")
        return "Fase Crescente (aprox.) 🌔" if is_waxing else "Fase Minguante (aprox.) 🌖"
    except Exception as e:
        logging.exception(f"Erro ao calcular fase da lua para '{data_str_ephem_format}': {e}")
        return "Fase da lua indisponível"

def obter_datas_comemorativas(file_path: str, sheet_name='tabela') -> str:
    logging.info(f"Tentando ler arquivo de datas: {os.path.abspath(file_path)}")
    if not os.path.exists(file_path):
        logging.warning(f"Arquivo de datas não encontrado em: {file_path}")
        return "⚠️ Arquivo de datas comemorativas não encontrado."
    try:
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        if df.empty or len(df.columns) < 2:
            return "⚠️ Arquivo de datas vazio ou mal formatado."
        df.columns = ['DataRaw', 'DescricaoRaw'] + list(df.columns[2:])
        df['Data'] = pd.to_datetime(df['DataRaw'], errors='coerce')
        df['Descricao'] = df['DescricaoRaw'].astype(str).str.strip()
        data_atual_obj = datetime.now(FUSO_BRASIL).date()
        datas_hoje = df[df['Data'].dt.date == data_atual_obj]
        if not datas_hoje.empty:
            return "\n".join(f"- {row['Descricao']}" for _, row in datas_hoje.iterrows())
        return f"Nenhuma data comemorativa listada para hoje ({data_atual_obj.strftime('%d/%m')})."
    except Exception as e:
        logging.exception(f"Erro ao ler/processar datas: {file_path}: {e}")
        return "⚠️ Erro ao carregar datas comemorativas."

def get_crypto_price(coin_id: str, coin_name: str) -> float | None:
    url = f"{COINGECKO_API_URL}?ids={coin_id}&vs_currencies=brl"
    response = safe_request_get(url)
    if response:
        try:
            data = response.json()
            price = data.get(coin_id, {}).get("brl")
            if price is not None: return float(price)
        except (ValueError, TypeError, AttributeError, requests.exceptions.JSONDecodeError) as e:
            logging.exception(f"Erro ao processar dados de {coin_name} da CoinGecko: {e}")
    return None

def get_biblical_verse() -> str:
    response = safe_request_get(BIBLE_GATEWAY_VOTD_URL)
    if response:
        try:
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'xml')
            verse_text_tag, reference_tag = soup.find("text"), soup.find("reference")
            if verse_text_tag and reference_tag:
                return f"{html.unescape(verse_text_tag.text.strip())} ({html.unescape(reference_tag.text.strip())})"
        except Exception as e: logging.exception(f"Erro ao processar XML da Bible Gateway: {e}")
    return "Não foi possível obter o versículo."

def get_quote_pensador() -> str:
    response = safe_request_get(PENSADOR_URL)
    if response:
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            frases_tags = soup.select("p.frase")
            if frases_tags:
                frase_el = random.choice(frases_tags)
                texto_frase = frase_el.text.strip()
                autor = None
                autor_el_p = frase_el.find_next_sibling("p", class_="autor")
                if autor_el_p and autor_el_p.find('a'): autor = autor_el_p.find('a').text.strip()
                if not autor : 
                    autor_el_span = frase_el.find_parent().find("span", class_="autor")
                    if autor_el_span : autor = autor_el_span.text.strip()
                return f'"{texto_frase}"{f" - {autor}" if autor else ""}'
        except Exception as e: logging.exception(f"Erro ao processar HTML do Pensador.com: {e}")
    return "⚠️ Nenhuma frase encontrada."

def get_boatos_org_feed() -> dict | str :
    response = safe_request_get(BOATOS_ORG_FEED_URL)
    if response:
        try:
            # Usar 'lxml-xml' é mais robusto para feeds RSS, se 'lxml' estiver instalado.
            # Se não, 'xml' é a alternativa padrão do BeautifulSoup.
            soup = BeautifulSoup(response.content, 'xml')
            items = soup.find_all("item")
            
            # Pega o primeiro item do feed, que é o mais recente.
            if items:
                boato = items[0] 
                titulo_tag, link_tag = boato.find("title"), boato.find("link")
                if titulo_tag and link_tag:
                    return {"title": titulo_tag.text.strip(), "link": link_tag.text.strip()}
                return "⚠️ Formato inesperado no feed Boatos.org."
        except Exception as e:
            logging.exception(f"Erro ao processar feed RSS do Boatos.org: {e}")
            if "Couldn't find a tree builder" in str(e):
                return "❌ Erro: Parser XML (lxml) não encontrado."
    return "❌ Erro ao buscar fake news do Boatos.org."

def get_exchange_rate_api(base_currency: str, target_currency: str, api_key: str | None) -> str:
    if api_key:
        url = f"{EXCHANGE_RATE_API_BASE_URL}/{api_key}/latest/{base_currency}"
        response = safe_request_get(url)
        if response:
            try:
                data = response.json()
                if data.get("result") == "success":
                    rate = data.get("conversion_rates", {}).get(target_currency)
                    if rate: return f"{rate:,.2f}" # Mantém formatação com vírgula
                    return f"Erro API ({target_currency}?)"
                return "Erro API Cotação"
            except (requests.exceptions.JSONDecodeError, Exception) as e:
                logging.exception(f"Erro com ExchangeRate-API: {e}")
                return "Erro API (Proc.)"
        return "Falha Conexão API Cotação"
    return "Indisponível (API ñ/config.)"

def get_cepea_prices_scraping() -> dict | str:
    """
    Busca os preços de commodities (Milho, Soja) fazendo web scraping
    do site do CEPEA/USP.
    Retorna um dicionário com os dados ou uma string de erro.
    """
    logging.info("Iniciando busca de preços de commodities via Web Scraping do CEPEA.")
    
    cepea_urls = {
        "Milho": "https://www.cepea.esalq.usp.br/br/indicador/milho.aspx",
        "Soja": "https://www.cepea.esalq.usp.br/br/indicador/soja.aspx",
        "Boi Gordo": "https://www.cepea.esalq.usp.br/br/indicador/boi-gordo.aspx"
    }
    
    commodity_prices = {}
    
    for commodity_name, url in cepea_urls.items():
        try:
            logging.info(f"Buscando dados para {commodity_name} em {url}")
            response = safe_request_get(url)
            if not response:
                commodity_prices[commodity_name] = {"valor": "Falha na conexão", "data": ""}
                continue

            soup = BeautifulSoup(response.content, "html.parser")
            
            valor_div = soup.find('div', class_='imagen_indicador_valor')
            data_div = soup.find('div', class_='imagen_indicador_data')
            
            if valor_div and data_div:
                valor = valor_div.text.strip()
                data_str = data_div.text.strip().split(',')[-1].strip()
                
                commodity_prices[commodity_name] = {"valor": f"R$ {valor}", "data": data_str}
                logging.info(f"Sucesso ao extrair dados para {commodity_name}: {valor} em {data_str}")
            else:
                commodity_prices[commodity_name] = {"valor": "Não encontrado", "data": "N/A"}
                logging.warning(f"Não foi possível encontrar as divs de valor/data para {commodity_name}.")

        except Exception as e:
            logging.exception(f"Erro ao fazer scraping para {commodity_name}: {e}")
            commodity_prices[commodity_name] = {"valor": "Erro no processo", "data": ""}
            
    if not commodity_prices:
        return "⚠️ Falha geral ao buscar dados de commodities do CEPEA."
        
    return commodity_prices


def buscar_noticias_newsapi(query_term: str, max_articles: int = 5) -> tuple[list[dict], str | None]:
    if not NEWS_API_KEY: return [], "⚠️ Chave API NewsAPI não configurada."
    parametros = {'q': query_term, 'language': 'pt', 'sortBy': 'publishedAt', 'pageSize': max_articles + 10, 'apiKey': NEWS_API_KEY}
    response = safe_request_get(NEWS_API_URL, params=parametros)
    if not response: return [], f"❌ Falha NewsAPI para '{query_term}'."
    try: dados = response.json()
    except requests.exceptions.JSONDecodeError:
        logging.error(f"Erro JSON NewsAPI '{query_term}'. Conteúdo: {response.text[:200]}")
        return [], "❌ Erro NewsAPI (JSON)."
    articles_data = []
    if dados.get('status') == 'ok' and dados.get('totalResults', 0) > 0:
        titulos_exibidos = set()
        for art_api in dados.get('articles', []):
            titulo = art_api.get('title')
            if not titulo or "[Removed]" in titulo or titulo in titulos_exibidos: continue
            titulos_exibidos.add(titulo)
            desc = art_api.get('description', "") 
            if len(desc) > 150: desc = desc[:147].strip() + "..."
            articles_data.append({"title": titulo, "source": art_api.get('source', {}).get('name', 'N/A'), "description": desc, "url": art_api.get('url')})
            if len(articles_data) >= max_articles: break
        if not articles_data: return [], f"Nenhuma notícia relevante para '{query_term}' (pós-filtros)."
        return articles_data, None
    elif dados.get('status') == 'error':
        msg = f"⚠️ Erro NewsAPI ({dados.get('code', 'err')}): {dados.get('message', '')}"
        return [], msg
    return [], f"Nenhuma notícia sobre '{query_term}'."

# --- Funções do Telegram ---

def escape_markdown_v2(text: str | None) -> str:
    if text is None: text = ""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f'\\{char}' if char in escape_chars else char for char in text)

def formatar_para_telegram_plain(jornal_data: dict) -> str:
    plain_list = []
    
    data_display = jornal_data["data_display"]
    fase_lua = jornal_data["fase_lua"]
    
    # Cabeçalho
    titulo_news_texto = f'Juninho News - {data_display}'
    plain_list.append(f"📰 {titulo_news_texto}")

    local_texto = 'De Pires do Rio-GO'
    plain_list.append(f"📌 {local_texto}")

    fase_lua_texto = f'Fase da Lua: {fase_lua}'
    plain_list.append(f"🌒 {fase_lua_texto}")
    plain_list.append("")

    # Frase e Versículo
    frase_titulo_texto = 'Frase de Hoje'
    plain_list.append(f"💭 {frase_titulo_texto}")
    plain_list.append(jornal_data['frase_dia'])
    plain_list.append("")

    versiculo_titulo_texto = 'Versículo do Dia'
    plain_list.append(f"📖 {versiculo_titulo_texto}")
    plain_list.append(jornal_data['versiculo_dia'])
    plain_list.append("") 

    # Agradecimento
    plain_list.append("🙏 Agradecemos por acompanhar nosso jornal")
    plain_list.append("!Se gostou do conteúdo e quer apoiar nosso trabalho, qualquer contribuição via Pix é muito bem-vinda! 💙")
    plain_list.append("📌 Chave Pix: 64992115946")
    plain_list.append("Seu apoio nos ajuda a continuar trazendo informações com qualidade e dedicação. Obrigado! 😊")
    plain_list.append("")

    # Datas Comemorativas
    datas_titulo_texto = f'HOJE É DIA... {data_display}:'
    plain_list.append(f"🗓 {datas_titulo_texto}")
    plain_list.append(jornal_data['datas_comemorativas'])
    plain_list.append("")
    
    # Cotações
    plain_list.append(f" 💵 Cotação do Dólar")
    dolar_valor_str = f"R$ {jornal_data['cotacoes']['dolar']}"
    plain_list.append(f" {dolar_valor_str}")
    plain_list.append("")

    plain_list.append(f"💶 Cotação do Euro")
    euro_valor_str = f"R$ {jornal_data['cotacoes']['euro']}"
    plain_list.append(f" {euro_valor_str}")
    plain_list.append("")

    plain_list.append(f"🪙 Cotação do Ethereum")
    eth_valor_str = f"R${jornal_data['cotacoes']['eth_plain_str']}"
    plain_list.append(f" {eth_valor_str}")
    plain_list.append("")

    plain_list.append(f"🪙 Cotação do Bitcoin")
    btc_valor_str = f"R$ {jornal_data['cotacoes']['btc_plain_str']}"
    plain_list.append(f" {btc_valor_str}")
    plain_list.append("")

    # Seção de Commodities (CEPEA)
    plain_list.append(f"🌾 Cotação de Commodities (Mercado Físico BR)")
    commodities_data = jornal_data.get('commodities')
    if isinstance(commodities_data, dict):
        for commodity_name, data in commodities_data.items():
            valor = data.get('valor', 'N/A')
            data_cotacao = data.get('data', '')
            unidade = "saca 60kg" if commodity_name in ["Milho", "Soja"] else "@" if commodity_name == "Boi Gordo" else ""
            plain_list.append(f" - {commodity_name} ({unidade}): {valor} ({data_cotacao})")
        plain_list.append("Fonte: CEPEA/USP")
    else:
        plain_list.append(str(commodities_data))
    plain_list.append("")
    
    # Notícias
    for secao_titulo_com_emoji, artigos_ou_msg in jornal_data['noticias'].items():
        plain_list.append(f"\n{secao_titulo_com_emoji}  ") 
        
        nome_secao_limpo = secao_titulo_com_emoji
        for emoji_char in "🇧🇷🟢🌍🌐⚽💰🍀🌟✈️🏆💻": nome_secao_limpo = nome_secao_limpo.replace(emoji_char, "")
        nome_secao_limpo = nome_secao_limpo.replace("(", "").replace(")", "").replace("&", "e").replace("Estado", "").strip()
        
        sub_titulo_texto = ""
        if "Geopolitica" in nome_secao_limpo: sub_titulo_texto = f"Últimas notícias da Geopolítica mundial:"
        elif "INTERNACIONAL" in secao_titulo_com_emoji: sub_titulo_texto = "Últimas notícias internacionais e do mundo:"
        else: sub_titulo_texto = f"Últimas notícias de {nome_secao_limpo}:"
        plain_list.append(f"📢 {sub_titulo_texto}\n")
            
        if isinstance(artigos_ou_msg, str):
            plain_list.append(artigos_ou_msg)
        else:
            for artigo in artigos_ou_msg:
                plain_list.append(f"📰 {artigo['title']}")
                plain_list.append(f"🏷 Fonte: {artigo['source']}")
                if artigo['description']:
                    desc_limpa = artigo['description'].replace('\r\n', '\n').replace('\r', '\n')
                    plain_list.append(f"📝 {desc_limpa}")
                if artigo['url']:
                    plain_list.append(f"🔗 {artigo['url']}")
                plain_list.append("") 
        plain_list.append("") 
    
    # Fake News
    plain_list.append(f"🔎 #FAKENEWS ") 
    boato_data = jornal_data['fake_news']
    if isinstance(boato_data, dict):
        plain_list.append(f"🛑 Fake News desmentida:")
        plain_list.append(f"📢 {boato_data['title']}")
        plain_list.append(f"🔗 {boato_data['link']}") 
    else: 
        plain_list.append(boato_data)
    plain_list.append("")
    
    return "\n".join(plain_list)

def send_telegram_message(bot_token: str, chat_id: str, message_text: str):
    if not bot_token or not chat_id:
        logging.error("Token do Bot ou Chat ID do Telegram não fornecidos.")
        return False
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    max_length, messages_to_send = 4096, []
    
    if len(message_text) > max_length:
        logging.warning(f"Mensagem ({len(message_text)} caracteres) excede limite. Será dividida.")
        current_part, temp_parts, current_line_buffer = "", [], ""
        for line in message_text.splitlines(keepends=True):
            if len(current_line_buffer) + len(line) <= max_length: current_line_buffer += line
            else:
                if current_line_buffer: temp_parts.append(current_line_buffer)
                current_line_buffer = line
        if current_line_buffer: temp_parts.append(current_line_buffer)
        for part in temp_parts:
            if len(part) > max_length:
                logging.warning(f"Sub-parte da mensagem ({len(part)}) ainda excede limite. Será truncada.")
                messages_to_send.append(part[:max_length - 30] + "\n...[mensagem cortada]...")
            else: messages_to_send.append(part)
        if not messages_to_send and message_text: 
                messages_to_send.append(message_text[:max_length - 30] + "\n...[mensagem cortada]...")
    else: messages_to_send.append(message_text)

    all_sent_successfully = True
    for i, part_message in enumerate(messages_to_send):
        if not part_message.strip(): continue
        payload = {'chat_id': chat_id, 'text': part_message, 'disable_web_page_preview': False}
        try:
            response = requests.post(send_url, data=payload, timeout=30)
            response_json = {}
            try: response_json = response.json()
            except json.JSONDecodeError: logging.error(f"Resp Telegram não JSON. Status: {response.status_code}, Resp: {response.text[:200]}")
            
            if response.status_code == 200 and response_json.get("ok"):
                logging.info(f"Parte {i+1}/{len(messages_to_send)} enviada ao Telegram (Chat ID: {chat_id}).")
            else:
                logging.error(f"Falha envio parte {i+1} Telegram. Status: {response.status_code}, Resp: {response.text}")
                all_sent_successfully = False
            time.sleep(2) 
        except requests.exceptions.RequestException as e:
            logging.exception(f"Exceção envio parte {i+1} Telegram: {e}")
            all_sent_successfully = False
    return all_sent_successfully

# --- Função Principal Adaptada para Automação ---
def main_automated():
    logging.info("Iniciando execução do Juninho News Automatizado.")
    if not all([NEWS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logging.critical("ERRO CRÍTICO: Variáveis de ambiente essenciais não configuradas!")
        return

    current_time_obj = datetime.now(FUSO_BRASIL)
    eth_val, btc_val = get_crypto_price('ethereum', 'Ethereum'), get_crypto_price('bitcoin', 'Bitcoin')

    jornal_data = {
        'saudacao': get_saudacao(),
        'data_display': current_time_obj.strftime('%d/%m/%Y'),
        'fase_lua': fase_da_lua(current_time_obj.strftime('%Y/%m/%d')),
        'frase_dia': get_quote_pensador(),
        'versiculo_dia': get_biblical_verse(),
        'datas_comemorativas': obter_datas_comemorativas(FILE_PATH_DATAS_COMEMORATIVAS),
        'cotacoes': {
            'dolar': get_exchange_rate_api("USD", "BRL", EXCHANGE_RATE_API_KEY),
            'euro': get_exchange_rate_api("EUR", "BRL", EXCHANGE_RATE_API_KEY),
            'eth_plain_str': f"{eth_val:,.2f}" if eth_val is not None else "Erro/Indisponível",
            'btc_plain_str': f"{btc_val:,.2f}" if btc_val is not None else "Erro/Indisponível",
        },
        'commodities': get_cepea_prices_scraping(),
        'noticias': {},
        'fake_news': get_boatos_org_feed()
    }

    news_sections_queries = {
        "🇧🇷 BRASIL GERAL": "Brasil", 
        "🟢 Goiás (Estado)": f"Goiás OR \"Estado de Goiás\" NOT \"Goiás Esporte Clube\"",
        "🌍 Geopolítica": "Geopolítica OR \"Relações Internacionais\"", 
        "🌐 INTERNACIONAL": "Internacional OR Mundial NOT Brasil",
        "⚽ Futebol": "Futebol Brasil OR \"Campeonato Brasileiro\" OR Libertadores OR \"Copa do Brasil\"",
        "💰 ECONOMIA & NEGÓCIOS": "\"Economia Brasileira\" OR Inflação OR Selic OR IBGE OR BCB", 
        "🍀 LOTERIAS": "\"Loterias Caixa\" OR Mega-Sena OR Quina OR Lotofácil",
        "🌟 FAMA & ENTRETENIMENTO": "Celebridades OR Entretenimento OR Famosos Brasil", 
        "✈️ TURISMO": "Turismo Brasil OR Viagens OR \"Pontos Turísticos\"", 
        "🏆 ESPORTES": "Esportes Brasil -futebol NOT \"e-sports\"",
        "💻 Tecnologia": "Tecnologia OR Inovação OR Inteligência Artificial OR Startups Brasil"
    }

    for titulo_secao_com_emoji, query in news_sections_queries.items():
        artigos, msg_erro = buscar_noticias_newsapi(query, max_articles=5)
        if msg_erro and not artigos: jornal_data['noticias'][titulo_secao_com_emoji] = msg_erro
        elif not artigos and not msg_erro: jornal_data['noticias'][titulo_secao_com_emoji] = f"Nenhuma notícia relevante para '{query}'."
        else: jornal_data['noticias'][titulo_secao_com_emoji] = artigos

    telegram_message_text = formatar_para_telegram_plain(jornal_data)
    
    # print(telegram_message_text) # Descomente para debug local

    if not send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, telegram_message_text):
        logging.error("Falha CRÍTICA ao enviar a mensagem completa para o Telegram.")
    else:
        logging.info("Juninho News enviado com sucesso para o Telegram!")

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    main_automated()
