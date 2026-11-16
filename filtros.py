"""Filtros compartilhados: o que é (e o que não é) achadinho, e o 'tipo' do produto para não repetir."""
import re
import unicodedata

# Produtos básicos/commodities que vendem muito mas NÃO são achadinhos
BLOQUEADAS = [
    "cloro", "piscina", "domclor", "tratamento de agua", "toalha", "chuveiro", "ducha", "liquidificador", "panela de pressao", "air fryer",
    "fritadeira", "refil", "lampada", "refletor", "limpador multiuso", "veja ", "repelente", "torneira",
    "guarda roupa", "guarda-roupa", "colchao", "lencol", "edredom", "papel higienico", "detergente", "sabao",
    "lava roupas", "desinfetante", "agua sanitaria", "canfora", "controle remoto", "portao", "fechadura",
    "camera", "tv ", "smart tv", "ventilador de coluna", "ar condicionado", "aspirador vertical", "aspirador de po vertical", "cortina",
    "tapete sala", "jogo de cama", "travesseiro", "cobertor", "pano de prato", "faqueiro", "talheres",
    "aparelho de jantar", "jogo de copos", "pilha", "bateria", "cabo usb", "carregador",
    "racao", "areia", "fralda", "shampoo", "condicionador", "creme", "perfume", "garrafa de agua mineral",
]

# Palavras genéricas que não dizem o "tipo" do produto
GENERICAS = {
    "kit", "com", "para", "de", "da", "do", "das", "dos", "e", "em", "a", "o", "cor", "un", "und", "unidades",
    "unidade", "pecas", "pcs", "pc", "adulto", "infantil", "grande", "pequeno", "medio", "novo", "nova",
    "original", "premium", "super", "mini", "multiuso", "casa", "cozinha", "banheiro", "lavanderia", "quarto",
    "branco", "preto", "cinza", "rosa", "azul", "verde", "transparente", "inox", "aco", "plastico",
    "silicone", "bambu", "madeira", "conjunto", "jogo", "par", "litros", "ml", "cm", "metros", "m", "w",
}


def normalizar(t):
    t = unicodedata.normalize("NFKD", (t or "").lower()).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]", " ", t)


def bloqueado(titulo):
    n = " " + normalizar(titulo) + " "
    return any(b in n for b in BLOQUEADAS)


# substantivos muito amplos: usamos 2 palavras (ex.: "organizador geladeira" != "organizador gaveta")
AMPLOS = {"organizador", "suporte", "porta", "caixa", "cesto", "escova", "dispenser", "dispensador", "fita",
          "luminaria", "saco", "gancho", "prateleira", "tapete", "capa", "protetor", "pano", "rodo", "copo",
          "garrafa", "cortador", "tampa", "forma", "pote"}


def _singular(w):
    if w.endswith("oes"):
        return w[:-3] + "ao"
    if w.endswith("es") and len(w) > 5 and w[-3] in "rzl":
        return w[:-2]
    if w.endswith("s") and len(w) > 4:
        return w[:-1]
    return w


def tipo(titulo):
    """Tipo do produto, ex.: 'Kit 30 Cabides Veludo' -> 'cabide'; 'Organizadores Geladeira' -> 'organizador geladeira'."""
    ws = [_singular(w) for w in normalizar(titulo).split()
          if not (w.isdigit() or len(w) < 3 or w in GENERICAS or re.match(r"^\d", w))]
    if not ws:
        return normalizar(titulo)[:15]
    return " ".join(ws[:2]) if ws[0] in AMPLOS and len(ws) > 1 else ws[0]


def vendas(info):
    m = re.search(r"([\d.,]+)\s*(mil|M)?\s*vendid", info or "")
    if not m:
        return 0
    n = float(m.group(1).replace(".", "").replace(",", "."))
    return n * (1000 if m.group(2) == "mil" else 1_000_000 if m.group(2) == "M" else 1)
