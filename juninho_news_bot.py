import html
import logging
import os
import random
import time
import json # Para logs mais detalhados da API do Telegram
from datetime import datetime, timedelta

import ephem
import pandas as pd
import pytz
import requests
from bs4 import BeautifulSoup
# from unidecode import unidecode # Descomente se for usar para normalizar texto em queries

# --- Configuração básica de logging ---
# Em um ambiente de servidor, você pode querer logar para um arquivo:
# logging.basicConfig(filename='juninho_news.log', level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')
# Por enquanto, logando para o console:
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

# --- Carregar Segredos das Variáveis de Ambiente ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
EXCHANGE_RATE_API_KEY = os.getenv('EXCHANGE_RATE_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

USER_AGENT = "JuninhoNewsBot/1.0 (Automated Script)"
FUSO_BRASIL = pytz.timezone('America/Sao_Paulo')
FILE_PATH_DATAS_COMEMORATIVAS = "datas comemorativas.xlsx" # Assume que está no mesmo diretório

# --- Funções Utilitárias e de Busca (Adaptadas do Colab) ---

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
    """Calcula a fase da lua para uma data (formato YYYY/MM/DD)."""
    try:
        data_ephem = ephem.Date(data_str_ephem_format)
        lua = ephem.Moon(data_ephem)
        fase_percentual = lua.phase

        pnm = ephem.previous_new_moon(data_ephem)
        nfm = ephem.next_full_moon(data_ephem) # Próxima lua cheia a partir da data atual

        # Lógica simplificada baseada na iluminação (0-100 para ephem.Moon().phase)
        # As fases são aproximadas.
        if fase_percentual < 3: return "Lua Nova 🌑"
        elif fase_percentual < 23:
             # Verifica se estamos mais perto do quarto crescente
             nfqm = ephem.next_first_quarter_moon(pnm) # Próximo quarto crescente após a última nova
             if data_ephem < nfqm:
                 return "Lua Crescente Côncava 🌒"
             else: # Estamos no ou após o quarto crescente, mas antes de ficar muito gibosa
                 return "Quarto Crescente 🌓" 
        elif fase_percentual < 48: return "Lua Crescente Gibosa 🌔"
        elif fase_percentual < 52: return "Lua Cheia 🌕"
        elif fase_percentual < 73: return "Lua Minguante Gibosa 🌖"
        elif fase_percentual < 97:
             # Verifica se estamos mais perto do quarto minguante
             nlqm = ephem.next_last_quarter_moon(nfm) # Próximo quarto minguante após a última cheia
             if data_ephem < nlqm:
                 return "Quarto Minguante 🌗"
             else: # Estamos no ou após o quarto minguante
                 return "Lua Minguante Côncava 🌘"
        else: return "Lua Nova (final) 🌑"
    except Exception as e:
        logging.exception(f"Erro ao calcular fase da lua para '{data_str_ephem_format}': {e}")
        return "Fase da lua indisponível"

def obter_datas_comemorativas(file_path: str, sheet_name='tabela') -> str:
    """Lê datas comemorativas de um arquivo Excel para a data atual."""
    try:
        if not os.path.exists(file_path):
            logging.warning(f"Arquivo de datas comemorativas não encontrado: {file_path}")
            return "⚠️ Arquivo de datas comemorativas não encontrado."
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        # Assegura que a primeira coluna seja usada para data e a segunda para descrição
        df.columns = ['DataRaw', 'DescricaoRaw'] + list(df.columns[2:]) 
        df['Data'] = pd.to_datetime(df['DataRaw'], errors='coerce')
        df['Descricao'] = df['DescricaoRaw'].astype(str).str.strip()
        
        data_atual_obj = datetime.now(FUSO_BRASIL).date()
        datas_hoje = df[df['Data'].dt.date == data_atual_obj]
        
        if not datas_hoje.empty:
            # Para Telegram, usar \- para itens de lista se a linha começar com * ou -
            return "\n".join(f"\\- {escape_markdown_v2(row['Descricao'])}" for _, row in datas_hoje.iterrows())
        return f"Nenhuma data comemorativa listada para hoje ({data_atual_obj.strftime('%d/%m')})."
    except Exception as e:
        logging.exception(f"Erro ao ler/processar datas comemorativas '{file_path}': {e}")
        return "⚠️ Erro ao carregar datas comemorativas."

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
                autor_tag = frase_escolhida.find_next_sibling("p")
                autor = None
                if autor_tag and autor_tag.find('a'):
                     autor = autor_tag.find('a').text.strip()
                elif frase_escolhida.find_parent().find("span", class_="autor") :
                     autor = frase_escolhida.find_parent().find("span", class_="autor").text.strip()
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
                titulo = boato.find("title").text.strip()
                link = boato.find("link").text.strip()
                logging.info("Boato desmentido obtido do Boatos.org.")
                return {"title": titulo, "link": link}
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
            if not titulo or titulo == "[Removed]" or titulo in titulos_exibidos:
                continue
            titulos_exibidos.add(titulo)
            descricao = artigo_api.get('description')
            if descricao and len(descricao) > 200: # Limite um pouco maior para Telegram
                descricao = descricao[:197].strip() + "..."
            
            articles_data.append({
                "title": titulo,
                "source": artigo_api.get('source', {}).get('name', 'N/A'),
                "description": descricao,
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

    tg_list.append(f"*{escape_markdown_v2(f'📰 Juninho News - {jornal_data["data_display"]}')}*")
    tg_list.append(f"_{escape_markdown_v2(f'📌 De Pires do Rio-GO')}_")
    tg_list.append(f"_{escape_markdown_v2(f'🌒 Fase da Lua: {jornal_data["fase_lua"]}')}_")
    tg_list.append(escape_markdown_v2("--------------------"))

    tg_list.append(f"*{escape_markdown_v2('💭 Frase de Hoje')}*")
    tg_list.append(f"_{escape_markdown_v2(jornal_data['frase_dia'])}_")
    tg_list.append(f"\n*{escape_markdown_v2('📖 Versículo do Dia')}*")
    tg_list.append(f"_{escape_markdown_v2(jornal_data['versiculo_dia'])}_")
    tg_list.append(f"_{escape_markdown_v2('Fonte: Bible Gateway (ARC)')}_")
    tg_list.append(escape_markdown_v2("--------------------"))

    tg_list.append(f"*{escape_markdown_v2(f'🗓️ Datas Comemorativas - {jornal_data["data_display"]}')}*")
    if jornal_data['datas_comemorativas'] and not jornal_data['datas_comemorativas'].startswith("Nenhuma") and not jornal_data['datas_comemorativas'].startswith("⚠️"):
        # A função obter_datas_comemorativas já prefixa com `\- ` e escapa o conteúdo
        tg_list.append(jornal_data['datas_comemorativas'])
    else:
        tg_list.append(escape_markdown_v2(jornal_data['datas_comemorativas']))
    tg_list.append(escape_markdown_v2("--------------------"))
    
    tg_list.append(f"*{escape_markdown_v2('💹 Cotações')}*")
    tg_list.append(f"◦ *Dólar \\(USD\\):* R\\$ {escape_markdown_v2(jornal_data['cotacoes']['dolar'])}")
    tg_list.append(f"◦ *Euro \\(EUR\\):* R\\$ {escape_markdown_v2(jornal_data['cotacoes']['euro'])}")
    tg_list.append(f"◦ *Ethereum \\(ETH\\):* {jornal_data['cotacoes']['eth_str_tg']}") # Já inclui R$ e é escapado
    tg_list.append(f"◦ *Bitcoin \\(BTC\\):* {jornal_data['cotacoes']['btc_str_tg']}")   # Já inclui R$ e é escapado
    tg_list.append(f"_{escape_markdown_v2('Cripto: Dados por CoinGecko')}_")
    tg_list.append(escape_markdown_v2("--------------------"))

    for secao_titulo, artigos_ou_msg in jornal_data['noticias'].items():
        tg_list.append(f"*{escape_markdown_v2(secao_titulo)}*")
        if isinstance(artigos_ou_msg, str):
            tg_list.append(escape_markdown_v2(artigos_ou_msg))
        else:
            for artigo in artigos_ou_msg:
                titulo_escaped = escape_markdown_v2(artigo['title'])
                fonte_escaped = escape_markdown_v2(artigo['source'])
                tg_list.append(f"📰 *{titulo_escaped}*")
                tg_list.append(f"_{escape_markdown_v2('Fonte:')} {fonte_escaped}_")
                if artigo['description']:
                    # Usar blockquote para descrição, escapando o conteúdo interno
                    descricao_limpa = artigo['description'].replace('\r\n', '\n').replace('\r', '\n')
                    linhas_descricao = [f"> {escape_markdown_v2(linha)}" for linha in descricao_limpa.split('\n')]
                    tg_list.append("\n".join(linhas_descricao))
                if artigo['url']:
                    tg_list.append(f"[🔗 Ver notícia completa]({artigo['url']})") 
                tg_list.append("") 
        tg_list.append(escape_markdown_v2("--------------------"))
    
    tg_list.append(f"*{escape_markdown_v2('🛑 Fake News Desmentida')}*")
    boato_data = jornal_data['fake_news']
    if isinstance(boato_data, dict):
        tg_list.append(f"*{escape_markdown_v2(boato_data['title'])}*")
        tg_list.append(f"[🔗 Leia mais]({boato_data['link']})")
    else: # String de erro/aviso
        tg_list.append(escape_markdown_v2(boato_data))
    tg_list.append(f"_{escape_markdown_v2('Fonte: Boatos.org (Feed RSS)')}_")
    tg_list.append(escape_markdown_v2("--------------------"))

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
        # Tenta dividir por blocos delimitados por "--------------------" ou por linhas se muito grande
        # Esta lógica de divisão pode ser aprimorada
        for line in message_text.splitlines(keepends=True):
            if len(current_part) + len(line) <= max_length:
                current_part += line
            else:
                if current_part:
                    messages_to_send.append(current_part)
                current_part = line
        if current_part:
            messages_to_send.append(current_part)
        
        if not messages_to_send and message_text: # Se a primeira parte já é muito longa
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
            'disable_web_page_preview': False # Habilita preview de links para notícias
        }
        try:
            response = requests.post(send_url, data=payload, timeout=30) # Timeout aumentado
            response_json = response.json() 
            if response.status_code == 200 and response_json.get("ok"):
                logging.info(f"Parte {i+1}/{len(messages_to_send)} enviada com sucesso para o Telegram (Chat ID: {chat_id}).")
            else:
                logging.error(f"Falha ao enviar parte {i+1} para o Telegram. Status: {response.status_code}, Resposta: {response.text}")
                all_sent_successfully = False
            time.sleep(1.5) # Pausa maior entre o envio de múltiplas partes para evitar rate limit
        except requests.exceptions.RequestException as e:
            logging.exception(f"Exceção ao enviar parte {i+1} para o Telegram: {e}")
            all_sent_successfully = False
        except json.JSONDecodeError as e:
            response_text_snippet = response.text[:200] if 'response' in locals() and hasattr(response, 'text') else "N/A"
            status_code_snippet = response.status_code if 'response' in locals() and hasattr(response, 'status_code') else "N/A"
            logging.error(f"Erro ao decodificar JSON da resposta do Telegram para parte {i+1}. Status: {status_code_snippet}, Resposta: {response_text_snippet}, Erro: {e}")
            all_sent_successfully = False
    return all_sent_successfully

# --- Função Principal Adaptada para Automação ---
def main_automated():
    """Função principal para coletar dados e enviar para o Telegram."""
    logging.info("Iniciando execução do Juninho News Automatizado.")
    
    if not all([NEWS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
        logging.critical("ERRO CRÍTICO: Variáveis de ambiente NEWS_API_KEY, TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID não estão configuradas!")
        # Em um ambiente de servidor, não adianta imprimir para o console, mas o log é importante.
        # Se precisar de uma notificação de falha, poderia enviar um email de erro ou uma mensagem para um chat de admin no Telegram.
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
        'fake_news': get_boatos_org_feed() # Retorna dict ou string de erro
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
        elif not artigos and not msg_erro:
             jornal_data['noticias'][titulo_secao] = f"Nenhuma notícia relevante para '{query}' no momento."
        else:
            jornal_data['noticias'][titulo_secao] = artigos

    telegram_message_text = formatar_para_telegram(jornal_data)
    
    if not send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, telegram_message_text):
        logging.error("Falha CRÍTICA ao enviar a mensagem completa para o Telegram.")
        # Em um servidor, você pode querer ter um fallback, como enviar um email de alerta.
    else:
        logging.info("Juninho News enviado com sucesso para o Telegram!")

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    main_automated()
