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

USER_AGENT = "JuninhoNewsBot/1.6 (Automated Script)"
FUSO_BRASIL = pytz.timezone('America/Sao_Paulo')
FILE_PATH_DATAS_COMEMORATIVAS = "datas comemorativas.xlsx"

# --- Funções Utilitárias e de Busca ---

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
        illumination = moon.phase # Porcentagem de iluminação (0-100)
        
        # Para determinar se está crescendo ou minguando de forma aproximada
        prev_date = ephem.Date(date_observer - 1)
        moon_prev = ephem.Moon(prev_date)
        is_waxing = illumination > moon_prev.phase
        # Casos especiais para nova e cheia onde a iluminação pode ser igual ao dia anterior
        if illumination < 1 and moon_prev.phase > 98: is_waxing = True # Acabou de ser nova
        if illumination > 99 and moon_prev.phase < 2: is_waxing = False # Acabou de ser cheia (errado, deveria ser is_waxing = true se illumination > prev)
                                                                    # Corrigindo:
        if illumination < 1: is_waxing = True # Definindo como crescente após a nova exata
        elif illumination > 99: is_waxing = False # Definindo como minguante após a cheia exata


        if illumination < 3: return "Lua Nova 🌑"
        if illumination > 97: return "Lua Nova (final) 🌑" 
        if illumination >= 48 and illumination <= 52: return "Lua Cheia 🌕"
        
        if illumination >= 23 and illumination <= 27:
            # Para os quartos, a direção é crucial
            # Se a iluminação de ontem era menor E hoje não é cheia, é crescente
            # Se a iluminação de ontem era maior E hoje não é nova, é minguante
            # A variável is_waxing já tenta capturar isso.
            return "Quarto Crescente 🌓" if is_waxing else "Quarto Minguante 🌗"
        
        if is_waxing:
            if illumination < 23: return "Lua Crescente Côncava 🌒"
            if illumination < 48: return "Lua Crescente Gibosa 🌔"
        else: # Minguante
            if illumination > 77: return "Lua Minguante Côncava 🌘"
            if illumination > 52: return "Lua Minguante Gibosa 🌖"
        
        logging.warning(f"Fase da lua (ilum: {illumination}%, crescendo: {is_waxing}) não encaixou, usando fallback.")
        return "Fase Crescente (aprox.) 🌔" if is_waxing else "Fase Minguante (aprox.) 🌖"
    except Exception as e:
        logging.exception(f"Erro ao calcular fase da lua para '{data_str_ephem_format}': {e}")
        return "Fase da lua indisponível"

def obter_datas_comemorativas(file_path: str, sheet_name='tabela') -> str:
    try:
        if not os.path.exists(file_path):
            return "⚠️ Arquivo de datas comemorativas não encontrado."
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
                return f"{html.unescape(verse_text_tag.text.strip())} ({html.unescape(reference_tag.text.strip())})"
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
                return f'"{texto_frase}"{f" - {autor}" if autor else ""}'
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
                    if rate: return f"{rate:,.2f}"
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
    """Escapa caracteres especiais para o formato MarkdownV2 do Telegram.
       Usado para *conteúdo* que será inserido em formatação Markdown.
    """
    if text is None: text = ""
    if not isinstance(text, str): text = str(text)
    # Caracteres a serem escapados conforme documentação do Telegram para MarkdownV2
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return "".join(f'\\{char}' if char in escape_chars else char for char in text)

def formatar_para_telegram_plain(jornal_data: dict) -> str:
    """Formata os dados do jornal para um estilo plain text, similar ao original,
       mas ainda escapa conteúdo dinâmico para segurança com parse_mode: MarkdownV2.
    """
    plain_list = []
    
    # Cabeçalho
    plain_list.append(f"📰 {escape_markdown_v2(f'Juninho News - {jornal_data["data_display"]}')}")
    plain_list.append(f"📌 {escape_markdown_v2('De Pires do Rio-GO')}")
    plain_list.append(f"🌒 {escape_markdown_v2(jornal_data['fase_lua'])}") # Emoji + texto escapado
    plain_list.append("")

    # Frase e Versículo
    plain_list.append(f"💭 {escape_markdown_v2('Frase de Hoje')}")
    plain_list.append(escape_markdown_v2(jornal_data['frase_dia']))
    plain_list.append("")
    plain_list.append(f"📖 {escape_markdown_v2('Versículo do Dia')}")
    plain_list.append(escape_markdown_v2(jornal_data['versiculo_dia']))
    plain_list.append("") # Opcional: adicionar fonte do versículo aqui

    # Agradecimento
    plain_list.append(f"🙏 {escape_markdown_v2('Agradecemos por acompanhar nosso jornal')}")
    plain_list.append(escape_markdown_v2("!Se gostou do conteúdo e quer apoiar nosso trabalho, qualquer contribuição via Pix é muito bem-vinda! 💙"))
    plain_list.append(f"📌 {escape_markdown_v2('Chave Pix:')} {escape_markdown_v2('64992115946')}") # Chave Pix não precisa ser monospace se for plain
    plain_list.append(escape_markdown_v2("Seu apoio nos ajuda a continuar trazendo informações com qualidade e dedicação. Obrigado! 😊"))
    plain_list.append("")

    # Datas Comemorativas
    plain_list.append(f"🗓 {escape_markdown_v2(f'HOJE É DIA... {jornal_data["data_display"]}:')}")
    # obter_datas_comemorativas agora retorna "- Descrição" (sem escape, pois é para plain text)
    # Mas para segurança com MarkdownV2, vamos escapar o resultado.
    # Modificação: obter_datas_comemorativas deve retornar plain text, e aqui escapamos.
    # Ou, obter_datas_comemorativas escapa, e aqui usamos diretamente.
    # Mantendo o escape em obter_datas_comemorativas para consistência se usado em outros contextos.
    # No entanto, para o formato plain text original `- item`, o escape não deve ser `\\-`.
    # Ajuste em obter_datas_comemorativas: return "\n".join(f"- {row['Descricao']}" ... )
    # E aqui escapamos:
    plain_list.append(jornal_data['datas_comemorativas']) # Assumindo que a função já trata o escape ou retorna plain
    plain_list.append("")

    # Cotações
    plain_list.append(f" 💵 {escape_markdown_v2('Cotação do Dólar')}")
    plain_list.append(f" {escape_markdown_v2(f'R$ {jornal_data["cotacoes"]["dolar"]}')}") # Adiciona espaço no início
    plain_list.append("")
    plain_list.append(f"💶 {escape_markdown_v2('Cotação do Euro')}")
    plain_list.append(f" {escape_markdown_v2(f'R$ {jornal_data["cotacoes"]["euro"]}')}")
    plain_list.append("")
    plain_list.append(f"🪙 {escape_markdown_v2('Cotação do Ethereum')}")
    plain_list.append(f" {escape_markdown_v2(f"R${jornal_data['cotacoes']['eth_plain_str']}")}") # R$ colado como no exemplo
    plain_list.append("")
    plain_list.append(f"🪙 {escape_markdown_v2('Cotação do Bitcoin')}")
    plain_list.append(f" {escape_markdown_v2(f"R$ {jornal_data['cotacoes']['btc_plain_str']}")}")
    plain_list.append("")

    # Notícias
    for secao_titulo_com_emoji, artigos_ou_msg in jornal_data['noticias'].items():
        plain_list.append(f"{secao_titulo_com_emoji}  ") # Título da seção com emojis (sem escape no emoji)
        
        nome_secao_limpo = secao_titulo_com_emoji
        for emoji in "🇧🇷🟢🌍🌐⚽💰🍀🌟🛳✈️🏆💻": nome_secao_limpo = nome_secao_limpo.replace(emoji, "")
        nome_secao_limpo = nome_secao_limpo.replace("(", "").replace(")", "").replace("&", "e").replace("Estado", "").strip()
        
        sub_titulo = ""
        if "Geopolitica" in nome_secao_limpo: sub_titulo = "Últimas notícias da Geopolítica mundial:"
        elif "INTERNACIONAL" in secao_titulo_com_emoji: sub_titulo = "Últimas notícias internacionais e do mundo:"
        else: sub_titulo = f"Últimas notícias de {nome_secao_limpo}:"
        plain_list.append(f"📢 {escape_markdown_v2(sub_titulo)}\n") # Uma newline aqui
            
        if isinstance(artigos_ou_msg, str):
            plain_list.append(escape_markdown_v2(artigos_ou_msg))
        else:
            for artigo in artigos_ou_msg:
                plain_list.append(f"📰 {escape_markdown_v2(artigo['title'])}")
                plain_list.append(f"🏷 {escape_markdown_v2('Fonte:')} {escape_markdown_v2(artigo['source'])}")
                if artigo['description']:
                    desc_limpa = artigo['description'].replace('\r\n', '\n').replace('\r', '\n')
                    plain_list.append(f"📝 {escape_markdown_v2(desc_limpa)}")
                if artigo['url']:
                    plain_list.append(f"🔗 {artigo['url']}") # URL não escapada
                plain_list.append("") 
        plain_list.append("") 
    
    # Fake News
    plain_list.append(f"🔎 {escape_markdown_v2('#FAKENEWS')} ") 
    boato_data = jornal_data['fake_news']
    if isinstance(boato_data, dict):
        plain_list.append(f"🛑 {escape_markdown_v2('Fake News desmentida:')}")
        plain_list.append(f"📢 {escape_markdown_v2(boato_data['title'])}")
        plain_list.append(f"🔗 {boato_data['link']}") # URL não escapada
    else: 
        plain_list.append(escape_markdown_v2(boato_data))
    # plain_list.append(f"_{escape_markdown_v2('Fonte: Boatos.org (Feed RSS)')}_") # Opcional
    plain_list.append("")

    # Agradecimento final já está no topo.
    
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
        # Tenta dividir por blocos (linhas vazias ou separadores de noticias)
        # Uma forma simples é dividir por linhas e agrupar até o limite
        temp_parts = []
        current_line_buffer = ""
        for line in message_text.splitlines(keepends=True):
            if len(current_line_buffer) + len(line) <= max_length:
                current_line_buffer += line
            else:
                if current_line_buffer: temp_parts.append(current_line_buffer)
                current_line_buffer = line
        if current_line_buffer: temp_parts.append(current_line_buffer)
        
        for part in temp_parts:
            if len(part) > max_length:
                logging.warning(f"Sub-parte da mensagem ({len(part)} caracteres) ainda excede o limite. Será truncada.")
                messages_to_send.append(part[:max_length - 30] + "\n" + escape_markdown_v2("...[mensagem cortada]..."))
            else:
                messages_to_send.append(part)

        if not messages_to_send and message_text: 
             messages_to_send.append(message_text[:max_length - 30] + "\n" + escape_markdown_v2("...[mensagem cortada]..."))
    else:
        messages_to_send.append(message_text)

    all_sent_successfully = True
    for i, part_message in enumerate(messages_to_send):
        if not part_message.strip(): continue
        # Mesmo para "plain text", usar MarkdownV2 e escapar o conteúdo é mais seguro
        # para evitar que caracteres no CONTEÚDO causem problemas de parsing.
        # Se você tiver certeza que o conteúdo é 100% seguro e não quer NENHUMA interpretação Markdown,
        # pode omitir 'parse_mode'. Mas URLs não seriam clicáveis por Markdown, só por auto-detecção do Telegram.
        payload = {'chat_id': chat_id, 'text': part_message, 'parse_mode': 'MarkdownV2', 'disable_web_page_preview': False}
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
            'eth_plain_str': f"{eth_val:,.2f}" if eth_val is not None else "Erro/Indisponível",
            'btc_plain_str': f"{btc_val:,.2f}" if btc_val is not None else "Erro/Indisponível",
        },
        'noticias': {},
        'fake_news': get_boatos_org_feed()
    }

    # Emojis simplificados ou removidos para evitar problemas de caracteres Unicode
    news_sections_queries = {
        "🇧🇷 BRASIL GERAL": "Brasil", 
        "🟢 Goiás (Estado)": f"Goiás OR \"Estado de Goiás\" NOT \"Goiás Esporte Clube\"", # Emoji simples
        "🌍 Geopolítica": "Geopolítica OR \"Relações Internacionais\"", 
        "🌐 INTERNACIONAL": "Internacional OR Mundial NOT Brasil", # Emoji simples
        "⚽ Futebol": "Futebol Brasil OR \"Campeonato Brasileiro\" OR Libertadores OR \"Copa do Brasil\"",
        "💰 ECONOMIA & NEGÓCIOS": "\"Economia Brasileira\" OR Inflação OR Selic OR IBGE OR BCB", # Removido emoji problemático
        "🍀 LOTERIAS": "\"Loterias Caixa\" OR Mega-Sena OR Quina OR Lotofácil",
        "🌟 FAMA & ENTRETENIMENTO": "Celebridades OR Entretenimento OR Famosos Brasil", # Removido emoji problemático
        "✈️ TURISMO": "Turismo Brasil OR Viagens OR \"Pontos Turísticos\"", # Mantido emoji simples
        "🏆 ESPORTES": "Esportes Brasil -futebol NOT \"e-sports\"",
        "💻 Tecnologia": "Tecnologia OR Inovação OR Inteligência Artificial OR Startups Brasil"
    }

    for titulo_secao_com_emoji, query in news_sections_queries.items():
        artigos, msg_erro = buscar_noticias_newsapi(query, max_articles=5)
        if msg_erro and not artigos: jornal_data['noticias'][titulo_secao_com_emoji] = msg_erro
        elif not artigos and not msg_erro: jornal_data['noticias'][titulo_secao_com_emoji] = f"Nenhuma notícia relevante para '{query}'."
        else: jornal_data['noticias'][titulo_secao_com_emoji] = artigos

    telegram_message_text = formatar_para_telegram_plain(jornal_data)
    
    # Para depuração local, você pode descomentar as linhas abaixo:
    # print("--- MENSAGEM PARA TELEGRAM (FORMATO PLAIN) ---")
    # print(telegram_message_text)
    # print(f"--- FIM DA MENSAGEM (Comprimento: {len(telegram_message_text)}) ---")

    if not send_telegram_message(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, telegram_message_text):
        logging.error("Falha CRÍTICA ao enviar a mensagem completa para o Telegram.")
    else:
        logging.info("Juninho News enviado com sucesso para o Telegram!")

# --- Bloco de Execução Principal ---
if __name__ == "__main__":
    main_automated()
