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
from bs4 import BeautifulSoup
# from unidecode import unidecode # Descomente se for usar para normalizar texto em queries

# --- Configuração básica de logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

# --- Carregar Segredos das Variáveis de Ambiente ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
EXCHANGE_RATE_API_KEY = os.getenv('EXCHANGE_RATE_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

USER_AGENT = "JuninhoNewsBot/1.1 (Automated Script)" # Versão atualizada
FUSO_BRASIL = pytz.timezone('America/Sao_Paulo')
FILE_PATH_DATAS_COMEMORATIVAS = "datas comemorativas.xlsx"

# --- Funções Utilitárias e de Busca ---

def safe_request_get(url, params=None, timeout=10, max_retries=2, delay_seconds=2):
    """Faz uma requisição GET com tratamento de erro, User-Agent e retries."""
    headers = {'User-Agent': USER_AGENT}
    if not ("newsapi.org" in url and NEWS_API_KEY):
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
            if http_err.response.status_code in [401, 403]:
                logging.error("Erro de autorização/permissão.")
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
            logging.info(f"Tentando novamente em {delay_seconds}s... (Tentativa {attempt + 1}/{max_retries})")
            time.sleep(delay_seconds)
        else:
            logging.error(f"Máximo de tentativas ({max_retries}) atingido para {url}.")
            break
    return None

def fase_da_lua(data_str_ephem_format: str) -> str:
    """Calcula a fase da lua para uma data (formato YYYY/MM/DD) de forma simplificada."""
    try:
        date_observer = ephem.Date(data_str_ephem_format)
        moon = ephem.Moon(date_observer)
        
        # moon.phase é a porcentagem de iluminação (0-100)
        illumination = moon.phase

        # Determinar se a lua está crescendo ou minguando
        # Comparamos a iluminação atual com a iluminação de um dia antes e um dia depois
        # Isso é uma simplificação; uma análise mais precisa envolveria os ângulos sol-terra-lua.
        # Para uma aproximação, podemos verificar a fase da próxima lua nova e cheia.
        
        next_new_moon_date = ephem.next_new_moon(date_observer)
        next_full_moon_date = ephem.next_full_moon(date_observer)

        is_waxing = date_observer < next_full_moon_date < next_new_moon_date or \
                    next_new_moon_date < date_observer < next_full_moon_date # Lua está entre Nova e Cheia
        
        if illumination < 3: return "Lua Nova 🌑"
        if illumination > 97: return "Lua Nova (final) 🌑" # Quase nova de novo / fim da minguante

        if illumination >= 47 and illumination <= 53: return "Lua Cheia 🌕"
        
        if illumination >= 22 and illumination <= 28: # Em torno de 25%
            return "Quarto Crescente 🌓" if is_waxing else "Quarto Minguante 🌗"

        if is_waxing:
            if illumination < 22: return "Lua Crescente Côncava 🌒"
            if illumination < 47: return "Lua Crescente Gibosa 🌔"
        else: # Waning
            if illumination > 78: return "Lua Minguante Côncava 🌘" # (Corrigido para > 78 e < 97)
            if illumination > 53: return "Lua Minguante Gibosa 🌖"
        
        # Fallback se a lógica acima não cobrir (improvável com a correção)
        if illumination < 50: return "Fase Crescente (genérico) 🌔"
        else: return "Fase Minguante (genérico) 🌖"

    except Exception as e:
        logging.exception(f"Erro ao calcular fase da lua para '{data_str_ephem_format}': {e}")
        return "Fase da lua indisponível"

def obter_datas_comemorativas(file_path: str, sheet_name='tabela') -> str:
    """Lê datas comemorativas de um arquivo Excel para a data atual."""
    try:
        if not os.path.exists(file_path):
            logging.warning(f"Arquivo de datas comemorativas não encontrado: {file_path}")
            return escape_markdown_v2("⚠️ Arquivo de datas comemorativas não encontrado.")
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        if df.empty or len(df.columns) < 2:
            logging.warning(f"Arquivo de datas comemorativas '{file_path}' está vazio ou com formato incorreto.")
            return escape_markdown_v2("⚠️ Arquivo de datas comemorativas vazio ou mal formatado.")
            
        df.columns = ['DataRaw', 'DescricaoRaw'] + list(df.columns[2:])
        df['Data'] = pd.to_datetime(df['DataRaw'], errors='coerce')
        df['Descricao'] = df['DescricaoRaw'].astype(str).str.strip()
        
        data_atual_obj = datetime.now(FUSO_BRASIL).date()
        datas_hoje = df[df['Data'].dt.date == data_atual_obj]
        
        if not datas_hoje.empty:
            return "\n".join(f"\\- {escape_markdown_v2(row['Descricao'])}" for _, row in datas_hoje.iterrows())
        return escape_markdown_v2(f"Nenhuma data comemorativa listada para hoje ({data_atual_obj.strftime('%d/%m')}).")
    except Exception as e:
        logging.exception(f"Erro ao ler/processar datas comemorativas '{file_path}': {e}")
        return escape_markdown_v2("⚠️ Erro ao carregar datas comemorativas.")

def get_crypto_price(coin_id: str, coin_name: str) -> float | None:
    """Busca preço de criptomoeda da API CoinGecko."""
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=brl"
    response = safe_request_get(url)
    if response:
        try:
            data = response.json()
            price = data.get(coin_id, {}).get("brl")
            if price is not None:
                logging.info(f"Preço de {coin_name} ({coin_id}) obtido: BRL {price}")
                return float(price)
            logging.warning(f"Preço para {coin_name} não encontrado na API CoinGecko: {data}")
        except (ValueError, TypeError, AttributeError, requests.exceptions.JSONDecodeError) as e:
            logging.exception(f"Erro ao processar/decodificar dados de {coin_name} da CoinGecko: {e}")
    return None

def get_biblical_verse() -> str:
    """Obtém o versículo do dia da Bible Gateway."""
    url = "https://www.biblegateway.com/votd/get/?format=xml&version=ARC"
    response = safe_request_get(url)
    if response:
        try:
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'xml')
            verse_text_tag, reference_tag = soup.find("text"), soup.find("reference")
            if verse_text_tag and reference_tag:
                verse = html.unescape(verse_text_tag.text.strip())
                reference = html.unescape(reference_tag.text.strip())
                logging.info(f"Versículo do dia obtido: {reference}")
                return f"{verse} ({reference})"
            logging.warning("Tags 'text' ou 'reference' não encontradas no XML da Bible Gateway.")
            return "Não foi possível obter o versículo (formato inesperado)."
        except Exception as e:
            logging.exception(f"Erro ao processar XML da Bible Gateway: {e}")
    return "Não foi possível obter o versículo (falha na requisição)."

def get_quote_pensador() -> str:
    """Obtém uma frase aleatória do Pensador.com."""
    url = "https://www.pensador.com/frases_de_pensadores_famosos/"
    logging.info("Tentando buscar frase no Pensador.com.")
    response = safe_request_get(url)
    if response:
        try:
            soup = BeautifulSoup(response.text, "html.parser")
            frases_tags = soup.select("p.frase")
            if frases_tags:
                frase_escolhida = random.choice(frases_tags)
                texto_frase = frase_escolhida.text.strip()
                autor = None
                # Tenta encontrar o autor em diferentes estruturas comuns
                autor_tag_p = frase_escolhida.find_next_sibling("p", class_="autor")
                if autor_tag_p:
                    autor_link = autor_tag_p.find('a')
                    if autor_link:
                        autor = autor_link.text.strip()
                if not autor: # Tenta outra estrutura
                    autor_span_parent = frase_escolhida.find_parent().find("span", class_="autor")
                    if autor_span_parent:
                        autor = autor_span_parent.text.strip()
                
                return f'"{texto_frase}"{f" - {autor}" if autor else ""}'
            logging.warning("Nenhuma tag 'p.frase' encontrada no Pensador.com.")
            return "⚠️ Nenhuma frase encontrada (layout pode ter mudado)."
        except Exception as e:
            logging.exception(f"Erro ao processar HTML do Pensador.com: {e}")
    return "❌ Erro ao buscar frase no Pensador.com."

def get_boatos_org_feed() -> dict | str :
    """Obtém uma fake news desmentida do feed RSS do Boatos.org. Retorna dict ou string de erro."""
    url = "https://www.boatos.org/feed"
    response = safe_request_get(url)
    if response:
        try:
            soup = BeautifulSoup(response.content, 'xml')
            items = soup.find_all("item")
            if items:
                boato = random.choice(items)
                titulo_tag = boato.find("title")
                link_tag = boato.find("link")
                if titulo_tag and link_tag:
                    titulo = titulo_tag.text.strip()
                    link = link_tag.text.strip()
                    logging.info("Boato desmentido obtido do Boatos.org.")
                    return {"title": titulo, "link": link}
                logging.warning("Tags 'title' ou 'link' não encontradas no item do feed Boatos.org.")
                return "⚠️ Formato inesperado no item do feed Boatos.org."
            logging.warning("Nenhum item encontrado no feed RSS do Boatos.org.")
            return "⚠️ Nenhuma fake news desmentida encontrada no feed."
        except Exception as e:
            logging.exception(f"Erro ao processar feed RSS do Boatos.org: {e}")
    return "❌ Erro ao buscar fake news do Boatos.org."

def get_exchange_rate_api(base_currency: str, target_currency: str, api_key: str | None) -> str:
    """Obtém cotação de moeda da ExchangeRate-API se a chave estiver disponível, senão placeholder."""
    if api_key:
        url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{base_currency}"
        response = safe_request_get(url)
        if response:
            try:
                data = response.json()
                if data.get("result") == "success":
                    rate = data.get("conversion_rates", {}).get(target_currency)
                    if rate:
                        logging.info(f"Cotação {base_currency}-{target_currency} obtida: {rate}")
                        return f"{rate:.2f}"
                    logging.error(f"Moeda {target_currency} não encontrada na ExchangeRate-API.")
                    return f"Erro API ({target_currency}?)"
                logging.error(f"Falha na ExchangeRate-API: {data.get('error-type', 'Erro')}")
                return "Erro API Cotação"
            except (requests.exceptions.JSONDecodeError, Exception) as e:
                logging.exception(f"Erro com ExchangeRate-API para {base_currency}-{target_currency}: {e}")
                return "Erro API (Proc.)"
        return "Falha Conexão API Cotação"
    logging.warning(f"Cotação de {base_currency}-{target_currency} indisponível. Configure EXCHANGE_RATE_API_KEY.")
    return "Indisponível (API ñ/config.)"

def buscar_noticias_newsapi(query_term: str, max_articles: int = 5) -> tuple[list[dict], str | None]:
    """Busca notícias da NewsAPI e retorna lista de artigos ou mensagem de erro."""
    if not NEWS_API_KEY:
        return [], "⚠️ Chave de API (NewsAPI) não configurada."
    url = "https://newsapi.org/v2/everything"
    # query_api = unidecode(query_term) if 'unidecode' in globals() else query_term # Opcional
    parametros = {
        'q': query_term, 'language': 'pt', 'sortBy': 'publishedAt',
        'pageSize': max_articles + 10, 'apiKey': NEWS_API_KEY
    }
    response = safe_request_get(url, params=parametros)
    if not response:
        return [], f"❌ Falha ao conectar à NewsAPI para '{query_term}'."
    try:
        dados = response.json()
    except requests.exceptions.JSONDecodeError:
        logging.error(f"Erro JSON NewsAPI para '{query_term}'. Conteúdo: {response.text[:200]}")
        return [], "❌ Erro NewsAPI (JSON)."

    articles_data = []
    if dados.get('status') == 'ok' and dados.get('totalResults', 0) > 0:
        titulos_exibidos = set()
        for artigo_api in dados.get('articles', []):
            titulo = artigo_api.get('title')
            if not titulo or "[Removed]" in titulo or titulo in titulos_exibidos: # Filtro melhorado
                continue
            titulos_exibidos.add(titulo)
            descricao = artigo_api.get('description')
            if descricao and len(descricao) > 200:
                descricao = descricao[:197].strip() + "..."
            
            articles_data.append({
                "title": titulo,
                "source": artigo_api.get('source', {}).get('name', 'N/A'),
                "description": descricao if descricao else "", # Garante que é string
                "url": artigo_api.get('url')
            })
            if len(articles_data) >= max_articles:
                break
        if not articles_data:
            return [], f"Nenhuma notícia relevante para '{query_term}' no momento (após filtros)."
        logging.info(f"{len(articles_data)} notícias encontradas para '{query_term}'.")
        return articles_data, None
    elif dados.get('status') == 'error':
        msg = f"⚠️ Erro NewsAPI ({dados.get('code', 'desconhecido')}): {dados.get('message', '')}"
        logging.error(f"Erro da NewsAPI para '{query_term}': {msg}")
        return [], msg
    else:
        logging.info(f"Nenhuma notícia (totalResults: 0 ou status não ok) para '{query_term}'.")
        return [], f"Nenhuma notícia sobre '{query_term}' no momento."

# --- Funções do Telegram ---

def escape_markdown_v2(text: str) -> str:
    """Escapa caracteres especiais para o formato MarkdownV2 do Telegram."""
    if not isinstance(text, str): 
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f'\\{char}' if char in escape_chars else char for char in text)

def formatar_para_telegram(jornal_data: dict) -> str:
    """Formata os dados do jornal para Telegram MarkdownV2."""
    tg_list = []

    # --- Cabeçalho ---
    data_display_str = jornal_data["data_display"]
    titulo_principal_interno = f'📰 Juninho News - {data_display_str}'
    titulo_principal_escapado = escape_markdown_v2(titulo_principal_interno)
    tg_list.append(f"*{titulo_principal_escapado}*")

    local_interno = f'📌 De Pires do Rio-GO'
    local_escapado = escape_markdown_v2(local_interno)
    tg_list.append(f"_{local_escapado}_")

    fase_lua_str = jornal_data["fase_lua"]
    fase_lua_interno = f'🌒 Fase da Lua: {fase_lua_str}'
    fase_lua_escapado = escape_markdown_v2(fase_lua_interno)
    tg_list.append(f"_{fase_lua_escapado}_")
    tg_list.append(escape_markdown_v2("--------------------"))

    # --- Frase e Versículo ---
    frase_dia_str = jornal_data['frase_dia']
    tg_list.append(f"*{escape_markdown_v2('💭 Frase de Hoje')}*")
    tg_list.append(f"_{escape_markdown_v2(frase_dia_str)}_")
    
    versiculo_dia_str = jornal_data['versiculo_dia']
    tg_list.append(f"\n*{escape_markdown_v2('📖 Versículo do Dia')}*") # Adiciona \n para separar visualmente
    tg_list.append(f"_{escape_markdown_v2(versiculo_dia_str)}_")
    tg_list.append(f"_{escape_markdown_v2('Fonte: Bible Gateway (ARC)')}_")
    tg_list.append(escape_markdown_v2("--------------------"))

    # --- Datas Comemorativas ---
    tg_list.append(f"*{escape_markdown_v2(f'🗓️ Datas Comemorativas - {data_display_str}')}*")
    datas_comemorativas_str = jornal_data['datas_comemorativas']
    # A função obter_datas_comemorativas já formata com \- e escapa
    tg_list.append(datas_comemorativas_str)
    tg_list.append(escape_markdown_v2("--------------------"))
    
    # --- Cotações ---
    tg_list.append(f"*{escape_markdown_v2('💹 Cotações')}*")
    dolar_val = escape_markdown_v2(jornal_data['cotacoes']['dolar'])
    euro_val = escape_markdown_v2(jornal_data['cotacoes']['euro'])
    # Para MarkdownV2, parênteses literais precisam ser escapados
    tg_list.append(f"◦ *Dólar \\(USD\\):* R\\$ {dolar_val}") 
    tg_list.append(f"◦ *Euro \\(EUR\\):* R\\$ {euro_val}")   

    eth_str_tg_val = escape_markdown_v2(jornal_data['cotacoes']['eth_str_tg'])
    btc_str_tg_val = escape_markdown_v2(jornal_data['cotacoes']['btc_str_tg'])
    tg_list.append(f"◦ *Ethereum \\(ETH\\):* {eth_str_tg_val}") 
    tg_list.append(f"◦ *Bitcoin \\(BTC\\):* {btc_str_tg_val}")
    tg_list.append(f"_{escape_markdown_v2('Cripto: Dados por CoinGecko')}_")
    tg_list.append(escape_markdown_v2("--------------------"))

    # --- Notícias ---
    for secao_titulo, artigos_ou_msg in jornal_data['noticias'].items():
        tg_list.append(f"*{escape_markdown_v2(secao_titulo)}*")
        if isinstance(artigos_ou_msg, str): # Mensagem de erro/aviso
            tg_list.append(escape_markdown_v2(artigos_ou_msg))
        else: # Lista de artigos
            for artigo in artigos_ou_msg:
                titulo_escaped = escape_markdown_v2(artigo['title'])
                fonte_escaped = escape_markdown_v2(artigo['source'])
                tg_list.append(f"📰 *{titulo_escaped}*")
                tg_list.append(f"_{escape_markdown_v2('Fonte:')} {fonte_escaped}_")
                if artigo['description']: # Garante que description não é None
                    descricao_limpa = artigo['description'].replace('\r\n', '\n').replace('\r', '\n')
                    linhas_descricao_escapadas = [f"> {escape_markdown_v2(linha.strip())}" for linha in descricao_limpa.split('\n') if linha.strip()]
                    if linhas_descricao_escapadas:
                        tg_list.append("\n".join(linhas_descricao_escapadas))
                if artigo['url']:
                    tg_list.append(f"[{escape_markdown_v2('🔗 Ver notícia completa')}]({artigo['url']})") 
                tg_list.append("") 
        tg_list.append(escape_markdown_v2("--------------------"))
    
    # --- Fake News ---
    tg_list.append(f"*{escape_markdown_v2('🛑 Fake News Desmentida')}*")
    boato_data = jornal_data['fake_news']
    if isinstance(boato_data, dict): 
        tg_list.append(f"*{escape_markdown_v2(boato_data['title'])}*")
        tg_list.append(f"[{escape_markdown_v2('🔗 Leia mais')}]({boato_data['link']})")
    else: 
        tg_list.append(escape_markdown_v2(boato_data))
    tg_list.append(f"_{escape_markdown_v2('Fonte: Boatos.org (Feed RSS)')}_")
    tg_list.append(escape_markdown_v2("--------------------"))

    # --- Agradecimento ---
    tg_list.append(f"*{escape_markdown_v2('🙏 Apoie o Juninho News!')}*")
    tg_list.append(escape_markdown_v2("Se gostou do conteúdo e quer apoiar nosso trabalho, qualquer contribuição via Pix é muito bem-vinda! 💙"))
    tg_list.append(f"*{escape_markdown_v2('Chave Pix:')}* `{escape_markdown_v2('64992115946')}`")
    tg_list.append(escape_markdown_v2("Seu apoio nos ajuda a continuar trazendo informações com qualidade e dedicação. Obrigado! 😊"))
    
    return "\n".join(tg_list)

def send_telegram_message(bot_token: str, chat_id: str, message_text: str):
    """Envia uma mensagem para um chat do Telegram usando a API do Bot."""
    if not bot_token or not chat_id:
        logging.error("Token do Bot ou Chat ID do Telegram não fornecidos.")
        return False
        
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    max_length = 4096 
    messages_to_send = []

    if len(message_text) > max_length:
        logging.warning(f"Mensagem ({len(message_text)} caracteres) excede o limite de {max_length}. Será dividida.")
        current_part = ""
        for line in message_text.splitlines(keepends=True): # Mantém newlines para a divisão
            if len(current_part) + len(line) <= max_length:
                current_part += line
            else:
                if current_part: 
                    messages_to_send.append(current_part)
                current_part = line
        if current_part: 
            messages_to_send.append(current_part)
        
        if not messages_to_send and message_text: 
             messages_to_send.append(message_text[:max_length - 20] + "\n\\.\\.\\.\\[continua\\]")
    else:
        messages_to_send.append(message_text)

    all_sent_successfully = True
    for i, part_message in enumerate(messages_to_send):
        if not part_message.strip(): continue

        payload = {
            'chat_id': chat_id,
            'text': part_message,
            'parse_mode': 'MarkdownV2',
            'disable_web_page_preview': False 
        }
        try:
            response = requests.post(send_url, data=payload, timeout=30)
            response_json = {}
            try:
                response_json = response.json()
            except json.JSONDecodeError: # Se a resposta não for JSON válido
                logging.error(f"Resposta do Telegram não é JSON válido. Status: {response.status_code}, Resposta: {response.text[:200]}")
            
            if response.status_code == 200 and response_json.get("ok"):
                logging.info(f"Parte {i+1}/{len(messages_to_send)} enviada com sucesso para o Telegram (Chat ID: {chat_id}).")
            else:
                logging.error(f"Falha ao enviar parte {i+1} para o Telegram. Status: {response.status_code}, Resposta: {response.text}")
                all_sent_successfully = False
            time.sleep(1.5) 
        except requests.exceptions.RequestException as e:
            logging.exception(f"Exceção ao enviar parte {i+1} para o Telegram: {e}")
            all_sent_successfully = False
    return all_sent_successfully

# --- Função Principal Adaptada para Automação ---
def main_automated():
    """Função principal para coletar dados e enviar para o Telegram."""
    logging.info("Iniciando execução do Juninho News Automatizado.")
    
    if not all([NEWS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logging.critical("ERRO CRÍTICO: Variáveis de ambiente NEWS_API_KEY, TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não estão configuradas!")
        return

    current_time_obj = datetime.now(FUSO_BRASIL)
    
    eth_val = get_crypto_price('ethereum', 'Ethereum')
    btc_val = get_crypto_price('bitcoin', 'Bitcoin')

    jornal_data = {
        'data_display': current_time_obj.strftime('%d/%m/%Y'),
        'fase_lua': fase_da_lua(current_time_obj.strftime('%Y/%m/%d')),
        'frase_dia': get_quote_pensador(),
        'versiculo_dia': get_biblical_verse(),
        'datas_comemorativas': obter_datas_comemorativas(FILE_PATH_DATAS_COMEMORATIVAS),
        'cotacoes': {
            'dolar': get_exchange_rate_api("USD", "BRL", EXCHANGE_RATE_API_KEY),
            'euro': get_exchange_rate_api("EUR", "BRL", EXCHANGE_RATE_API_KEY),
            'eth_str_tg': f"R$ {eth_val:,.2f}" if eth_val is not None else "Erro/Indisponível",
            'btc_str_tg': f"R$ {btc_val:,.2f}" if btc_val is not None else "Erro/Indisponível",
        },
        'noticias': {},
        'fake_news': get_boatos_org_feed()
    }

    news_sections_queries = {
        "🇧🇷 Brasil (Geral)": "Brasil",
        "🏴 Goiás": f"Goiás OR \"Estado de Goiás\" NOT \"Goiás Esporte Clube\"",
        "🌍 Geopolítica": "Geopolítica OR \"Relações Internacionais\"",
        "🌐 Internacional": "Internacional OR Mundial NOT Brasil",
        "⚽ Futebol": "Futebol Brasil OR \"Campeonato Brasileiro\" OR Libertadores OR \"Copa do Brasil\"",
        "💰 Economia": "\"Economia Brasileira\" OR Inflação OR Selic OR IBGE OR BCB",
        "🍀 Loterias": "\"Loterias Caixa\" OR Mega-Sena OR Quina OR Lotofácil",
        "🌟 Fama & Entretenimento": "Celebridades OR Entretenimento OR Famosos Brasil",
        "✈️ Turismo": "Turismo Brasil OR Viagens OR \"Pontos Turísticos\"",
        "🏆 Outros Esportes": "Esportes Brasil -futebol NOT \"e-sports\"",
        "💻 Tecnologia": "Tecnologia OR Inovação OR Inteligência Artificial OR Startups Brasil"
    }

    for titulo_secao, query in news_sections_queries.items():
        artigos, msg_erro = buscar_noticias_newsapi(query, max_articles=5)
        if msg_erro and not artigos:
             jornal_data['noticias'][titulo_secao] = msg_erro
        elif not artigos and not msg_erro: # Se não houve erro mas não encontrou artigos
             jornal_data['noticias'][titulo_secao] = f"Nenhuma notícia relevante para '{query}' no momento."
        else:
            jornal_data['noticias'][titulo_secao] = artigos

    telegram_message_text = formatar_para_telegram(jornal_data)
    
    if not send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, telegram_message_text):
        logging.error("Falha CRÍTICA ao enviar a mensagem completa para o Telegram.")
        # Para depuração, se rodar localmente, pode imprimir a mensagem
        # print("\n--- MENSAGEM PARA TELEGRAM (FALHA NO ENVIO AUTOMÁTICO) ---\n")
        # print(telegram_message_text)
    else:
        logging.info("Juninho News enviado com sucesso para o Telegram!")
        # print("Juninho News enviado com sucesso para o Telegram!") # Útil para logs no console

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    main_automated()
