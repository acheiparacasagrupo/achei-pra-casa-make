"""
Achei pra Casa — fábrica automática de Shorts (100% grátis, SEM API do Mercado Livre e SEM API do YouTube)

GitHub Actions (3x por dia):
 1. Abre a página pública "Mais vendidos" do Mercado Livre (categorias de casa) e coleta os produtos
 2. Gemini ranqueia: qual resolve a DOR mais forte e tem mais cara de viral
 3. Abre a página do produto e pega o VÍDEO REAL (clips do próprio anúncio)
 4. Gemini escreve título, descrição, tags e narração (dor -> solução -> CTA do grupo)
 5. Narração com voz natural (edge-tts) + montagem 9:16 com FFmpeg (< 5 MB, limite do Make grátis)
 6. Publica o vídeo como Release do GitHub e avisa o Make (webhook)
Make: recebe o webhook -> baixa o vídeo -> posta no YouTube pela conta conectada no próprio Make.
"""
import html
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

# ----------------------------------------------------------------- CONFIG
GRUPO_WHATSAPP = os.getenv("GRUPO_WHATSAPP") or "https://chat.whatsapp.com/Dm1Mv7qgbPRDNZN1zvLZRz"
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL", "")
GEMINI_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELS = [m for m in (os.getenv("GEMINI_MODEL", ""), "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash") if m]
VOZ = os.getenv("VOZ") or "pt-BR-AntonioNeural"          # ou pt-BR-FranciscaNeural / pt-BR-ThalitaNeural
VELOCIDADE_VOZ = os.getenv("VELOCIDADE_VOZ") or "+12%"
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true")
REPO = os.getenv("GITHUB_REPOSITORY", "")

BASE_MV = "https://www.mercadolivre.com.br/mais-vendidos/MLB1574"  # Casa, Móveis e Decoração
# subcategorias com mais "achadinho que resolve dor" (nomes como aparecem no site)
SUBCATS_PREFERIDAS = ["Cozinha", "Organização para Casa", "Cuidado da Casa e Lavanderia", "Banheiros",
                      "Iluminação Residencial", "Segurança para Casa", "Jardim e Ar Livre"]
EXTRAS = ["https://www.mercadolivre.com.br/mais-vendidos/MLB5726"]  # Eletrodomésticos (mini processador, etc.)
BLOQUEADAS = ["papel higiênico", "papel higienico", "lava roupas", "sabão", "detergente", "água sanitária",
              "agua sanitaria", "lençol", "lencol", "colchão", "colchao", "cortina", "sofá", "guarda-roupa",
              "geladeira", "fogão", "fogao", "máquina de lavar", "ar condicionado", "tapete", "colcha", "ducha"]

MAX_MB = 4.3  # Make grátis aceita arquivos de até 5 MB
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")

BASE = Path(__file__).parent
TMP = BASE / "tmp"
TMP.mkdir(exist_ok=True)
HIST = BASE / "historico.json"


def log(*a):
    print("[achei]", *a, flush=True)


def run(cmd, **kw):
    log("$", " ".join(str(c) for c in cmd)[:250])
    return subprocess.run(cmd, check=True, **kw)


def pid(url):
    m = re.search(r"/p/(MLB\d+)", url) or re.search(r"(MLB)-?(\d+)", url)
    if not m:
        return url
    return m.group(1) if m.lastindex == 1 else f"MLB{m.group(2)}"


# ----------------------------------------------------------------- 1. MAIS VENDIDOS (sem API)
def coletar(page, historico):
    ja = {h["id"] for h in historico}
    page.goto(BASE_MV, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    subcats = page.eval_on_selector_all(
        "a.ui-search-link", "els => els.map(a => [a.innerText.trim(), a.href.split('#')[0].split('?')[0]])")
    urls = [u for n, u in subcats if n in SUBCATS_PREFERIDAS and "/mais-vendidos/" in u] + EXTRAS
    log("Subcategorias:", len(urls))
    produtos = {}
    for url in urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            for _ in range(3):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(600)
            itens = page.eval_on_selector_all("a.poly-component__title", """els => els.map(a => {
                const card = a.closest('.poly-card') || a.parentElement.parentElement;
                return {titulo: a.innerText.trim(), link: a.href.split('#')[0].split('?')[0],
                        info: (card ? card.innerText : '').replace(/\\s+/g,' ').slice(0, 200)};
            })""")
        except Exception as e:
            log("falha em", url, e)
            continue
        for it in itens:
            it["id"] = pid(it["link"])
            low = it["titulo"].lower()
            if it["id"] in ja or any(b in low for b in BLOQUEADAS):
                continue
            produtos.setdefault(it["id"], it)
    log(len(produtos), "produtos novos coletados")
    return list(produtos.values())


def videos_do_produto(page, link):
    """Os clips do anúncio vêm no HTML como "video_url": ".../playlists/....m3u8"."""
    page.goto(link, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    src = page.content()
    urls = []
    for m in re.finditer(r'"video_url"\s*:\s*"([^"]+)"', src):
        try:
            u = json.loads('"' + m.group(1) + '"')
        except ValueError:
            u = m.group(1)
        u = html.unescape(u)
        if u.startswith("http") and u not in urls:
            urls.append(u)
    desc = ""
    try:
        desc = page.inner_text(".ui-pdp-description__content", timeout=3000)[:1200]
    except Exception:
        pass
    return urls[:3], desc


# ----------------------------------------------------------------- 2/4. GEMINI
def gemini_json(prompt, temperatura=0.8):
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperatura}}
    for modelo in GEMINI_MODELS:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
        for tentativa in range(3):
            r = requests.post(url, params={"key": GEMINI_KEY}, json=body, timeout=120)
            if r.status_code == 200:
                txt = r.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                return json.loads(re.sub(r"^```(?:json)?|```$", "", txt).strip())
            log("Gemini", modelo, r.status_code, r.text[:200])
            if r.status_code in (400, 404):
                break  # modelo não existe -> próximo
            time.sleep(10 * (tentativa + 1))
    raise RuntimeError("Gemini falhou em todos os modelos")


def ranquear(produtos):
    topo = produtos[:60]
    lista = "\n".join(f"{i}: {p['titulo'][:100]} | {p['info'][:90]}" for i, p in enumerate(topo))
    r = gemini_json(
        "Você escolhe produtos para Shorts virais de 'achadinhos para casa'. Abaixo estão os mais vendidos do "
        "Mercado Livre. Ordene do MELHOR para o pior: resolve uma DOR clara do dia a dia, é visual/demonstrável "
        "em vídeo, tem efeito 'uau', é barato e de compra por impulso. Descarte itens comuns de supermercado, "
        "roupa de cama e produtos sem apelo visual.\n"
        'Responda JSON: {"ordem": [índices, no máximo 10]}\n\n' + lista, 0.4)
    ordem = [i for i in r.get("ordem", []) if isinstance(i, int) and 0 <= i < len(topo)]
    return [topo[i] for i in ordem] or topo[:10]


PROMPT_ROTEIRO = """Você é o roteirista do canal de YouTube Shorts "Achei pra Casa" (achadinhos para casa).
Produto: {titulo}
Info do anúncio: {info}
Descrição do vendedor: {desc}

Responda SOMENTE um JSON com:
- "dor": a dor resolvida, em poucas palavras
- "titulo": CAIXA ALTA, frase curta que ataca a DOR em tom de ordem/conselho, SEM o nome do produto,
   máximo 45 caracteres. Exemplos do canal: "PARE DE CHORAR PRA CORTAR CEBOLA",
   "CHEGA DE SOFRER PRA LIMPAR O FOGÃO", "NUNCA MAIS PERCA TEMPO DOBRANDO ROUPA"
- "nome_curto": nome do produto em CAIXA ALTA, 2 a 4 palavras, sem marca (ex: "MINI TRITURADOR ELETRICO")
- "hashtags_titulo": exatamente 3 hashtags: "#achadinhos", "#shopee" e uma do contexto (ex: "#dicas", "#cozinha", "#limpeza")
- "hashtags_descricao": 4 hashtags: "#achadinhos", "#compras" e 2 do contexto (ex: "#donadecasa", "#organizacao")
- "tags": 12 tags em minúsculas: "achadinhos", "achadinhos para casa", "achadinhos shopee", "compras para casa"
   e 8 específicas (o que é o produto e como as pessoas pesquisam a dor, ex: "como cortar cebola sem chorar")
- "narracao": 45 a 60 palavras (20 a 25 segundos), português do Brasil natural, MUITO persuasivo, frases curtas:
   (1) GANCHO com a dor em 1 pergunta que prende ("Você ainda chora toda vez que corta cebola?")
   (2) como o produto resolve, com 2 benefícios concretos e visuais
   (3) prova social/urgência ("tá todo mundo comprando", "esgota rápido")
   (4) termine EXATAMENTE com: "Entra no nosso grupo do WhatsApp de achadinhos pra casa, com desconto todo dia! O link tá na descrição."
   Sem emojis, sem hashtags, sem preço, sem dizer "Shopee" ou "Mercado Livre".
"""


def roteiro(prod, desc):
    return gemini_json(PROMPT_ROTEIRO.format(titulo=prod["titulo"], info=prod["info"], desc=desc[:1000]), 0.9)


# ----------------------------------------------------------------- 3/5. VÍDEO + VOZ + MONTAGEM
def duracao(arq):
    out = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                   "-of", "default=nw=1:nk=1", str(arq)])
    return float(out.strip())


def baixar_clips(urls):
    """Baixa até 3 clips (m3u8) e normaliza para 720x1280 sem áudio."""
    partes = []
    for i, u in enumerate(urls):
        bruto, norm = TMP / f"clip{i}.mp4", TMP / f"clip{i}_n.mp4"
        try:
            http = ["-user_agent", UA, "-headers", "Referer: https://www.mercadolivre.com.br/\r\n"] \
                if u.startswith("http") else []
            run(["ffmpeg", "-y", "-loglevel", "error", *http, "-i", u, "-t", "40", "-c", "copy", str(bruto)])
            run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(bruto), "-an", "-vf",
                 "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,fps=30",
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(norm)])
            if duracao(norm) > 2:
                partes.append(norm)
        except Exception as e:
            log("clip falhou:", e)
    if not partes:
        return None
    lista = TMP / "lista.txt"
    lista.write_text("".join(f"file '{p.name}'\n" for p in partes))
    final = TMP / "original.mp4"
    run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lista), "-c", "copy", str(final)])
    return final


def narrar(texto):
    mp3 = TMP / "narracao.mp3"
    run(["edge-tts", "--voice", VOZ, f"--rate={VELOCIDADE_VOZ}", "--text", texto, "--write-media", str(mp3)])
    return mp3


def montar(video, narracao):
    final = TMP / "short.mp4"
    dur = min(duracao(narracao) + 0.8, 58.0)
    audio_kbps = 96
    video_kbps = int(min(2500, (MAX_MB * 8192) / dur - audio_kbps))  # cabe em < 5 MB
    run(["ffmpeg", "-y", "-loglevel", "error", "-stream_loop", "-1", "-i", str(video), "-i", str(narracao),
         "-filter_complex", "[0:v]eq=saturation=1.08:contrast=1.04[v];[1:a]volume=1.5,apad[a]",
         "-map", "[v]", "-map", "[a]", "-t", f"{dur:.2f}",
         "-c:v", "libx264", "-preset", "medium", "-b:v", f"{video_kbps}k", "-maxrate", f"{video_kbps}k",
         "-bufsize", f"{video_kbps * 2}k", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-movflags", "+faststart", str(final)])
    log(f"Short: {dur:.1f}s, {final.stat().st_size / 1e6:.2f} MB")
    return final


# ----------------------------------------------------------------- 6. RELEASE + MAKE
def descricao(r, prod):
    return ("🛍️ LINK DE TODOS OS PRODUTOS AQUI\n\n"
            f"🔴GRUPO VIP DE PROMOÇÕES NO WHATSAPP🔴\n{GRUPO_WHATSAPP}\n\n"
            f"🛍️{r['nome_curto']}\n{prod['link']}\n\n"
            f"🟢GRUPO DE OFERTAS E CUPONS DE DESCONTO🟢\n{GRUPO_WHATSAPP}\n"
            "O grupo é somente de postagem de produtos, sem chat.\n"
            "Nele você encontra achadinhos para casa com cupons de desconto todos os dias!\n\n"
            + " ".join(r["hashtags_descricao"]))


def publicar_release(arquivo, tag):
    run(["gh", "release", "create", tag, str(arquivo), "--repo", REPO, "--title", tag, "--notes", "Short gerado automaticamente"])
    # mantém só os 15 releases mais recentes
    try:
        out = subprocess.check_output(["gh", "release", "list", "--repo", REPO, "--limit", "100", "--json", "tagName"])
        for rel in json.loads(out)[15:]:
            subprocess.run(["gh", "release", "delete", rel["tagName"], "--repo", REPO, "--yes", "--cleanup-tag"])
    except Exception as e:
        log("limpeza de releases:", e)
    return f"https://github.com/{REPO}/releases/download/{tag}/short.mp4"


def avisar_make(payload):
    r = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=60)
    log("Make respondeu:", r.status_code, r.text[:200])
    r.raise_for_status()


# ----------------------------------------------------------------- MAIN
def main():
    from playwright.sync_api import sync_playwright
    historico = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else []
    with sync_playwright() as p:
        nav = p.chromium.launch(headless=True)
        page = nav.new_context(user_agent=UA, locale="pt-BR", viewport={"width": 1366, "height": 900}).new_page()
        candidatos = coletar(page, historico)
        if not candidatos:
            sys.exit("Nenhum produto coletado (o ML pode ter mudado o layout ou bloqueado o acesso).")
        escolhido = None
        for prod in ranquear(candidatos):
            log("Checando vídeo de:", prod["titulo"])
            try:
                clips, desc = videos_do_produto(page, prod["link"])
            except Exception as e:
                log("página falhou:", e)
                continue
            if not clips:
                log("  sem vídeo no anúncio")
                continue
            video = baixar_clips(clips)
            if video:
                escolhido = (prod, desc, video)
                break
        nav.close()
    if not escolhido:
        sys.exit("Nenhum dos melhores produtos tinha vídeo real nesta rodada.")

    prod, desc, video = escolhido
    r = roteiro(prod, desc)
    log("Produto:", prod["titulo"], "| dor:", r.get("dor"))
    final = montar(video, narrar(r["narracao"]))
    titulo = f"{r['titulo'].upper()}   {' '.join(r['hashtags_titulo'])}"[:100]
    payload = {"titulo": titulo, "descricao": descricao(r, prod), "tags": ",".join(r["tags"][:15]),
               "produto": prod["titulo"], "link_produto": prod["link"], "narracao": r["narracao"],
               "comentario": f"🔴 GRUPO VIP DE ACHADINHOS PRA CASA COM DESCONTO TODO DIA 👉 {GRUPO_WHATSAPP}"}
    (TMP / "roteiro.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if DRY_RUN:
        log("DRY_RUN: vídeo pronto, não publicado. Baixe em Artifacts.")
        return
    tag = f"short-{time.strftime('%Y%m%d-%H%M')}"
    payload["video_url"] = publicar_release(final, tag)
    avisar_make(payload)
    historico.append({"id": prod["id"], "produto": prod["titulo"], "titulo": titulo,
                      "release": tag, "data": time.strftime("%Y-%m-%d %H:%M")})
    HIST.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
