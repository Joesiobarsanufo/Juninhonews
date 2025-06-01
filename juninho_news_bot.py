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
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(funcName)s] - %(message)s')

# --- Carregar Segredos das Variáveis de Ambiente ---
NEWS_API_KEY = os.getenv('NEWS_API_KEY')
EXCHANGE_RATE_API_KEY = os.getenv('EXCHANGE_RATE_API_KEY')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

USER_AGENT = "JuninhoNewsBot/1.5 (Automated Script)" # Versão incrementada
FUSO_BRASIL = pytz.timezone('America/Sao_Paulo')
FILE_PATH_DATAS_COMEMORATIVAS = "datas comemorativas.xlsx"

# --- Funções Utilitárias e de Busca (mantidas e ajustadas) ---

def safe_request_get(url, params=None, timeout=10, max_retries=2, delay_seconds=2):
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
    try:
        date_observer = ephem.Date(data_str_ephem_format)
        moon = ephem.Moon(date_observer)
        illumination = moon.phase
        
        prev_date = ephem.Date(date_observer - 1)
        moon_prev = ephem.Moon(prev_date)
        is_waxing_approx = illumination > moon_prev.phase

        if illumination < 3: return "Lua Nova 🌑"
        if illumination > 97: return "Lua Nova (final) 🌑" 
        if illumination >= 48 and illumination <= 52: return "Lua Cheia 🌕" # Faixa mais precisa
        
        # Para quartos, um pouco mais de precisão usando eventos do ephem
        pnm = ephem.previous_new_moon(date_observer)
        nfqm = ephem.next_first_quarter_moon(pnm)
        nfm = ephem.next_full_moon(date_observer) # Próxima cheia a partir da data atual, para referência de minguante
        plqm = ephem.previous_last_quarter_moon(date_observer) # Último quarto minguante antes da data

        # Verifica se está próximo do Quarto Crescente
        if abs(date_observer - nfqm) < 1.5 : return "Quarto Crescente 🌓" # Tolerância de 1.5 dias
        # Verifica se está próximo do Quarto Minguante
        # Precisamos do *próximo* quarto minguante após a última cheia, ou *anterior* mais próximo
        # Se a data atual está entre a última cheia e a próxima nova, e perto do evento do quarto minguante
        pfm = ephem.previous_full_moon(date_observer)
        nlqm_after_pfm = ephem.next_last_quarter_moon(pfm)
        if abs(date_observer-nlqm_after_pfm) < 1.5 : return "Quarto Minguante 🌗"


        if is_waxing_approx: # Se está crescendo
            if illumination < 23: return "Lua Crescente Côncava 🌒"
            if illumination < 48: return "Lua Crescente Gibosa 🌔"
        else: # Se está minguando
            if illumination > 77: return "Lua Minguante Côncava 🌘"
            if illumination > 52: return "Lua Minguante Gibosa 🌖"
        
        logging.warning(f"Fase da lua com iluminação {illumination}% não encaixou precisamente, usando fallback com base na direção.")
        return "Fase Crescente (aprox.) 🌔" if is_waxing_approx else "Fase Minguante (aprox.) 🌖"

    except Exception as e:
        logging.exception(f"Erro ao calcular fase da lua para '{data_str_ephem_format}': {e}")
        return "Fase da lua indisponível"


def obter_datas_comemorativas(file_path: str, sheet_name='tabela') -> str:
    try:
        if not os.path.exists(file_path):
            return "⚠️ Arquivo de datas comemorativas não encontrado." # Não precisa escapar para plain text
        df = pd.read_excel(file_path, sheet_name=sheet_name)
        if df.empty or len(df.columns) < 2:
            return "⚠️ Arquivo de datas vazio ou mal formatado."
        df.columns = ['DataRaw', 'DescricaoRaw'] + list(df.columns[2:])
        df['Data'] = pd.to_datetime(df['DataRaw'], errors='coerce')
        df['Descricao'] = df['DescricaoRaw'].astype(str).str.strip()
        data_atual_obj = datetime.now(FUSO_BRASIL).date()
        datas_hoje = df[df['Data'].dt.date == data_atual_obj]
        if not datas_hoje.empty:
            # Formato plain text para lista
            return "\n".join(f"- {row['Descricao']}" for _, row in datas_hoje.iterrows())
        return f"Nenhuma data comemorativa listada para hoje ({data_atual_obj.strftime('%d/%m')})."
    except Exception as e:
        logging.exception(f"Erro ao ler/processar datas comemorativas '{file_path}': {e}")
        return "⚠️ Erro ao carregar datas comemorativas."

def get_crypto_price(coin_id: str, coin_name: str) -> float | None:
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin_id}&vs_currencies=brl"
    response = safe_request_get(url)
    if response:
        try:
            data = response.json()
            price = data.get(coin_id, {}).get("brl")
            if price is not None: return float(price)
            logging.warning(f"Preço para {coin_name} não encontrado na API CoinGecko: {data}")
        except (ValueError, TypeError, AttributeError, requests.exceptions.JSONDecodeError) as e:
            logging.exception(f"Erro ao processar/decodificar dados de {coin_name} da CoinGecko: {e}")
    return None

def get_biblical_verse() -> str:
    url = "https://www.biblegateway.com/votd/get/?format=xml&version=ARC"
    response = safe_request_get(url)
    if response:
        try:
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'xml') # Requer lxml
            verse_text_tag, reference_tag = soup.find("text"), soup.find("reference")
            if verse_text_tag and reference_tag:
                return f"{html.unescape(verse_text_tag.text.strip())} ({html.unescape(reference_tag.text.strip())})" # Plain text
            return "Não foi possível obter o versículo (formato inesperado)."
        except Exception as e: logging.exception(f"Erro ao processar XML da Bible Gateway: {e}")
    return "Não foi possível obter o versículo (falha na requisição)."

def get_quote_pensador() -> str:
    url = "https://www.pensador.com/frases_de_pensadores_famosos/"
    response = safe_request_get(url)
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
                return f'"{texto_frase}"{f" - {autor}" if autor else ""}' # Plain text
            return "⚠️ Nenhuma frase encontrada (layout pode ter mudado)."
        except Exception as e: logging.exception(f"Erro ao processar HTML do Pensador.com: {e}")
    return "❌ Erro ao buscar frase no Pensador.com."

def get_boatos_org_feed() -> dict | str :
    url = "https://www.boatos.org/feed"
    response = safe_request_get(url)
    if response:
        try:
            soup = BeautifulSoup(response.content, 'xml') # Requer lxml
            items = soup.find_all("item")
            if items:
                boato = random.choice(items)
                titulo_tag, link_tag = boato.find("title"), boato.find("link")
                if titulo_tag and link_tag:
                    return {"title": titulo_tag.text.strip(), "link": link_tag.text.strip()}
                return "⚠️ Formato inesperado no item do feed Boatos.org."
            return "⚠️ Nenhuma fake news desmentida encontrada no feed."
        except Exception as e:
            logging.exception(f"Erro ao processar feed RSS do Boatos.org: {e}")
            if "Couldn't find a tree builder" in str(e):
                return "❌ Erro: Parser XML (lxml) não encontrado. Instale 'lxml'."
    return "❌ Erro ao buscar fake news do Boatos.org."

def get_exchange_rate_api(base_currency: str, target_currency: str, api_key: str | None) -> str:
    if api_key:
        url = f"https://v6.exchangerate-api.com/v6/{api_key}/latest/{base_currency}"
        response = safe_request_get(url)
        if response:
            try:
                data = response.json()
                if data.get("result") == "success":
                    rate = data.get("conversion_rates", {}).get(target_currency)
                    if rate: return f"{rate:,.2f}" # Formatado com vírgula e ponto decimal
                    return f"Erro API ({target_currency}?)"
                return "Erro API Cotação"
            except (requests.exceptions.JSONDecodeError, Exception) as e:
                logging.exception(f"Erro com ExchangeRate-API: {e}")
                return "Erro API (Proc.)"
        return "Falha Conexão API Cotação"
    return "Indisponível (API ñ/config.)"

def buscar_noticias_newsapi(query_term: str, max_articles: int = 5) -> tuple[list[dict], str | None]:
    if not NEWS_API_KEY: return [], "⚠️ Chave de API (NewsAPI) não configurada."
    url = "https://newsapi.org/v2/everything"
    parametros = {'q': query_term, 'language': 'pt', 'sortBy': 'publishedAt', 'pageSize': max_articles + 10, 'apiKey': NEWS_API_KEY}
    response = safe_request_get(url, params=parametros)
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
            if len(desc) > 150: desc = desc[:147].strip() + "..." # Descrição mais curta para plain text
            articles_data.append({"title": titulo, "source": art_api.get('source', {}).get('name', 'N/A'), "description": desc, "url": art_api.get('url')})
            if len(articles_data) >= max_articles: break
        if not articles_data: return [], f"Nenhuma notícia relevante para '{query_term}' (pós-filtros)."
        return articles_data, None
    elif dados.get('status') == 'error':
        msg = f"⚠️ Erro NewsAPI ({dados.get('code', 'err')}): {dados.get('message', '')}"
        return [], msg
    return [], f"Nenhuma notícia sobre '{query_term}'."

# --- Funções do Telegram (escape_markdown_v2 ainda é útil para conteúdo) ---

def escape_markdown_v2(text: str | None) -> str:
    # Mesmo para um output "plain text", escapar alguns caracteres que o Telegram
    # pode tentar interpretar (especialmente se parse_mode ainda for MarkdownV2) é mais seguro.
    # Se parse_mode for omitido, menos escape é necessário, mas URLs podem não ser clicáveis.
    # Por segurança, mantemos o escape para o conteúdo.
    if text is None: text = ""
    if not isinstance(text, str): text = str(text)
    # Caracteres problemáticos para MarkdownV2 do Telegram
    escape_chars = r'_*[]()~`>#+-=|{}.!' 
    return "".join(f'\\{char}' if char in escape_chars else char for char in text)

def formatar_para_telegram_plain(jornal_data: dict) -> str:
    """Formata os dados do jornal para um estilo plain text, similar ao original."""
    plain_list = []
    
    # Cabeçalho (Conforme exemplo do usuário)
    plain_list.append(f"📰 Juninho News - {jornal_data['data_display']}")
    plain_list.append(f"📌 De Pires do Rio-GO")
    plain_list.append(f"🌒 {jornal_data['fase_lua']}") # Já vem com emoji
    plain_list.append("") # Linha em branco

    # Frase e Versículo
    plain_list.append(f"💭 Frase de Hoje")
    plain_list.append(jornal_data['frase_dia']) # Conteúdo já é string
    plain_list.append("")
    plain_list.append(f"📖 Versículo do Dia")
    plain_list.append(jornal_data['versiculo_dia']) # Conteúdo já é string
    # Nota: Fonte do versículo pode ser adicionada se desejado: ("Fonte: Bible Gateway (ARC)")
    plain_list.append("")

    # Agradecimento (movido para mais perto do topo, como no exemplo)
    plain_list.append(f"🙏 Agradecemos por acompanhar nosso jornal") # Sem escape para emojis e texto literal
    plain_list.append(f"!Se gostou do conteúdo e quer apoiar nosso trabalho, qualquer contribuição via Pix é muito bem-vinda! 💙")
    plain_list.append(f"📌 Chave Pix: 64992115946")
    plain_list.append(f"Seu apoio nos ajuda a continuar trazendo informações com qualidade e dedicação. Obrigado! 😊")
    plain_list.append("")

    # Datas Comemorativas
    plain_list.append(f"🗓 HOJE É DIA... {jornal_data['data_display']}:")
    # obter_datas_comemorativas agora retorna formato "- Descrição"
    plain_list.append(jornal_data['datas_comemorativas']) 
    plain_list.append("")

    # Cotações
    # Usar R$ diretamente. A formatação : ,.2f já lida com pontos e vírgulas.
    plain_list.append(f" 💵 Cotação do Dólar") # Adiciona espaço no início como no exemplo
    plain_list.append(f" R$ {jornal_data['cotacoes']['dolar']}")
    plain_list.append("")
    plain_list.append(f"💶 Cotação do Euro")
    plain_list.append(f" R$ {jornal_data['cotacoes']['euro']}")
    plain_list.append("")
    plain_list.append(f"🪙 Cotação do Ethereum")
    plain_list.append(f" R${jornal_data['cotacoes']['eth_plain_str']}") # Plain string, sem escape
    plain_list.append("")
    plain_list.append(f"🪙 Cotação do Bitcoin")
    plain_list.append(f" R$ {jornal_data['cotacoes']['btc_plain_str']}") # Plain string, sem escape
    plain_list.append("")
    # Atribuição CoinGecko pode ser omitida para plain text ou adicionada
    # plain_list.append("Cripto: Dados por CoinGecko")


    # Notícias
    for secao_titulo_com_emoji, artigos_ou_msg in jornal_data['noticias'].items():
        plain_list.append(f"{secao_titulo_com_emoji}  ") # Título da seção com emojis
        
        # Subtítulo "📢 Últimas notícias..."
        # Tenta extrair o nome da seção sem emojis para o subtítulo
        nome_secao_limpo = secao_titulo_com_emoji
        for emoji in "🇧🇷🏴󠁢󠁲󠁧󠁯󠁿🌍🌐⚽💰🍀🌟🛳✈️🏆💻": nome_secao_limpo = nome_secao_limpo.replace(emoji, "")
        nome_secao_limpo = nome_secao_limpo.replace("(", "").replace(")", "").replace("&", "e").strip()
        if "Geopolitica" in nome_secao_limpo:
            plain_list.append(f"📢 Últimas notícias da {nome_secao_limpo} mundial:\n")
        elif "INTERNACIONAL" in secao_titulo_com_emoji: # Checa o original para caso especial
             plain_list.append(f"🌐 Últimas notícias internacionais e do mundo:\n")
        else:
            plain_list.append(f"📢 Últimas notícias de {nome_secao_limpo}:\n")
            
        if isinstance(artigos_ou_msg, str): # Mensagem de erro/aviso
            plain_list.append(artigos_ou_msg)
        else: # Lista de artigos
            for artigo in artigos_ou_msg:
                plain_list.append(f"📰 {artigo['title']}") # Título sem formatação especial
                plain_list.append(f"🏷 Fonte: {artigo['source']}")
                if artigo['description']:
                    desc_limpa = artigo['description'].replace('\r\n', '\n').replace('\r', '\n')
                    plain_list.append(f"📝 {desc_limpa}")
                if artigo['url']:
                    plain_list.append(f"🔗 {artigo['url']}") # URL plain, Telegram auto-linka
                plain_list.append("") # Linha em branco entre artigos
        plain_list.append("") # Linha em branco após a seção

    # Fake News
    plain_list.append(f"🔎 #FAKENEWS ") # Com espaço como no original
    boato_data = jornal_data['fake_news']
    if isinstance(boato_data, dict):
        plain_list.append(f"🛑 Fake News desmentida:") # Mantendo o estilo
        plain_list.append(f"📢 {boato_data['title']}")
        plain_list.append(f"🔗 {boato_data['link']}")
    else: 
        plain_list.append(boato_data) # String de erro/aviso
    plain_list.append("")
    # Fonte do Boatos.org pode ser omitida ou adicionada:
    # plain_list.append("Fonte: Boatos.org (Feed RSS)")
    
    # Agradecimento final (já foi movido para o início, conforme exemplo)
    
    return "\n".join(plain_list)


def send_telegram_message(bot_token: str, chat_id: str, message_text: str):
    if not bot_token or not chat_id:
        logging.error("Token do Bot ou Chat ID do Telegram não fornecidos.")
        return False
    send_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    max_length, messages_to_send = 4096, []
    
    if len(message_text) > max_length:
        logging.warning(f"Mensagem ({len(message_text)} caracteres) excede limite. Será dividida.")
        current_part = ""
        separator = "\n\n\n" # Tenta dividir por seções (blocos de texto separados por 2 newlines)
        # A lógica de divisão pode ser melhorada para respeitar seções
        
        # Divisão simples por linhas, respeitando o limite
        temp_parts = []
        for line in message_text.splitlines(keepends=True):
            if len(current_part) + len(line) <= max_length:
                current_part += line
            else:
                if current_part: temp_parts.append(current_part)
                current_part = line
        if current_part: temp_parts.append(current_part)
        
        for part in temp_parts:
            if len(part) > max_length: # Se uma parte ainda for muito grande (ex: seção de notícias longa)
                # Trunca a sub-parte
                messages_to_send.append(part[:max_length - 30] + "\n...[mensagem cortada]...")
            else:
                messages_to_send.append(part)

        if not messages_to_send and message_text: 
             messages_to_send.append(message_text[:max_length - 30] + "\n...[mensagem cortada]...")
    else:
        messages_to_send.append(message_text)

    all_sent_successfully = True
    for i, part_message in enumerate(messages_to_send):
        if not part_message.strip(): continue
        # Para texto "plain", omitir parse_mode ou usar HTML se quiser links explícitos,
        # mas o Telegram geralmente auto-linka URLs.
        # Se usar MarkdownV2, o texto *DEVE* ser escapado corretamente.
        # Como estamos mirando em "plain text" com emojis, não usaremos parse_mode explícito,
        # deixando o Telegram fazer a interpretação padrão (que inclui auto-link).
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
        'data_display': current_time_obj.strftime('%d/%m/%Y'),
        'fase_lua': fase_da_lua(current_time_obj.strftime('%Y/%m/%d')),
        'frase_dia': get_quote_pensador(),
        'versiculo_dia': get_biblical_verse(),
        'datas_comemorativas': obter_datas_comemorativas(FILE_PATH_DATAS_COMEMORATIVAS),
        'cotacoes': {
            'dolar': get_exchange_rate_api("USD", "BRL", EXCHANGE_RATE_API_KEY),
            'euro': get_exchange_rate_api("EUR", "BRL", EXCHANGE_RATE_API_KEY),
            # Strings para plain text, com formatação de moeda
            'eth_plain_str': f"{eth_val:,.2f}" if eth_val is not None else "Erro/Indisponível",
            'btc_plain_str': f"{btc_val:,.2f}" if btc_val is not None else "Erro/Indisponível",
        },
        'noticias': {},
        'fake_news': get_boatos_org_feed()
    }

    # Mantendo os títulos das seções com emojis como no seu exemplo original de saída
    news_sections_queries = {
        "🏴󠁢󠁲󠁧󠁯󠁿 Goiás 🏴󠁢󠁲󠁧󠁯󠁿": f"Goiás OR \"Estado de Goiás\" NOT \"Goiás Esporte Clube\"",
        "🌎 Geopolitica 🌍": "Geopolítica OR \"Relações Internacionais\"", 
        "🌎 INTERNACIONAL 🌍": "Internacional OR Mundial NOT Brasil",
        "⚽ Futebol ⚽": "Futebol Brasil OR \"Campeonato Brasileiro\" OR Libertadores OR \"Copa do Brasil\"",
        "🇧🇷 BRASIL GERAL 🇧🇷": "Brasil",
        "💰 ECONOMIA & NEGÓCIOS 💲": "\"Economia Brasileira\" OR Inflação OR Selic OR IBGE OR BCB",
        "🍀 LOTERIAS 🍀": "\"Loterias Caixa\" OR Mega-Sena OR Quina OR Lotofácil",
        "🌟 FAMA & ENTRETENIMENTO 🎭": "Celebridades OR Entretenimento OR Famosos Brasil",
        "🛳 TURISMO ✈️": "Turismo Brasil OR Viagens OR \"Pontos Turísticos\"",
        "🏆 ESPORTES 🏆": "Esportes Brasil -futebol NOT \"e-sports\"",
        "💻 Tecnologia 💻": "Tecnologia OR Inovação OR Inteligência Artificial OR Startups Brasil"
    }


    for titulo_secao_com_emoji, query in news_sections_queries.items():
        artigos, msg_erro = buscar_noticias_newsapi(query, max_articles=5)
        # Armazena diretamente o título com emoji como chave
        if msg_erro and not artigos: jornal_data['noticias'][titulo_secao_com_emoji] = msg_erro
        elif not artigos and not msg_erro: jornal_data['noticias'][titulo_secao_com_emoji] = f"Nenhuma notícia relevante para '{query}'."
        else: jornal_data['noticias'][titulo_secao_com_emoji] = artigos

    telegram_message_text = formatar_para_telegram_plain(jornal_data)
    
    if not send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, telegram_message_text):
        logging.error("Falha CRÍTICA ao enviar a mensagem completa para o Telegram.")
        # print("\n--- MENSAGEM PARA TELEGRAM (FALHA NO ENVIO AUTOMÁTICO) ---\n") # Para debug local
        # print(telegram_message_text)
    else:
        logging.info("Juninho News enviado com sucesso para o Telegram!")
        # print("Juninho News enviado com sucesso para o Telegram!") # Para debug local

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    main_automated()
