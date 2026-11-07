"""
Achei pra Casa — fábrica automática de Shorts (100% grátis)

Fluxo:
 1. Busca os MAIS VENDIDOS de categorias de casa no Mercado Livre (API oficial /highlights)
 2. Gemini escolhe o produto que mais resolve uma DOR e escreve título, descrição, tags e narração
 3. Pega um vídeo REAL do produto (vídeo do anúncio no ML; se não tiver, busca no YouTube)
 4. Gera narração em voz natural (edge-tts, grátis) e monta o Short 9:16 com FFmpeg
 5. Publica no YouTube no modelo do canal + comenta o link do grupo VIP
 6. Salva em historico.json para nunca repetir produto

Quem dispara: o cenário do Make (repository_dispatch) enviando o access_token do Mercado Livre.
"""
import json
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

# ----------------------------------------------------------------- CONFIG
GRUPO_WHATSAPP = os.getenv("GRUPO_WHATSAPP", "https://chat.whatsapp.com/Dm1Mv7qgbPRDNZN1zvLZRz")

# Categorias do ML (Brasil). Ajuste à vontade.
CATEGORIAS = {
    "MLB1574": "Casa, Móveis e Decoração",
    "MLB5726": "Eletrodomésticos",
    "MLB1499": "Indústria e Comércio",  # tem muito utilitário de cozinha/limpeza
    "MLB263532": "Ferramentas",
}
# Palavras que NÃO queremos (fora do nicho "achadinho para casa")
BLOQUEADAS = ["geladeira", "fogão", "máquina de lavar", "lavadora", "sofá", "colchão",
              "cama box", "guarda-roupa", "ar condicionado", "freezer", "televisor", "smart tv"]

VOZ = os.getenv("VOZ", "pt-BR-AntonioNeural")   # ou pt-BR-FranciscaNeural / pt-BR-ThalitaNeural
VELOCIDADE_VOZ = os.getenv("VELOCIDADE_VOZ", "+12%")
VOLUME_ORIGINAL = float(os.getenv("VOLUME_ORIGINAL", "0.12"))  # áudio original do vídeo bem baixinho
# True = no fallback do YouTube só usa vídeos Creative Commons (protege o canal de strike)
SOMENTE_CREATIVE_COMMONS = os.getenv("SOMENTE_CREATIVE_COMMONS", "true").lower() == "true"
PRIVACIDADE = os.getenv("PRIVACIDADE", "public")  # use "private" nos primeiros testes
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ML_TOKEN = os.getenv("ML_ACCESS_TOKEN", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID", "")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET", "")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN", "")
YT_COOKIES = os.getenv("YT_COOKIES", "")  # opcional: cookies.txt (Netscape) p/ o yt-dlp não ser bloqueado
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"  # monta o vídeo mas não publica

BASE = Path(__file__).parent
TMP = BASE / "tmp"
TMP.mkdir(exist_ok=True)
HIST = BASE / "historico.json"
ML = "https://api.mercadolibre.com"


def log(*a):
    print("[achei]", *a, flush=True)


def run(cmd, **kw):
    log("$", " ".join(str(c) for c in cmd)[:300])
    return subprocess.run(cmd, check=True, **kw)


def carregar_historico():
    if HIST.exists():
        return json.loads(HIST.read_text(encoding="utf-8"))
    return []


def salvar_historico(h):
    HIST.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------- 1. MERCADO LIVRE
def ml_get(path, **params):
    headers = {"Authorization": f"Bearer {ML_TOKEN}"} if ML_TOKEN else {}
    r = requests.get(ML + path, headers=headers, params=params, timeout=30)
    if r.status_code != 200:
        log("ML", r.status_code, path, r.text[:200])
        return None
    return r.json()


def detalhes(entry):
    """Converte uma entrada do /highlights em produto padronizado."""
    pid, tipo = entry["id"], entry.get("type", "ITEM")
    if tipo == "PRODUCT":
        p = ml_get(f"/products/{pid}")
        if not p:
            return None
        item_id = (p.get("buy_box_winner") or {}).get("item_id")
        video = None
        if item_id:
            it = ml_get(f"/items/{item_id}")
            video = (it or {}).get("video_id")
        return {
            "id": pid,
            "nome": p.get("name", ""),
            "link": p.get("permalink") or f"https://www.mercadolivre.com.br/p/{pid}",
            "fotos": [x.get("url") for x in p.get("pictures", [])][:3],
            "video_id": video,
            "descricao": (p.get("short_description") or {}).get("content", "")[:600],
        }
    it = ml_get(f"/items/{pid}")
    if not it:
        return None
    return {
        "id": pid,
        "nome": it.get("title", ""),
        "link": it.get("permalink", ""),
        "fotos": [x.get("secure_url") for x in it.get("pictures", [])][:3],
        "video_id": it.get("video_id"),
        "descricao": "",
    }


def buscar_candidatos(historico, limite=25):
    ja = {h["id"] for h in historico}
    cand = []
    cats = list(CATEGORIAS)
    random.shuffle(cats)
    for cat in cats:
        hl = ml_get(f"/highlights/MLB/category/{cat}")
        if not hl:
            continue
        for e in hl.get("content", [])[:20]:
            if e["id"] in ja:
                continue
            d = detalhes(e)
            if not d or not d["nome"]:
                continue
            if any(b in d["nome"].lower() for b in BLOQUEADAS):
                continue
            d["categoria"] = CATEGORIAS[cat]
            d["posicao"] = e.get("position")
            cand.append(d)
            if len(cand) >= limite:
                return cand
    return cand


# ----------------------------------------------------------------- 2. GEMINI
PROMPT = """Você é o roteirista do canal de YouTube Shorts "Achei pra Casa" (achadinhos para casa).
Abaixo estão produtos MAIS VENDIDOS do Mercado Livre agora. Escolha UM: o que resolve uma DOR
do dia a dia mais forte, mais visual, com mais cara de "viralizou" e mais fácil de entender em 3 segundos.

PRODUTOS (JSON):
{produtos}

Responda SOMENTE um JSON com estas chaves:
- "id": id do produto escolhido (exatamente como veio)
- "dor": a dor resolvida em poucas palavras
- "titulo": título do Short em CAIXA ALTA, frase curta que ataca a DOR em tom de ordem/conselho,
   SEM citar o nome do produto, máximo 45 caracteres. Exemplos do canal:
   "PARE DE CHORAR PRA CORTAR CEBOLA", "CHEGA DE SOFRER PRA LIMPAR O FOGÃO", "NUNCA MAIS PERCA TEMPO DOBRANDO ROUPA"
- "nome_curto": nome do produto em CAIXA ALTA, 2 a 4 palavras, sem marca (ex: "MINI TRITURADOR ELETRICO")
- "hashtags_titulo": exatamente 3 hashtags; as duas primeiras SEMPRE "#achadinhos" e "#shopee",
   a terceira do contexto (ex: "#dicas", "#cozinha", "#limpeza", "#organizacao")
- "hashtags_descricao": 4 hashtags; SEMPRE "#achadinhos" e "#compras", mais 2 do contexto (ex: "#donadecasa")
- "tags": 12 tags de SEO em minúsculas: sempre "achadinhos", "achadinhos para casa", "achadinhos shopee",
   "compras para casa", e 8 específicas (o que o produto é, como as pessoas pesquisam a dor, ex: "como cortar cebola sem chorar")
- "narracao": texto falado de 45 a 60 palavras (cerca de 20 a 25 segundos), português do Brasil natural,
   muito persuasivo, frases curtas. Estrutura:
     (1) GANCHO com a dor em 1 frase que prende ("Você ainda chora toda vez que corta cebola?")
     (2) como o produto resolve, com 2 benefícios concretos e visuais
     (3) prova social/urgência ("tá todo mundo comprando", "esgota rápido")
     (4) CTA final: "Entra no nosso grupo do WhatsApp de achadinhos pra casa, com desconto todo dia! O link tá na descrição."
   Não use emojis, hashtags, nem preço. Não diga "Shopee" nem "Mercado Livre".
- "busca_video": termo curto para buscar um vídeo real desse produto no YouTube (ex: "mini triturador elétrico de alho usb")
"""


def gemini(produtos):
    enxuto = [{k: p[k] for k in ("id", "nome", "categoria", "posicao", "descricao")} for p in produtos]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "contents": [{"parts": [{"text": PROMPT.format(produtos=json.dumps(enxuto, ensure_ascii=False))}]}],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.9},
    }
    for tentativa in range(4):
        r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=90)
        if r.status_code == 200:
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(re.sub(r"^```(json)?|```$", "", txt.strip()))
        log("Gemini", r.status_code, r.text[:300])
        time.sleep(15 * (tentativa + 1))
    raise RuntimeError("Gemini falhou")


# ----------------------------------------------------------------- 3. VÍDEO REAL
def yt_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials(None, refresh_token=YT_REFRESH_TOKEN, client_id=YT_CLIENT_ID,
                        client_secret=YT_CLIENT_SECRET, token_uri="https://oauth2.googleapis.com/token")
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


def baixar(url, destino):
    cmd = ["yt-dlp", "-f", "bv*[height<=1920][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b",
           "--merge-output-format", "mp4", "--max-filesize", "150M", "-o", str(destino), url]
    if YT_COOKIES:
        ck = TMP / "cookies.txt"
        ck.write_text(YT_COOKIES)
        cmd[1:1] = ["--cookies", str(ck)]
    try:
        run(cmd)
        return destino.exists() and destino.stat().st_size > 50_000
    except subprocess.CalledProcessError:
        return False


def obter_video(produto, busca, yt):
    destino = TMP / "original.mp4"
    destino.unlink(missing_ok=True)
    vid = produto.get("video_id")
    # 3a. vídeo do próprio anúncio do Mercado Livre (vendedor)
    if vid:
        url = f"https://www.youtube.com/watch?v={vid}" if len(vid) == 11 else vid
        log("Vídeo do anúncio:", url)
        if baixar(url, destino):
            return destino, url
    # 3b. busca no YouTube (vídeos curtos, de preferência Creative Commons)
    params = dict(part="id,snippet", q=busca, type="video", videoDuration="short",
                  maxResults=10, regionCode="BR", relevanceLanguage="pt")
    if SOMENTE_CREATIVE_COMMONS:
        params["videoLicense"] = "creativeCommon"
    res = yt.search().list(**params).execute()
    for it in res.get("items", []):
        url = f"https://www.youtube.com/watch?v={it['id']['videoId']}"
        log("Tentando vídeo:", it["snippet"]["title"], url)
        if baixar(url, destino):
            return destino, url
    return None, None


# ----------------------------------------------------------------- 4. NARRAÇÃO + MONTAGEM
def duracao(arq):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", str(arq)])
    return float(out.strip())


def tem_audio(arq):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "a",
                                   "-show_entries", "stream=index", "-of", "csv=p=0", str(arq)])
    return bool(out.strip())


def narrar(texto):
    mp3 = TMP / "narracao.mp3"
    run(["edge-tts", "--voice", VOZ, f"--rate={VELOCIDADE_VOZ}", "--text", texto, "--write-media", str(mp3)])
    return mp3


def montar(video, narracao):
    final = TMP / "short.mp4"
    dur = min(duracao(narracao) + 0.8, 59.0)
    vdur = duracao(video)
    # pula os primeiros segundos (geralmente vinheta) se o vídeo for comprido
    inicio = 1.5 if vdur > dur + 4 else 0
    vf = ("scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
          "setsar=1,fps=30,eq=saturation=1.08:contrast=1.04")
    if tem_audio(video):
        af = (f"[0:a]volume={VOLUME_ORIGINAL}[bg];[1:a]volume=1.6,apad[nar];"
              f"[bg][nar]amix=inputs=2:duration=longest:dropout_transition=0[a]")
    else:
        af = "[1:a]volume=1.6,apad[a]"
    run(["ffmpeg", "-y", "-stream_loop", "-1", "-ss", str(inicio), "-i", str(video), "-i", str(narracao),
         "-filter_complex", f"[0:v]{vf}[v];{af}", "-map", "[v]", "-map", "[a]",
         "-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "medium", "-crf", "21",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(final)])
    return final


# ----------------------------------------------------------------- 5. YOUTUBE
def descricao(roteiro, produto):
    return (
        "🛍️ LINK DE TODOS OS PRODUTOS AQUI\n\n"
        f"🔴GRUPO VIP DE PROMOÇÕES NO WHATSAPP🔴\n{GRUPO_WHATSAPP}\n\n"
        f"🛍️{roteiro['nome_curto']}\n{produto['link']}\n\n"
        f"🟢GRUPO DE OFERTAS E CUPONS DE DESCONTO🟢\n{GRUPO_WHATSAPP}\n"
        "O grupo é somente de postagem de produtos, sem chat.\n"
        "Nele você encontra achadinhos para casa com cupons de desconto todos os dias!\n\n"
        + " ".join(roteiro["hashtags_descricao"])
    )


def publicar(yt, arquivo, roteiro, produto):
    from googleapiclient.http import MediaFileUpload
    titulo = f"{roteiro['titulo'].upper()}   {' '.join(roteiro['hashtags_titulo'])}"[:100]
    body = {
        "snippet": {
            "title": titulo,
            "description": descricao(roteiro, produto),
            "tags": roteiro["tags"][:15],
            "categoryId": "26",  # Guias e Estilo
            "defaultLanguage": "pt-BR",
            "defaultAudioLanguage": "pt-BR",
        },
        "status": {"privacyStatus": PRIVACIDADE, "selfDeclaredMadeForKids": False},
    }
    req = yt.videos().insert(part="snippet,status", body=body,
                             media_body=MediaFileUpload(str(arquivo), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    log("Publicado:", titulo, f"https://youtube.com/shorts/{vid}")
    try:
        yt.commentThreads().insert(part="snippet", body={"snippet": {
            "videoId": vid,
            "topLevelComment": {"snippet": {"textOriginal":
                f"🔴 GRUPO VIP DE ACHADINHOS PRA CASA COM DESCONTO TODO DIA 👉 {GRUPO_WHATSAPP}"}}}}).execute()
    except Exception as e:  # comentário é bônus, não derruba o fluxo
        log("Comentário falhou:", e)
    return vid, titulo


# ----------------------------------------------------------------- MAIN
def main():
    historico = carregar_historico()
    candidatos = buscar_candidatos(historico)
    log(f"{len(candidatos)} candidatos")
    if not candidatos:
        sys.exit("Nenhum produto novo. Confira o ML_ACCESS_TOKEN.")

    yt = yt_service()
    tentados = set()
    for _ in range(4):  # até 4 produtos diferentes se não achar vídeo
        restantes = [c for c in candidatos if c["id"] not in tentados]
        if not restantes:
            break
        roteiro = gemini(restantes)
        produto = next((c for c in restantes if c["id"] == roteiro["id"]), restantes[0])
        tentados.add(produto["id"])
        log("Escolhido:", produto["nome"], "| dor:", roteiro.get("dor"))
        video, fonte = obter_video(produto, roteiro["busca_video"], yt)
        if not video:
            log("Sem vídeo real para", produto["nome"], "— tentando outro produto")
            continue
        final = montar(video, narrar(roteiro["narracao"]))
        (TMP / "roteiro.json").write_text(json.dumps(roteiro, ensure_ascii=False, indent=2), encoding="utf-8")
        if DRY_RUN:
            log("DRY_RUN: vídeo pronto em", final)
            return
        vid, titulo = publicar(yt, final, roteiro, produto)
        historico.append({"id": produto["id"], "nome": produto["nome"], "youtube": vid,
                          "titulo": titulo, "fonte_video": fonte, "data": time.strftime("%Y-%m-%d %H:%M")})
        salvar_historico(historico)
        return
    sys.exit("Não achei vídeo real para nenhum candidato nesta rodada.")


if __name__ == "__main__":
    main()
