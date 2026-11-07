"""
Achei pra Casa — fábrica automática de Shorts (100% grátis, SEM API do Mercado Livre e SEM API do YouTube)

GitHub Actions (3x por dia):
 1. Lê a fila.json (preenchida pela extensão "Achei pra Casa - Coletor" no seu Chrome, com os
    mais vendidos de casa do Mercado Livre e os links dos VÍDEOS REAIS dos anúncios)
 2. Gemini ranqueia: qual resolve a DOR mais forte e tem mais cara de viral
 3. Baixa os clips reais do anúncio (CDN público do ML)
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


FILA = Path(__file__).parent / "fila.json"


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


def ranquear(produtos, recentes=()):
    topo = produtos[:60]
    lista = "\n".join(f"{i}: {p['titulo'][:100]} | {p.get('info','')[:90]}" for i, p in enumerate(topo))
    r = gemini_json(
        "Você escolhe produtos para Shorts virais de 'achadinhos para casa'. Abaixo estão os mais vendidos do "
        "Mercado Livre. Ordene do MELHOR para o pior: resolve uma DOR clara do dia a dia, é visual/demonstrável "
        "em vídeo, tem efeito 'uau', é barato e de compra por impulso. Descarte itens comuns de supermercado, "
        "roupa de cama e produtos sem apelo visual.\n"
        "IMPORTANTE: varie! NÃO escolha primeiro um produto do mesmo tipo destes postados recentemente: "
        + "; ".join(recentes) + "\n"
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
    return gemini_json(PROMPT_ROTEIRO.format(titulo=prod["titulo"], info=prod.get("info", ""), desc=desc[:1000]), 0.9)


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
    historico = json.loads(HIST.read_text(encoding="utf-8")) if HIST.exists() else []
    fila = json.loads(FILA.read_text(encoding="utf-8")) if FILA.exists() else []
    feitos = {h["id"] for h in historico}
    fila = [p for p in fila if p["id"] not in feitos and p.get("videos")]
    if not fila:
        log("Fila vazia: a extensão do Chrome ainda não mandou produtos novos. Nada a fazer agora.")
        return
    escolhido = None
    recentes = [h.get("produto", "")[:60] for h in historico[-8:] if h.get("produto")]
    for prod in ranquear(fila, recentes):
        log("Tentando:", prod["titulo"])
        video = baixar_clips(prod["videos"])
        if video:
            escolhido = (prod, video)
            break
        log("  vídeos não baixaram; removendo da fila")
        historico.append({"id": prod["id"], "produto": prod["titulo"], "erro": "video", "data": time.strftime("%Y-%m-%d %H:%M")})
    if not escolhido:
        HIST.write_text(json.dumps(historico, ensure_ascii=False, indent=2), encoding="utf-8")
        sys.exit("Nenhum vídeo da fila pôde ser baixado.")

    prod, video = escolhido
    r = roteiro(prod, prod.get("descricao", ""))
    log("Produto:", prod["titulo"], "| dor:", r.get("dor"))
    final = montar(video, narrar(r["narracao"]))
    titulo = f"{r['titulo'].upper()}   {' '.join(r['hashtags_titulo'])}"[:100].replace("<", "").replace(">", "")
    payload = {"titulo": titulo, "descricao": descricao(r, prod).replace("<", "").replace(">", ""),
               "tags": ",".join(t.replace(",", " ") for t in r["tags"][:15]),
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
