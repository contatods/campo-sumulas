"""
campo_generator.py — CAMPO v7
Módulo de geração de súmulas HTML. Importado pelo servidor web.
"""

import os, re, base64
from jinja2 import Template


def font_b64(path):
    """Carrega fonte como base64 a partir de um caminho completo."""
    if os.path.exists(path):
        return base64.b64encode(open(path, "rb").read()).decode()
    return ""


def load_fonts(font_dir=None):
    """Localiza e carrega fontes Lato em base64.
    Tenta vários diretórios em ordem: argumento, ./fonts/, sistema."""
    search = []
    if font_dir:
        search.append(font_dir)
    # Pasta local 'fonts/' relativa ao módulo
    here = os.path.dirname(os.path.abspath(__file__))
    search.append(os.path.join(here, "fonts"))
    # Linux
    search.append("/usr/share/fonts/truetype/lato")
    # macOS
    search += [
        os.path.expanduser("~/Library/Fonts"),
        "/Library/Fonts",
        "/System/Library/Fonts",
    ]
    # Windows
    windir = os.environ.get("WINDIR", "C:\\Windows")
    search.append(os.path.join(windir, "Fonts"))

    for d in search:
        if not os.path.isdir(d):
            continue
        b = font_b64(os.path.join(d, "Lato-Black.ttf"))
        if b:
            print(f"  ✓ Fontes carregadas de: {d}")
            return {
                "black": b,
                "bold":  font_b64(os.path.join(d, "Lato-Bold.ttf")),
                "reg":   font_b64(os.path.join(d, "Lato-Regular.ttf")),
                "light": font_b64(os.path.join(d, "Lato-Light.ttf")),
            }
    print("  ⚠  Fontes Lato não encontradas — usando Arial como fallback")
    return {"black": "", "bold": "", "reg": "", "light": ""}


def img_b64(path):
    """Converte imagem local para data URL base64."""
    if path and os.path.exists(path):
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg",
                "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(ext, "image/png")
        return f"data:{mime};base64,{base64.b64encode(open(path, 'rb').read()).decode()}"
    return ""


def sanitize(n):
    """Sanitiza nome para arquivo/pasta — preserva acentos e Unicode.

    Substitui apenas caracteres reservados em filesystem (`/ \\ : * ? " < > |`
    e quebras de linha). Espaços viram underscore. Múltiplos underscores
    são compactados.
    """
    if not n:
        return ""
    s = re.sub(r'[\/\\:*?"<>|\r\n\t]+', "_", str(n))
    s = re.sub(r"\s+", "_", s.strip())
    s = re.sub(r"_+", "_", s)
    return s.strip("_") or "_"



CSS = """
/* ═══════════════════════════════════════════════════════
   CAMPO v7 — tokens
   ink    #0F0F0F  near-black text
   panel  #1A1818  dark background (header, workout zone, score box left)
   dk     #2B2B2B  section banners, sep rows, cum col
   mid    #5A5A5A  secondary text
   ghost  #9A9A9A  labels, refs
   rule   #D0CBC2  warm table rules
   paper  #F8F5F2  alternate row tint
   field  #F4F0E8  writing field background
   w      #FFFFFF  white
   a      #E05C10  orange — score box border + badge + cum col only
   ═══════════════════════════════════════════════════════ */
/* B&W print palette
   Contraste máximo: preto sólido / branco / cinzas bem separados.
   Sem dependência de cor — hierarquia só por valor de luminosidade.
   panel #181818  — painéis escuros (leitura header/workout zone)
   dk    #3A3A3A  — escuro secundário (col acumulado, sep rows)
   mid   #545454  — texto secundário
   ghost #787878  — labels (escuro o suficiente p/ impressão)
   rule  #A0A0A0  — divisores de tabela (visíveis em papel)
   paper #E4E4E4  — linhas alternadas (diferença clara do branco)
   field #F0F0F0  — fundo de campos de preenchimento
   w     #FFFFFF  — branco puro (áreas de escrita) */
:root{
  --ink:   #000000;
  --panel: #181818;
  --dk:    #3A3A3A;
  --mid:   #545454;
  --ghost: #6B6B6B;   /* ratio 5.5:1 sobre branco — WCAG AA confortável (era 4.5 borderline) */
  --text3: #6B6B6B;   /* texto secundário (ratio 5.5:1 sobre branco — AA confortável) */
  --rule:  #A0A0A0;
  --paper: #E4E4E4;
  --field: #F0F0F0;
  --w:     #FFFFFF;
  --a:     #000000;
  --font-body: 'Lato', Arial, sans-serif;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
@page{size:A4;margin:8mm}
body{
  font-family:'Lato',Arial,sans-serif;
  color:var(--ink);background:var(--w);
  font-size:8pt;
  -webkit-print-color-adjust:exact;print-color-adjust:exact;
}
.page{
  width:194mm;
  position:relative;
  display:flex;flex-direction:column;min-height:281mm;
  page-break-after:always;break-after:page;
}
.page:last-child{page-break-after:auto;break-after:auto}
.page-footer{margin-top:auto;}
.ds-credit{
  text-align:center;font-size:5pt;color:#bbb;
  letter-spacing:.1em;margin-top:3mm;
  font-family:var(--font-body);text-transform:uppercase;
}

/* ── A4 MARKER (só na tela, escondido em print/PDF) ── */
@media screen{
  .a4-marker{
    position:absolute;top:281mm;left:-2mm;right:-2mm;height:0;
    border-top:2px dashed rgba(200,0,0,.5);pointer-events:none;z-index:999;
  }
  .a4-marker::after{
    content:'A4';position:absolute;right:0;top:-10px;
    font-size:7px;font-weight:700;color:rgba(200,0,0,.55);
    letter-spacing:.06em;font-family:Arial,sans-serif;
  }
}
@media print{.a4-marker{display:none!important}}

/* ══════════════════════════════════════════════════════
   HEADER — 10mm dark panel
   ══════════════════════════════════════════════════════ */
.hdr{
  height:10mm;background:var(--panel);
  display:flex;align-items:stretch;
  margin-bottom:0;
}
.hdr-logo-col{
  width:22mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  padding:0 2.5mm;
  border-right:1px solid rgba(255,255,255,.07);
}
.hdr-logo{
  max-height:7mm;max-width:18mm;
  width:auto;height:auto;
  object-fit:contain;object-position:center;
  display:block;
}
.hdr-body{
  flex:1;display:flex;flex-direction:column;
  justify-content:center;padding:0 3.5mm;
  border-right:1px solid rgba(255,255,255,.07);
}
.hdr-event{
  font-size:10pt;font-weight:900;color:var(--w);
  letter-spacing:.07em;text-transform:uppercase;line-height:1;
}
.hdr-sep{color:rgba(255,255,255,.5);font-weight:300;margin:0 2mm}
.hdr-cat{
  font-size:5.5pt;font-weight:700;color:rgba(255,255,255,.70);
  letter-spacing:.1em;text-transform:uppercase;margin-top:1mm;
}
.hdr-date-col{
  display:flex;align-items:center;padding:0 3.5mm;flex-shrink:0;
}
.hdr-date{font-size:6pt;color:rgba(255,255,255,.55);letter-spacing:.05em;text-transform:uppercase}
.hdr-cat-credit{
  font-size:4.5pt;font-weight:400;color:rgba(255,255,255,.38);
  letter-spacing:.08em;text-transform:uppercase;margin-top:1.2mm;
}
.hdr-evento-col{
  width:22mm;flex-shrink:0;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:0 2.5mm;
  border-left:1px solid rgba(255,255,255,.07);
  gap:1.5mm;
}
.hdr-evento-logo{
  max-height:7mm;max-width:18mm;
  width:auto;height:auto;
  object-fit:contain;object-position:center;
  display:block;
}
.hdr-evento-date{font-size:5pt;color:rgba(255,255,255,.45);letter-spacing:.05em;text-transform:uppercase;line-height:1}

/* ══════════════════════════════════════════════════════
   PRÉ-WORKOUT ZONE
   Filled by the arbiter BEFORE the workout starts.
   Three rows: athlete name / raia+nº+box / árbitro+bateria
   Orange left border = "fill this first"
   ══════════════════════════════════════════════════════ */
.prekit{
  border:2px solid var(--ink);
  border-left:4px solid var(--ink);
  margin-top:2mm;margin-bottom:0;overflow:hidden;
}
/* PRÉ-WORKOUT header strip */
.pk-header{
  height:5mm;background:var(--panel);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 3mm;
}
.pk-header-t{
  font-size:6pt;font-weight:700;color:var(--w);
  letter-spacing:.18em;text-transform:uppercase;
}
.pk-header-s{
  font-size:4.5pt;font-weight:400;color:rgba(255,255,255,.60);
  letter-spacing:.06em;text-transform:uppercase;
}
.pk-athlete-row{
  height:9mm;background:var(--field);
  border-bottom:1.5px solid var(--rule);
  padding:1mm 3mm 0;display:flex;flex-direction:column;
}
.pk-sub-row{
  display:flex;height:8mm;background:var(--field);
  border-bottom:2.5px solid var(--ink);
}
.pk-ops-row{
  display:flex;height:8mm;background:var(--w);
}
.pk-cell{
  display:flex;flex-direction:column;padding:0.8mm 3mm 0;
}
.pk-cell+.pk-cell{border-left:1px solid var(--rule)}

/* Shared: field label + write line */
.fl{
  font-size:5pt;font-weight:700;color:var(--mid);
  text-transform:uppercase;letter-spacing:.12em;
  flex-shrink:0;line-height:1;
}
.fline{
  border-bottom:1px solid var(--rule);
  margin-top:auto;margin-bottom:1mm;width:100%;
}
.fline-filled{
  font-size:9pt;font-weight:700;color:var(--ink);
  letter-spacing:.03em;padding-bottom:0.5mm;
  border-bottom:none;
}

/* ══════════════════════════════════════════════════════
   WORKOUT ZONE — 16mm dark panel
   Badge (orange) = workout number.
   Time cap right rail = arbiter reference during workout.
   ══════════════════════════════════════════════════════ */
.wkt-zone{
  min-height:11mm;height:auto;background:var(--panel);
  display:flex;align-items:stretch;
  margin-bottom:1.5mm;
  border-top:1px solid rgba(255,255,255,.05);
}
.wkt-badge{
  width:14mm;flex-shrink:0;
  background:var(--w);
  display:flex;align-items:center;justify-content:center;
  font-size:16pt;font-weight:900;color:var(--ink);line-height:1;
}
.wkt-badge-dual{
  width:14mm;flex-shrink:0;
  background:var(--w);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:0;line-height:1;
}
.wkt-badge-dual .bd-num{
  font-size:11pt;font-weight:900;color:var(--ink);line-height:1.1;
}
.wkt-badge-dual .bd-sep{
  font-size:7pt;font-weight:700;color:var(--ghost);letter-spacing:.05em;
}
.sbn-badge{
  width:6mm;height:6mm;background:var(--w);border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  font-size:8pt;font-weight:900;color:var(--ink);flex-shrink:0;
  margin-right:2mm;
}
.wkt-body{
  flex:1;display:flex;flex-direction:column;
  justify-content:center;padding:0 3.5mm;min-width:0;
}
.wkt-name{
  font-size:18pt;font-weight:900;color:var(--w);
  letter-spacing:-.02em;line-height:.95;text-transform:uppercase;
  white-space:normal;overflow-wrap:break-word;
}
.wkt-type{
  display:block;font-size:4.5pt;font-weight:700;
  color:rgba(255,255,255,.65);letter-spacing:.2em;
  text-transform:uppercase;margin-top:1mm;
}
.wkt-tc-rail{
  width:21mm;flex-shrink:0;
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  border-left:1px solid rgba(255,255,255,.15);gap:0.8mm;
}
.wkt-tc-lbl{
  font-size:4.5pt;font-weight:700;
  color:rgba(255,255,255,.70);letter-spacing:.18em;text-transform:uppercase;
}
.wkt-tc-val{
  font-size:12pt;font-weight:900;
  color:rgba(255,255,255,.9);letter-spacing:-.02em;line-height:1;
}

/* ══════════════════════════════════════════════════════
   DESCRIPTION
   ══════════════════════════════════════════════════════ */
.desc{border-left:2px solid var(--rule);padding:1mm 3mm;margin-bottom:1mm}
.dl  {font-size:6.5pt;line-height:1.4;color:var(--mid)}
.dl-t{font-weight:700;color:var(--ink)}
.dl-tc{font-weight:700;font-style:italic}

/* ══════════════════════════════════════════════════════
   MOVEMENT TABLE
   Sequential number: 14pt bold ink — arbiter locates
   position at a glance from a distance.
   Cumulative column: dark bg + orange — scoreboard ref.
   ══════════════════════════════════════════════════════ */
.mov-wrap{border:2px solid var(--ink);overflow:hidden;margin-bottom:0}

.mov-hdr{display:flex;background:var(--panel);height:6mm;align-items:center}
.mh-lbl{width:14mm;flex-shrink:0;border-left:1px solid rgba(255,255,255,.06)}
.mh-mov{
  flex:1;font-size:6pt;font-weight:700;
  color:rgba(255,255,255,.80);padding-left:3mm;
  letter-spacing:.14em;text-transform:uppercase;
}
.mh-reps{
  width:21mm;flex-shrink:0;text-align:center;
  font-size:5.5pt;font-weight:700;color:rgba(255,255,255,.85);
  letter-spacing:.09em;text-transform:uppercase;
  background:var(--dk);
  border-left:1px solid rgba(255,255,255,.12);
  display:flex;align-items:center;justify-content:center;
}
.mh-cum{
  width:14mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:5.5pt;font-weight:700;color:rgba(255,255,255,.50);
  letter-spacing:.12em;text-transform:uppercase;
}

.mov-row{
  display:flex;align-items:stretch;min-height:7mm;
  border-top:1px solid var(--rule);background:var(--w);
}
/* Zebra: usa .mov-row.is-even setada via Jinja (contar só mov-rows reais
   sem incluir secao-row/sep-row/atleta-sep-row no índice). */
.mov-row.is-even{background:var(--paper)}

.mr-lbl{
  width:14mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:4.5pt;font-weight:700;color:var(--ghost);
  letter-spacing:.04em;text-align:center;
  border-left:1px solid var(--rule);padding:1mm;line-height:1.25;
}
.mr-name{
  flex:1;display:flex;align-items:center;
  padding:1mm 2.5mm;font-size:8pt;font-weight:700;color:var(--ink);
  line-height:1.2;text-transform:uppercase;
  border-left:1px solid var(--rule);
  gap:1.5mm;
}
.mr-reps-inline{
  font-size:6.5pt;font-weight:400;color:var(--ghost);
  flex-shrink:0;
}
.mr-carga{
  font-size:6.5pt;font-weight:700;color:var(--mid);
  letter-spacing:.04em;flex-shrink:0;
}
.mr-reps{
  width:21mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  background:var(--dk)!important;
  border-left:1px solid rgba(255,255,255,.12);
  font-size:13pt;font-weight:900;color:var(--w);
}
.mr-cum{
  width:14mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  background:var(--field)!important;
  font-size:10pt;font-weight:700;color:var(--mid);
  letter-spacing:-.02em;line-height:1;
  border-left:1px solid var(--rule);
}

/* Chegada — última linha da tabela, distinta das demais */
.chegada-inline{
  background:var(--ink)!important;
  border-top:2px solid rgba(255,255,255,.15);
}
.chegada-inline .mr-name{
  color:var(--w);letter-spacing:.06em;
  border-left-color:rgba(255,255,255,.12);
}
.chegada-inline .mr-reps-inline{
  color:rgba(255,255,255,.70);
}
.chegada-inline .mr-reps{
  background:var(--panel)!important;
  border-left-color:rgba(255,255,255,.08);
  color:var(--w);
}
.chegada-inline .mr-cum{
  background:rgba(255,255,255,.06)!important;
  color:rgba(255,255,255,.65);
  border-left-color:rgba(255,255,255,.1);
}
.chegada-inline .mr-lbl{
  color:rgba(255,255,255,.65);
  border-left-color:rgba(255,255,255,.1);
}

.sep-row{
  display:flex;align-items:center;justify-content:center;
  height:5mm;background:var(--dk);
}
.sep-txt{
  font-size:6pt;font-weight:700;
  color:rgba(255,255,255,.85);letter-spacing:.22em;text-transform:uppercase;
}

/* Seção informativa: header tipo 'PART 1 (00:00-06:00)'. Não é movimento
   nem 'then...' — é divisão temporal/lógica do workout. Mais prominente
   que .sep-row (banner alto, fundo paper). */
.secao-row{
  display:flex;align-items:center;justify-content:center;
  min-height:7mm;background:var(--paper);
  border-top:1.5px solid var(--ink);border-bottom:1px solid var(--rule);
  padding:1mm 3mm;
}
.secao-txt{
  font-size:8pt;font-weight:900;color:var(--ink);
  letter-spacing:.14em;text-transform:uppercase;
}

/* Tiebreak checkpoint inline (For Time multi-checkpoint): linha escrevível
   após o mov marcado. Sem coluna Reps/Acumulado — só label + linha branca. */
.mov-row-tb{
  display:flex;align-items:center;min-height:6mm;
  background:var(--paper);border-top:1px dashed var(--mid);
}
.mr-tb-lbl{
  flex:0 0 auto;padding:1mm 2.5mm;
  font-size:7pt;font-weight:700;color:var(--ink);
  letter-spacing:.1em;text-transform:uppercase;
  border-left:1px solid var(--rule);
}
.mr-tb-unit{font-size:6pt;font-weight:400;color:var(--ghost);letter-spacing:.04em}
.mr-tb-line{
  flex:1;margin:1mm 3mm 1mm 2mm;
  min-height:4mm;background:var(--w);
  border:1.5px solid var(--ink);border-radius:1.5px;
}

/* Movimentos em paralelo — chave visual P&B safe (símbolo bold + fundo) */
.mov-row-paralelo{background:var(--field)!important}
.mov-row-paralelo .mr-name{position:relative}
.mr-paralelo-mark{
  font-size:11pt;font-weight:900;color:var(--ink);
  line-height:1;flex-shrink:0;margin-right:.5mm;
}
.mov-row-paralelo + .mov-row-paralelo .mr-paralelo-mark::before{
  content:''; /* keep alignment, sem alterar */
}

/* Banner 'Aguardando balizamento': fica logo após o header do workout.
   Visual P&B-safe: borda dupla preta + padrão tracejado nas laterais. */
.aguardando-banner{
  display:flex;align-items:center;gap:3mm;
  margin:0 0 1.5mm 0;padding:2mm 3mm;
  border:1.5px solid var(--ink);
  background:var(--paper);
  background-image:repeating-linear-gradient(45deg,
    transparent 0,transparent 4px,
    var(--rule) 4px,var(--rule) 5px);
}
.aguardando-mark{
  font-size:8pt;font-weight:900;flex-shrink:0;line-height:1;
  background:var(--ink);color:var(--w);
  padding:1mm 2mm;border-radius:2px;letter-spacing:.1em;
}
.aguardando-txt{
  font-size:9pt;font-weight:900;color:var(--ink);
  letter-spacing:.08em;text-transform:uppercase;flex:1;
}
.aguardando-sub{
  font-size:6.5pt;font-weight:400;color:var(--mid);
  letter-spacing:.04em;text-transform:none;display:block;line-height:1.3;
  margin-top:0.5mm;
}

/* Banner Alvo no topo do mov_table — For Time com Goal (Simple Mind/Dim) */
.goal-banner{
  background:var(--ink);color:var(--w);
  padding:2mm 3mm;border:1px solid var(--ink);border-bottom:0;
  font-size:9pt;font-weight:900;letter-spacing:.08em;text-transform:uppercase;
  display:flex;align-items:baseline;gap:3mm;
}
.goal-banner-sub{font-size:6pt;font-weight:400;letter-spacing:.04em;
  text-transform:none;color:rgba(255,255,255,.65);margin-left:auto}
.gb-mark{background:var(--w);color:var(--ink);padding:.6mm 2mm;
  border-radius:2px;font-weight:900;font-size:7.5pt;letter-spacing:.1em}
.gb-target{font-size:11pt;font-weight:900}
.gb-mov{font-size:9pt;font-weight:900}
.gb-carga{font-size:8pt;font-weight:700;color:rgba(255,255,255,.75)}

/* Linha de movimento Goal: tag visual + caixa de reps levemente maior
   pro juiz escrever à caneta sem encostar nas linhas vizinhas. Altura
   próxima das demais linhas pra preservar o ritmo da tabela. */
.mov-row-goal{background:var(--field);min-height:9mm}
.mov-row-goal .mr-reps{padding:1.2mm 1mm}
.mov-row-goal .mr-reps-empty-box{min-height:7mm}
.mr-goal-badge{
  display:inline-block;background:var(--ink);color:var(--w);
  padding:.3mm 1.4mm;border-radius:2px;font-size:6pt;font-weight:900;
  letter-spacing:.08em;margin-right:1.8mm;vertical-align:1px;
}
.mr-cum-dash{text-align:center;color:var(--text3);font-weight:700}

/* Coluna lateral Tiebreak (For Time Goal): célula INTEIRA é a área de
   escrita (sem caixinha aninhada — borda interna come espaço útil).
   Linhas não-âncora: célula vazia, mesmo fundo da row. Linha-âncora:
   fundo branco destacado, indicando claramente onde escrever. */
.mh-tb{
  width:24mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:5.5pt;font-weight:700;color:rgba(255,255,255,.85);
  letter-spacing:.09em;text-transform:uppercase;
  background:var(--dk);
  border-left:1px solid rgba(255,255,255,.12);
}
.mr-tb{
  width:24mm;flex-shrink:0;
  border-left:1px solid var(--rule);
}
/* Célula-âncora do tiebreak (For Time Goal): a célula INTEIRA é a área de
   escrita, com borda inferior pra simular linha-base e microlabel 'm:s' no
   canto superior direito — afordância clara de "escreva um tempo aqui". */
.mr-tb-anchor{
  background:var(--w)!important;position:relative;
  border-bottom:1.5px solid var(--ink);
}
.mr-tb-anchor::after{
  content:'m:s';position:absolute;top:.6mm;right:1.2mm;
  font-size:4.5pt;font-weight:700;color:var(--ghost);letter-spacing:.04em;
}

/* Nota abaixo do score box em For Time Goal: REGRA OFICIAL de cálculo de
   pontuação. Não pode parecer secundário — juiz usa pra ranquear quem não
   finaliza. Faixa lateral + texto preto + peso 700. */
.goal-score-note{
  font-size:7.5pt;font-weight:700;color:var(--ink);
  margin:1.5mm 0 0;padding:1mm 2mm;
  background:var(--field);
  border-left:2px solid var(--ink);
}
.gsn-mark{
  display:inline-block;background:var(--ink);color:var(--w);
  width:3.5mm;height:3.5mm;border-radius:50%;
  font-size:6.5pt;font-weight:900;font-style:normal;
  text-align:center;line-height:3.5mm;margin-right:1mm;
  vertical-align:middle;
}

/* Movimento sem reps prescritas (max snatch etc): caixinhas brancas
   escrevíveis no lugar do número de reps e do acumulado. */
.mr-reps-empty{background:var(--dk)!important;padding:1mm}
.mr-reps-empty-box{
  width:100%;height:100%;background:var(--w);border:1.5px solid var(--w);
  border-radius:1.5px;min-height:5mm;
}
.mr-cum-empty{background:var(--field)!important;padding:1mm}
.mr-cum-empty-box{
  width:100%;height:100%;background:var(--w);border:1.5px solid var(--ink);
  border-radius:1.5px;min-height:5mm;
}

/* Banner family — três variantes (aguardando / goal / relay) compartilham:
   - background var(--ink) ou paper, color contrastante
   - font 900, uppercase, letter-spacing .08em
   - padding 1.5-2mm vertical / 3mm horizontal
   - border var(--ink), bottom 0 quando colado em outro elemento
   Pequenas variações de peso/tamanho são intencionais por hierarquia. */
.relay-note{
  background:var(--ink);color:var(--w);
  padding:1.5mm 3mm;font-size:7.5pt;font-weight:800;
  letter-spacing:.08em;text-transform:uppercase;
  border:1px solid var(--ink);border-bottom:0;
}
/* Separador de bloco por atleta dentro do mov_table. Mostra 'Atleta N' +
   linha pra preencher nome. Não consome cum — só visual. */
.atleta-sep-row{
  display:flex;align-items:center;gap:3mm;
  padding:1.5mm 3mm;background:var(--field);
  border-top:2px solid var(--ink);
}
.atleta-sep-row:first-child{border-top:0}
.atleta-sep-pos{
  font-size:7pt;font-weight:900;color:var(--w);
  background:var(--ink);padding:0.6mm 3mm;border-radius:2px;
  letter-spacing:.08em;text-transform:uppercase;flex-shrink:0;
}
.atleta-sep-nome{flex:1;min-height:5mm;border-bottom:1.5px solid var(--ink)}

/* ══════════════════════════════════════════════════════
   SCORE BOX — dominant post-workout element
   Orange top border announces: "fill this now".
   Left dark panel = label. Right field = large write area.
   ══════════════════════════════════════════════════════ */
/* ══════════════════════════════════════════════════════
   SCORE BOX — horizontal layout with 4 integrated zones:
   [RESULTADO label] [TEMPO field] [REPS field] [TIME CAP]
   ══════════════════════════════════════════════════════ */
.score-box{
  display:flex;
  border:2px solid var(--panel);
  overflow:hidden;
  margin-bottom:1.5mm;
  height:18mm;
}
/* Left dark label */
.sb-lbl-col{
  width:28mm;flex-shrink:0;background:var(--panel);
  display:flex;flex-direction:column;
  align-items:flex-start;justify-content:center;
  padding:0 3mm;
  border-right:1px solid rgba(255,255,255,.08);
}
.sb-lbl-tag{
  font-size:4.5pt;font-weight:700;color:rgba(255,255,255,.65);
  letter-spacing:.28em;text-transform:uppercase;
}
.sb-lbl-name{
  font-size:8.5pt;font-weight:900;color:rgba(255,255,255,.85);
  text-transform:uppercase;margin-top:1mm;letter-spacing:.02em;
}
/* Write fields — branco puro para máximo contraste de escrita manual */
.sb-field{
  display:flex;flex-direction:column;
  background:var(--w);
  padding:2mm 3mm 2.5mm;
  border-right:1px solid var(--rule);
  justify-content:space-between;
}
.sb-field-tempo{flex:2}
.sb-field-reps {flex:1}
.sb-field-tb   {flex:2}
.sb-field-lbl{
  font-size:4.5pt;font-weight:700;color:var(--ghost);
  text-transform:uppercase;letter-spacing:.14em;flex-shrink:0;
}
.sb-field-sub{
  font-size:4pt;font-weight:400;color:var(--ghost);
  text-transform:none;letter-spacing:.02em;
  margin-left:1mm;font-style:italic;
}
.sb-field-line{
  border-bottom:2px solid var(--ink);
  flex:1;margin-top:3mm;
}
/* Right dark time cap */
.sb-tc-col{
  width:28mm;flex-shrink:0;background:var(--panel);
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:1mm;
  border-left:1px solid rgba(255,255,255,.08);
}
.sb-tc-box{
  width:10mm;height:10mm;
  background:var(--w);
  border:1.5px solid var(--mid);
}
.sb-tc-lbl{
  font-size:4.5pt;font-weight:700;color:rgba(255,255,255,.75);
  letter-spacing:.18em;text-transform:uppercase;
}

/* SCORE ANNOUNCE STRIP — substitui acento laranja em B&W */
.score-section{
  height:4.5mm;background:var(--panel);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 3mm;margin-top:1.5mm;margin-bottom:0;
}
.sc-t{font-size:6pt;font-weight:700;color:var(--w);letter-spacing:.18em;text-transform:uppercase}
.sc-s{font-size:4.5pt;font-weight:400;color:rgba(255,255,255,.60);letter-spacing:.06em;text-transform:uppercase}
.sb-tc-sub{font-size:3.5pt;font-weight:700;color:rgba(255,255,255,.55);letter-spacing:.08em;text-transform:uppercase;text-align:center;margin-top:.5mm}

/* EXPRESS score box — same horizontal structure, two write fields */
.score-box-dual{
  display:flex;
  border:2px solid var(--panel);
  overflow:hidden;
  margin-bottom:1.5mm;
  height:16mm;
}
.sb-phase-tag{
  font-size:4pt;font-weight:700;color:rgba(255,255,255,.65);
  letter-spacing:.18em;text-transform:uppercase;
}
.sb-phase-type{
  font-size:7.5pt;font-weight:900;color:rgba(255,255,255,.78);
  text-transform:uppercase;margin-top:0.8mm;
}
.sb-ph-lbl{
  font-size:4.5pt;font-weight:700;color:var(--ghost);
  letter-spacing:.14em;text-transform:uppercase;flex-shrink:0;
}
.sb-ph-line{flex:1;border-bottom:2px solid var(--ink);margin-top:2mm}

/* ══════════════════════════════════════════════════════
   AMRAP SCORECARD (unchanged from v6)
   ══════════════════════════════════════════════════════ */
.amrap-wrap{border:2px solid var(--ink);overflow:hidden;margin-bottom:0}
.amrap-hdr{display:flex;align-items:center;background:var(--panel);height:6mm}
.amrap-subhdr{display:flex;align-items:stretch;background:var(--paper);min-height:4.5mm;height:auto;border-bottom:1px solid var(--rule)}
.amrap-row{
  display:flex;align-items:stretch;min-height:7mm;
  border-top:1px solid var(--rule);background:var(--w);
}
.amrap-row:nth-child(even){background:var(--paper)}
.rplus-row{opacity:.6}
.ar-round{flex-shrink:0;display:flex;align-items:center;justify-content:center}
.ar-mov{flex:1;display:flex;align-items:stretch;border-left:1px solid var(--rule)}
.ar-mov-cell{flex:1;display:flex;align-items:center;justify-content:center;border-right:1px solid var(--rule)}
.ar-write{
  width:calc(100% - 2.5mm);height:calc(100% - 2.5mm);margin:1.25mm;
  border:1px solid var(--rule);background:var(--w);
  display:flex;align-items:flex-start;padding:1mm;
}
.ar-ref{font-size:6.5pt;font-weight:700;color:var(--rule)}
.ar-ref-lbl{font-size:5pt;color:var(--rule);display:block;line-height:1.2}
.ar-reps-cell{flex-shrink:0;display:flex;align-items:stretch;border-left:1px solid var(--rule)}
.ar-reps-inner{display:flex;align-items:center;justify-content:center;width:100%}
.ar-write-strong{
  width:calc(100% - 2.5mm);height:calc(100% - 2.5mm);margin:1.25mm;
  border:1px solid var(--mid);background:var(--w);
  display:flex;align-items:flex-start;padding:1mm;
}
.ar-cum-cell{
  flex-shrink:0;display:flex;align-items:stretch;
  background:var(--dk)!important;border-left:none;
}
.ar-cum-inner{display:flex;align-items:center;justify-content:center;width:100%}
/* Campo escrevível branco DENTRO da célula escura — juiz precisa enxergar o
   que escreve a caneta. Antes era transparente sobre fundo dark = ilegível. */
.ar-write-cum{
  width:calc(100% - 2.5mm);height:calc(100% - 2.5mm);margin:1.25mm;
  border:1px solid var(--w);
  background:var(--w);
  display:flex;align-items:flex-start;padding:1mm;border-radius:1.5px;
}
.ar-ref-sb{font-size:6.5pt;font-weight:700;color:var(--mid)}
.ar-ref-sb-lbl{font-size:5pt;color:var(--ghost);display:block;line-height:1.2}
.ar-tb-cell{
  flex-shrink:0;display:flex;align-items:stretch;
  background:var(--field)!important;
  border-left:1.5px solid var(--ink);
}
.ar-tb-inner{
  width:100%;display:flex;align-items:flex-start;justify-content:flex-start;
  padding:1.25mm;
}
.ar-tb-ref{font-size:6.5pt;font-weight:400;color:var(--ghost)}
/* Progressão de reps — destaques P&B safe (bold, fundo cinza, símbolos) */
.ah-ref-prog{font-weight:700!important;color:rgba(255,255,255,.92)!important;
  background:rgba(255,255,255,.12);padding:0.5mm 2mm;border-radius:2px;
  border:1px solid rgba(255,255,255,.25)}
.ash-prog{background:var(--field);border-top:1.5px solid var(--ink)!important;
  border-bottom:1.5px solid var(--ink)!important}
.ash-prog-mark{font-size:5pt;color:var(--ink);margin-left:.5mm;vertical-align:super;font-weight:900}
.ash-prog-seq{font-size:6pt;font-weight:900;color:var(--ink);
  letter-spacing:.06em;line-height:1.1;
  text-decoration:underline;text-underline-offset:1.5px}
.ar-ref-prog{color:var(--ink)!important;font-weight:900!important;
  text-decoration:underline;text-underline-offset:1.5px}
/* Última round MAX — destaque visual P&B safe (caixa borda dupla preta) */
.ar-cum-cell-max{outline:1.5px solid var(--w);outline-offset:-2px}
.ar-ref-max{font-weight:900!important;font-size:7pt!important;
  letter-spacing:.04em;text-transform:uppercase}
.ah-n{flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:10pt;font-weight:900;color:rgba(255,255,255,.12)}
.ah-title{flex:1;font-size:7pt;font-weight:700;color:rgba(255,255,255,.7);padding-left:3mm;letter-spacing:.12em;text-transform:uppercase;display:flex;align-items:center;border-left:1px solid rgba(255,255,255,.07)}
.ah-x{margin:0 .8mm;color:rgba(255,255,255,.45);font-weight:400}
.ah-total{margin-left:2mm;color:rgba(255,255,255,.45);font-weight:400;
  font-size:6.5pt;letter-spacing:.04em;text-transform:none}
.ah-ref{font-size:7pt;font-weight:300;color:rgba(255,255,255,.60);display:flex;align-items:center;padding-right:3mm}
.ash{display:flex;align-items:center;justify-content:center;
  font-size:4.5pt;font-weight:700;color:var(--mid);letter-spacing:.05em;
  text-transform:uppercase;text-align:center;white-space:normal;line-height:1.25;
  padding:1mm 1.5mm}
/* Nome do movimento — destaque (maior, mais escuro). Reps + carga inline. */
.ash-nome{font-size:7pt;font-weight:900;color:var(--ink);letter-spacing:.03em;
  line-height:1.2}
.ash-reps{font-size:6.5pt;font-weight:700;color:var(--mid);margin-right:.3mm}
.ash-carga{font-size:6pt;font-weight:700;color:var(--mid);letter-spacing:.04em}
.ash-cum{background:var(--dk)!important;border-left:none;color:rgba(255,255,255,.75)!important}

/* ══════════════════════════════════════════════════════
   EXPRESS SECTION BANNERS
   ══════════════════════════════════════════════════════ */
.section-banner{
  background:var(--dk);height:5.5mm;
  display:flex;align-items:center;padding:0 3mm;
  margin-bottom:1.5mm;justify-content:space-between;
}
.sbn-t{font-size:7pt;font-weight:900;color:var(--w);letter-spacing:.1em;text-transform:uppercase}
.sbn-s{font-size:5.5pt;font-weight:300;color:rgba(255,255,255,.70);letter-spacing:.04em}
.rest-bar{
  background:var(--paper);height:3.5mm;
  display:flex;align-items:center;justify-content:center;
  margin:1mm 0;
  border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
  font-size:6pt;font-weight:700;color:var(--ghost);
  letter-spacing:.12em;text-transform:uppercase;
}

/* ══════════════════════════════════════════════════════
   SIGNATURES
   ══════════════════════════════════════════════════════ */
.sign-zone{display:flex;gap:2mm;margin-top:3mm;margin-bottom:1mm}
.sign-cell{
  border:1.5px solid var(--ink);height:10mm;
  padding:1.5mm 3mm 0;display:flex;flex-direction:column;
}
.sign-wide  {flex:0 0 calc(60% - 1mm)}
.sign-narrow{flex:1}
.no-rasure{
  text-align:center;font-size:5.5pt;color:var(--mid);
  margin-bottom:1.5mm;letter-spacing:.07em;text-transform:uppercase;
}

/* ══════════════════════════════════════════════════════
   OBSERVATIONS
   ══════════════════════════════════════════════════════ */
.obs-box{
  border:1.5px solid var(--ink);
  padding:1.5mm 3mm;display:flex;flex-direction:column;
  min-height:24mm;
}
.obs-lbl{font-size:5pt;font-weight:700;color:var(--ghost);letter-spacing:.13em;text-transform:uppercase;margin-bottom:1mm}
.obs-lines{flex:1;display:flex;flex-direction:column;justify-content:space-evenly}
.obs-line{border-bottom:1px solid var(--rule);min-height:3.5mm}

/* ── FOR LOAD ── régua de anilhas + barra desenhada + carga + validade ── */
.fl-zone{border:2px solid var(--ink);margin-bottom:0}
.fl-zone-hdr{display:flex;align-items:center;justify-content:space-between;
  background:var(--panel);color:var(--w);padding:1.5mm 3mm;min-height:8mm;gap:3mm}
.fl-zone-t{font-weight:900;font-size:13pt;letter-spacing:.06em;text-transform:uppercase}
.fl-zone-meta{font-size:9.5pt;font-weight:600;color:#DDD;text-align:right}
.fl-instrucao{padding:1.5mm 3mm;background:var(--paper);font-size:8.5pt;
  color:var(--mid);font-style:italic;border-bottom:1px solid var(--rule);line-height:1.4}
/* Cada tentativa = 2 linhas: top (régua + barra + régua) + bottom (carga + validade + obs) */
.fl-row{display:flex;flex-direction:column;border-top:1px solid var(--rule);
  background:var(--w);padding:1.5mm 0}
.fl-row-alt{background:var(--paper)}
.fl-row-top{display:flex;align-items:center;padding:0 2mm;gap:0}
.fl-row-bottom{display:flex;align-items:center;padding:1.5mm 2mm 0 2mm;gap:4mm}
.fl-row-hdr{width:9mm;display:flex;align-items:center;justify-content:center;
  font-weight:900;font-size:12pt;color:var(--w);background:var(--dk);
  border-radius:2px;padding:1mm 0;align-self:stretch}
.fl-anilhas{display:flex;align-items:center}
.fl-anilha{width:7.5mm;height:7.5mm;border:1px solid var(--ink);
  display:flex;align-items:center;justify-content:center;background:var(--w);
  border-right:none}
.fl-anilha:last-child{border-right:1px solid var(--ink)}
.fl-anilha span{font-size:8pt;font-weight:700;color:var(--ink);pointer-events:none;
  line-height:1}
/* Barra desenhada: caixa preta com peso em branco — mais marcante que traço fino.
   Comunica "barra" como objeto, não como divisor. */
.fl-barra{display:flex;align-items:center;justify-content:center;
  min-width:18mm;height:7.5mm;background:var(--ink);color:var(--w);
  font-size:9pt;font-weight:900;letter-spacing:.02em;margin:0 0.5mm;
  border-radius:1.5mm}
/* Carga + unidade inline */
.fl-carga{display:flex;align-items:center;gap:2mm;flex:1;min-width:42mm}
.fl-carga-lbl{font-size:9pt;font-weight:700;color:var(--ink);
  text-transform:uppercase;letter-spacing:.04em;flex-shrink:0}
.fl-carga-line{flex:1;min-height:7mm;border:1.5px solid var(--ink);
  background:var(--w);border-radius:1.5px}
.fl-carga-unidade{font-size:10pt;font-weight:900;color:var(--ink);flex-shrink:0}
/* Validade: caixas com label VÁLIDA / NO-REP — claro pro árbitro */
.fl-val{display:flex;align-items:center;gap:4mm;flex-shrink:0}
.fl-val-opt{display:flex;align-items:center;gap:1.5mm}
.fl-val-box{width:7mm;height:7mm;border:1.8px solid var(--ink);
  background:var(--w);border-radius:1px;flex-shrink:0}
.fl-val-lbl{font-size:8.5pt;font-weight:800;color:var(--ink);letter-spacing:.04em;
  text-transform:uppercase}
/* NO-REP: invertido (fundo preto, texto branco) — P&B safe, imprime
   distinguível em impressora monocromática. Antes era vermelho #A03020. */
.fl-val-lbl.nr{
  background:var(--ink);color:var(--w);
  padding:.4mm 1.6mm;border-radius:2px;letter-spacing:.06em;
}
/* Observações curtas por tentativa (opcional) */
.fl-obs{display:flex;align-items:center;gap:2mm;flex:1;min-width:50mm}
.fl-obs-lbl{font-size:7.5pt;font-weight:700;color:var(--ghost);
  text-transform:uppercase;letter-spacing:.04em;flex-shrink:0}
.fl-obs-line{flex:1;border-bottom:1px solid var(--rule);min-height:5mm}
/* MELHOR CARGA com referência à tentativa */
.fl-melhor{display:flex;align-items:center;border-top:2px solid var(--ink);
  background:var(--dk);color:var(--w);padding:2.5mm 3mm;gap:3mm}
.fl-melhor-lbl{font-size:10pt;font-weight:900;letter-spacing:.06em;
  text-transform:uppercase}
.fl-melhor-line{flex:1;min-height:7mm;background:transparent;
  border-bottom:1.5px solid var(--w)}
.fl-melhor-unidade{font-size:10pt;font-weight:700}
.fl-melhor-ref{display:flex;align-items:center;gap:1.5mm;font-size:8.5pt;
  font-weight:600;color:#DDD;letter-spacing:.04em}
.fl-melhor-ref-box{width:8mm;height:6.5mm;border:1.5px solid var(--w);
  background:transparent}

/* ── For Load COMPACT — pra 5+ tentativas (cabe em A4 sem estourar) ──
   Estratégia: 1 linha por tentativa (em vez de 2), padding/fonts
   menores, esconde instrução e coluna Obs. Mantém anilhas + barra +
   carga + validade — info essencial pro árbitro. */
.fl-zone-compact .fl-instrucao{display:none}
.fl-zone-compact .fl-row{flex-direction:row;align-items:center;padding:1mm 2mm;
  gap:3mm;min-height:0}
.fl-zone-compact .fl-row-top{padding:0;gap:0;flex:0 0 auto}
.fl-zone-compact .fl-row-bottom{padding:0;gap:3mm;flex:1}
.fl-zone-compact .fl-row-hdr{width:8mm;font-size:10pt;padding:0.5mm 0}
.fl-zone-compact .fl-anilha{width:6mm;height:6mm}
.fl-zone-compact .fl-anilha span{font-size:7pt}
.fl-zone-compact .fl-barra{min-width:14mm;height:6mm;font-size:7.5pt}
/* Quando há muitas anilhas (libras tem 8), reduz pra caber em A4 sem overflow */
.fl-zone-compact.fl-zone-muitas-anilhas .fl-anilha{width:5mm;height:5.5mm}
.fl-zone-compact.fl-zone-muitas-anilhas .fl-anilha span{font-size:6.5pt}
.fl-zone-compact.fl-zone-muitas-anilhas .fl-barra{min-width:12mm;height:5.5mm;font-size:7pt}
.fl-zone-compact.fl-zone-muitas-anilhas .fl-carga{min-width:30mm}
.fl-zone-compact.fl-zone-muitas-anilhas .fl-val{gap:2mm}
/* Mesmo no expandido, 8+ anilhas reduzem pra evitar overflow */
.fl-zone-muitas-anilhas:not(.fl-zone-compact) .fl-anilha{width:6.5mm;height:6.5mm}
.fl-zone-muitas-anilhas:not(.fl-zone-compact) .fl-anilha span{font-size:7.5pt}

/* ── For Load TEAM (dupla/trio/quarteto/time) — sub-blocos por atleta ── */
.fl-zone-team .fl-atleta-bloco{border-top:2px solid var(--ink);padding:1mm 2mm 0.5mm}
.fl-zone-team .fl-atleta-bloco:first-of-type{border-top:1px solid var(--rule)}
.fl-zone-team .fl-atleta-hdr{display:flex;align-items:center;gap:2.5mm;
  margin-bottom:1mm;padding:0 1mm}
.fl-zone-team .fl-atleta-pos{font-weight:900;font-size:9.5pt;color:var(--ink);
  background:var(--paper);padding:0.5mm 2.5mm;border-radius:2px;flex-shrink:0;
  letter-spacing:.04em;text-transform:uppercase}
.fl-zone-team .fl-atleta-nome-line{flex:1;border-bottom:1.5px solid var(--ink);
  min-height:5mm;min-width:30mm}
.fl-zone-team .fl-atleta-genero{font-size:7.5pt;font-weight:700;color:var(--mid);
  letter-spacing:.04em}
/* Melhor Carga inline no header — economiza 1 row por atleta */
.fl-zone-team .fl-atleta-melhor-inline{display:flex;align-items:center;gap:2mm;
  flex:0 0 auto;min-width:62mm}
.fl-zone-team .fl-atleta-melhor-lbl{font-size:7.5pt;font-weight:700;
  color:var(--ink);text-transform:uppercase;letter-spacing:.04em;flex-shrink:0}
.fl-zone-team .fl-atleta-melhor-line{flex:1;min-height:5mm;min-width:25mm;
  border:1.5px solid var(--ink);background:var(--field);border-radius:1.5px}
.fl-zone-team .fl-atleta-melhor-unidade{font-size:8.5pt;font-weight:900;flex-shrink:0}
.fl-zone-team .fl-soma-time{background:var(--ink);color:var(--w);
  border-top:3px double var(--w);padding:2.5mm}
/* Campo branco e escrevível dentro do bloco escuro */
.fl-zone-team .fl-soma-time .fl-melhor-line{background:var(--w);
  border:1.5px solid var(--w);min-height:7mm;border-radius:2px}
.fl-zone-team .fl-soma-time .fl-melhor-unidade{color:var(--w)}
/* Em team, esconde campo "Obs" por tentativa (juiz registra obs no fim, não por tents) */
.fl-zone-team .fl-obs{display:none}

/* Sequência — só buy-in (opcional) + complex. Lembrete pro árbitro. */
.fl-sequencia{display:flex;flex-direction:column;gap:0.8mm;
  padding:1.5mm 3mm;background:var(--field);border-bottom:1px solid var(--rule)}
.fl-sequencia-item{display:flex;align-items:center;gap:2.5mm}
.fl-sequencia-tag{font-size:6pt;font-weight:900;color:var(--w);
  background:var(--ink);padding:.7mm 2mm;border-radius:2px;
  letter-spacing:.12em;text-transform:uppercase;flex-shrink:0;min-width:14mm;
  text-align:center}
.fl-sequencia-tag-buyin{background:var(--mid)}
.fl-sequencia-text{font-size:9pt;font-weight:900;color:var(--ink);
  letter-spacing:.02em;text-transform:uppercase;line-height:1.2}
.fl-sequencia-text-buyin{color:var(--mid)}
.fl-zone-compact .fl-sequencia{padding:1mm 3mm}
.fl-zone-compact .fl-sequencia-text{font-size:8pt}
.fl-zone-super-compact .fl-sequencia{padding:0.7mm 2.5mm}
.fl-zone-super-compact .fl-sequencia-text{font-size:7.5pt}

/* SUPER-COMPACT (quarteto: 4 atletas × 3 tents = 12 linhas em A4) */
.fl-zone-super-compact .fl-atleta-bloco{padding:0.8mm 2mm 0.3mm}
.fl-zone-super-compact .fl-atleta-hdr{margin-bottom:0.5mm;gap:2mm}
.fl-zone-super-compact .fl-atleta-pos{font-size:8.5pt;padding:0.3mm 2mm}
.fl-zone-super-compact .fl-atleta-nome-line{min-height:4mm;min-width:24mm}
.fl-zone-super-compact .fl-atleta-melhor-inline{min-width:50mm}
.fl-zone-super-compact .fl-atleta-melhor-line{min-height:4mm;min-width:20mm}
.fl-zone-super-compact .fl-atleta-melhor-lbl{font-size:7pt}
.fl-zone-super-compact .fl-row{padding:0.5mm 2mm}
.fl-zone-super-compact .fl-anilha{width:5mm;height:5mm}
.fl-zone-super-compact .fl-anilha span{font-size:6pt}
.fl-zone-super-compact .fl-row-hdr{width:7mm;font-size:8.5pt;padding:0}
.fl-zone-super-compact .fl-barra{min-width:11mm;height:5mm;font-size:6.5pt}
.fl-zone-super-compact .fl-carga{min-width:28mm}
.fl-zone-super-compact .fl-carga-lbl{font-size:7pt}
.fl-zone-super-compact .fl-carga-line{min-height:4.5mm}
.fl-zone-super-compact .fl-val-box{width:4.5mm;height:4.5mm}
.fl-zone-super-compact .fl-val-lbl{font-size:6.5pt}
.fl-zone-super-compact .fl-val{gap:2mm}
.fl-zone-super-compact .fl-zone-hdr{min-height:5.5mm;padding:0.5mm 3mm}
.fl-zone-super-compact .fl-zone-t{font-size:10pt}
.fl-zone-super-compact .fl-zone-meta{font-size:7.5pt}
.fl-zone-super-compact .fl-soma-time{padding:1.5mm 3mm}
.fl-zone-super-compact .fl-melhor-lbl{font-size:8.5pt}
.fl-zone-super-compact .fl-melhor-line{min-height:5mm}
.fl-zone-compact .fl-carga{min-width:34mm}
.fl-zone-compact .fl-carga-lbl{font-size:8pt}
.fl-zone-compact .fl-carga-line{min-height:5.5mm}
.fl-zone-compact .fl-carga-unidade{font-size:8.5pt}
.fl-zone-compact .fl-val{gap:3mm}
.fl-zone-compact .fl-val-box{width:5.5mm;height:5.5mm}
.fl-zone-compact .fl-val-lbl{font-size:7.5pt}
.fl-zone-compact .fl-obs{display:none}
.fl-zone-compact .fl-zone-hdr{min-height:7mm;padding:1mm 3mm}
.fl-zone-compact .fl-zone-t{font-size:11.5pt}
.fl-zone-compact .fl-zone-meta{font-size:8.5pt}
.fl-zone-compact .fl-melhor{padding:1.5mm 3mm}
.fl-zone-compact .fl-melhor-lbl{font-size:9.5pt}
.fl-zone-compact .fl-melhor-line{min-height:5.5mm}
.fl-team-atleta{display:flex;align-items:center;border-top:1px solid var(--rule);
  padding:3mm;gap:4mm;background:var(--w)}
.fl-team-info{flex:1;display:flex;align-items:center;gap:3mm;min-width:0}
.fl-team-num{font-weight:900;font-size:11pt;color:var(--ghost);min-width:14mm}
.fl-team-nome{font-weight:700;font-size:10pt;color:var(--ink);overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.fl-team-box{font-size:8pt;color:var(--mid);font-style:italic}
.fl-team-carga{display:flex;align-items:center;gap:2mm;flex-shrink:0;min-width:55mm}
.fl-team-carga-lbl{font-size:8pt;font-weight:700;color:var(--ghost);text-transform:uppercase}
.fl-team-carga-line{flex:1;min-height:6mm;border-bottom:1.5px solid var(--ink);
  background:var(--field);min-width:30mm}
.fl-team-unidade{font-size:9pt;font-weight:700;color:var(--ink)}

@media print{
  body{margin:0}
  .a4-marker{display:none!important}
  .mov-wrap,.prekit,.score-box,.score-box-dual,.sign-zone,.obs-box,.amrap-wrap,.fl-zone{page-break-inside:avoid}
  /* goal-score-note: regra oficial — não pode quebrar do score-box que ela
     interpreta. break-before:avoid força colagem na página anterior. */
  .goal-score-note{page-break-inside:avoid;break-before:avoid;page-break-before:avoid}
}
"""


MOV_TABLE_MACRO = r"""
{% macro mov_table(movimentos, num, goal_reps=0, hide_cum=false, tb_col=false) %}
{% set has_lbl = movimentos | selectattr('label','defined') | selectattr('label') | list | length > 0 %}
<div class="mov-wrap">
  <div class="mov-hdr">
    {% if has_lbl %}<div class="mh-lbl"></div>{% endif %}
    <div class="mh-mov">Movimentos</div>
    <div class="mh-reps">Reps</div>
    {% if not hide_cum %}<div class="mh-cum">Acumulado</div>{% endif %}
    {% if tb_col %}<div class="mh-tb">Tiebreak</div>{% endif %}
  </div>
  {# row_idx conta só linhas de movimento (chegada/goal/default) — não conta
     secao-row, sep-row, atleta-sep-row, round-header. Garante zebra correta. #}
  {% set ns = namespace(cum=0, row_idx=0) %}
  {% for mov in movimentos %}
    {% if mov.atleta_header is defined %}
      <div class="atleta-sep-row">
        <span class="atleta-sep-pos">Atleta {{ mov.atleta_header }}</span>
        <div class="atleta-sep-nome"></div>
      </div>
    {% elif mov.round_header is defined %}
      {# Header 'Round N' antes de cada repetição em 'N rounds for time'.
         Reusa visual do atleta_header (banner com badge + linha pra tempo) — pode
         servir pra juiz anotar split time do round. #}
      <div class="atleta-sep-row">
        <span class="atleta-sep-pos">Round {{ mov.round_header }}</span>
        <div class="atleta-sep-nome"></div>
      </div>
    {% elif mov.separador is defined and mov.separador %}
      <div class="sep-row"><span class="sep-txt">{{ mov.separador | upper }}</span></div>
    {% elif mov.secao is defined and mov.secao %}
      <div class="secao-row"><span class="secao-txt">{{ mov.secao | upper }}</span></div>
    {% elif mov.chegada is defined and mov.chegada %}
      {# Acumulado final: soma goal_reps (Simple Mind/Dim) + 1 (rep chegada).
         Para 'N rounds for time', mov_table já recebe a lista expandida com
         N repetições — ns.cum naturalmente acumula a soma total. #}
      {% set ns.cum = ns.cum + (goal_reps or 0) + 1 %}
      {% set ns.row_idx = ns.row_idx + 1 %}
      <div class="mov-row chegada-inline">
        {% if has_lbl %}<div class="mr-lbl">—</div>{% endif %}
        <div class="mr-name">
          <span class="mr-reps-inline">(1)</span>CHEGADA
        </div>
        <div class="mr-reps">1</div>
        {% if not hide_cum %}<div class="mr-cum">{{ ns.cum }}</div>{% endif %}
        {% if tb_col %}<div class="mr-tb"></div>{% endif %}
      </div>
    {% elif mov.goal %}
      {# Linha do movimento alvo (goal): badge + nome + carga, com caixa
         branca de reps ATIVA — juiz conta reps daquela PART durante o
         workout. Total agregado das PARTs também vai no score box do rodapé. #}
      {% set ns.row_idx = ns.row_idx + 1 %}
      <div class="mov-row mov-row-goal">
        {% if has_lbl %}<div class="mr-lbl">{{ mov.label | default('') }}</div>{% endif %}
        <div class="mr-name">
          <span class="mr-goal-badge">GOAL</span>{{ mov.nome }}{% if mov.carga %} <span class="mr-carga">({{ mov.carga }})</span>{% endif %}
        </div>
        <div class="mr-reps mr-reps-empty"><div class="mr-reps-empty-box"></div></div>
        {% if not hide_cum %}<div class="mr-cum mr-cum-dash">—</div>{% endif %}
        {% if tb_col %}<div class="mr-tb{% if mov.tiebreak_aqui %} mr-tb-anchor{% endif %}"></div>{% endif %}
      </div>
    {% else %}
      {% set ns.cum = ns.cum + (mov.reps | default(0)) %}
      {% set ns.row_idx = ns.row_idx + 1 %}
      <div class="mov-row{% if ns.row_idx is divisibleby 2 %} is-even{% endif %}{% if mov.paralelo %} mov-row-paralelo{% endif %}{% if mov.reps is not defined %} mov-row-flex{% endif %}">
        {% if has_lbl %}<div class="mr-lbl">{{ mov.label | default('') }}</div>{% endif %}
        <div class="mr-name">
          {% if mov.paralelo %}<span class="mr-paralelo-mark" title="Executado em paralelo">‖</span>{% endif %}
          {% if mov.reps is defined %}<span class="mr-reps-inline">({{ mov.reps }})</span>{% endif %}{{ mov.nome }}{% if mov.carga %} <span class="mr-carga">({{ mov.carga }})</span>{% endif %}
        </div>
        {% if mov.reps is defined %}
          <div class="mr-reps">{{ mov.reps }}</div>
          {% if not hide_cum %}<div class="mr-cum">{{ ns.cum }}</div>{% endif %}
        {% else %}
          {# Movimento sem reps prescritos (ex: max snatch com Goal):
             juiz preenche reps na caixinha branca. Cumulativo idem. #}
          <div class="mr-reps mr-reps-empty"><div class="mr-reps-empty-box"></div></div>
          {% if not hide_cum %}<div class="mr-cum mr-cum-empty"><div class="mr-cum-empty-box"></div></div>{% endif %}
        {% endif %}
        {% if tb_col %}<div class="mr-tb{% if mov.tiebreak_aqui %} mr-tb-anchor{% endif %}"></div>{% endif %}
      </div>
      {# Checkpoint de tiebreak inline (AMRAP/EMOM): linha extra abaixo do
         mov com label + caixa branca larga. For Time Goal usa coluna lateral
         dedicada (renderizada inline em cada mov-row, ver tb_col acima). #}
      {% if mov.tiebreak %}
      <div class="mov-row mov-row-tb">
        {% if has_lbl %}<div class="mr-lbl">—</div>{% endif %}
        <div class="mr-name mr-tb-lbl">Tiebreak <span class="mr-tb-unit">(m:s)</span></div>
        <div class="mr-tb-line"></div>
      </div>
      {% endif %}
    {% endif %}
  {% endfor %}
</div>
{% endmacro %}

{# Macro mov_table_relay foi removido em v1.21.5 — Spin agora renderiza
   atleta_header inline em mov_table (uma tabela só com cum cumulativo). #}
"""

AMRAP_TABLE_MACRO = r"""
{% macro amrap_table(movimentos, num, n_rounds, wkt=none) %}
{% set data_movs = movimentos | rejectattr('separador','defined') | rejectattr('chegada','defined') | list %}
{% set is_emom = wkt is not none and wkt.emom_janela %}
{% set has_tb = wkt is not none and wkt.tiebreak_por_round %}
{% set _n_rounds = wkt.emom_rounds if is_emom else n_rounds %}
{% set show_rplus = not is_emom %}
{% set has_progressao = data_movs | selectattr('reps_por_round','defined') | list | length > 0 %}
{% set delta = (wkt.reps_delta_por_round if wkt is not none else 0) | default(0) %}
{% set reps_round = data_movs | map(attribute='reps') | list | sum %}
{# Calcula tempo total EMOM (ex: 2:30 × 5 = 12:30) — info útil pro juiz. #}
{% set tempo_total = '' %}
{% if is_emom and wkt.emom_janela %}
  {% set partes = wkt.emom_janela.split(':') %}
  {% if partes | length == 2 %}
    {% set s_total = (partes[0]|int * 60 + partes[1]|int) * wkt.emom_rounds %}
    {% set tempo_total = '%d:%02d' | format(s_total // 60, s_total % 60) %}
  {% endif %}
{% endif %}
{% set rnd_w='14mm' %}{% set cum_w='16mm' %}{% set tb_w='18mm' %}
<div class="amrap-wrap">
  <div class="amrap-hdr">
    <div class="ah-n" style="width:{{rnd_w}}">{{ num }}</div>
    {% if is_emom %}
      <div class="ah-title">EMOM {{ wkt.emom_janela }} <span class="ah-x">×</span> {{ wkt.emom_rounds }} rounds{% if tempo_total %} <span class="ah-total">= {{ tempo_total }} total</span>{% endif %}</div>
    {% else %}
      <div class="ah-title">Scorecard AMRAP</div>
    {% endif %}
    {% if has_progressao %}
      <div class="ah-ref ah-ref-prog">+{{ delta }} reps/round{% if wkt.ultimo_round_max %} · último MAX{% endif %}</div>
    {% else %}
      <div class="ah-ref">{{ reps_round }} reps / round</div>
    {% endif %}
  </div>
  <div class="amrap-subhdr">
    <div class="ash" style="width:{{rnd_w}}">Round</div>
    {% for m in data_movs %}
      {# Limpa o nome: remove parênteses com qty de atletas (ex: '(2 ATHLETES)') #}
      {% set nc = m.nome.split('(')[0].strip() %}
      <div class="ash{% if m.reps_por_round %} ash-prog{% endif %}" style="flex:1;border-left:1px solid var(--rule)">
        <span class="ash-nome">
          {% if m.reps_por_round %}
            <span class="ash-prog-seq" title="Reps progridem por round">({{ m.reps_por_round | join(' · ') }})</span>
          {% else %}
            <span class="ash-reps">({{ m.reps }})</span>
          {% endif %}
          {{ nc }}{% if m.carga %} <span class="ash-carga">({{ m.carga }})</span>{% endif %}
        </span>
      </div>
    {% endfor %}
    <div class="ash ash-cum" style="width:{{cum_w}};border-left:1px solid var(--rule)">Acumulado</div>
    {% if has_tb %}<div class="ash ash-tb" style="width:{{tb_w}};border-left:1px solid var(--rule)">Tie-break<br>(m:s)</div>{% endif %}
  </div>
  {% set ns = namespace(cum=0) %}
  {% set total_rows = _n_rounds + (1 if show_rplus else 0) %}
  {% for ri in range(total_rows) %}
    {% set ip = (show_rplus and ri == _n_rounds) %}
    {% set rl = 'R+' if ip else (ri+1)|string %}
    {# Reps por round (com progressão se houver) — usado pra ref e pra somar.
       Quando algum mov tem 'MAX' no round, ref do total fica indeterminado. #}
    {% set ns_rps = namespace(sum=0, vals=[], tem_max=false) %}
    {% for m in data_movs %}
      {% set r = m.reps_por_round[ri] if (m.reps_por_round and ri < m.reps_por_round|length) else m.reps %}
      {% set ns_rps.vals = ns_rps.vals + [r] %}
      {% if r is integer %}
        {% set ns_rps.sum = ns_rps.sum + r %}
      {% else %}
        {% set ns_rps.tem_max = true %}
      {% endif %}
    {% endfor %}
    <div class="amrap-row {% if ip %}rplus-row{% endif %}">
      <div class="ar-round" style="width:{{rnd_w}};border-right:1px solid var(--rule)">
        <span style="font-weight:900;font-size:{% if ip %}7{% else %}9{% endif %}pt;color:{% if ip %}var(--ghost){% else %}var(--mid){% endif %}">{{ rl }}</span>
      </div>
      <div class="ar-mov">
        {% for m in data_movs %}
        <div class="ar-mov-cell">
          <div class="ar-write">
            {% if not ip %}<span class="ar-ref{% if m.reps_por_round %} ar-ref-prog{% endif %}"><span class="ar-ref-lbl">ref</span>{{ ns_rps.vals[loop.index0] }}</span>{% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
      {% if not ip and not ns_rps.tem_max %}{% set ns.cum = ns.cum + ns_rps.sum %}{% endif %}
      <div class="ar-cum-cell{% if ns_rps.tem_max %} ar-cum-cell-max{% endif %}" style="width:{{cum_w}}">
        <div class="ar-cum-inner">
          <div class="ar-write-cum">
            {% if not ip %}
              {% if ns_rps.tem_max %}
                <span class="ar-ref-sb ar-ref-max"><span class="ar-ref-sb-lbl">ref</span>+ MAX</span>
              {% else %}
                <span class="ar-ref-sb"><span class="ar-ref-sb-lbl">ref</span>{{ ns.cum }}</span>
              {% endif %}
            {% endif %}
          </div>
        </div>
      </div>
      {% if has_tb %}
      <div class="ar-tb-cell" style="width:{{tb_w}}">
        <div class="ar-tb-inner">
          {% if not ip %}<span class="ar-ref ar-tb-ref"><span class="ar-ref-lbl">m:s</span></span>{% endif %}
        </div>
      </div>
      {% endif %}
    </div>
  {% endfor %}
</div>
{% endmacro %}
"""

SCORE_BOX_MACRO = r"""
{% macro score_box(tipo, wkt=none) %}
{% set tb_text = wkt.tiebreak if (wkt is not none and wkt.tiebreak) else none %}
{% if tipo == 'for_time' %}
<div class="score-section">
  <span class="sc-t">Resultado</span>
  <span class="sc-s">Preencher após o workout</span>
</div>
<div class="score-box">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">For Time</span>
    <span class="sb-lbl-name">Pontuação</span>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">Tempo</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-reps">
    <span class="sb-field-lbl">Reps</span>
    <div class="sb-field-line"></div>
  </div>
  {% if tb_text %}
  <div class="sb-field sb-field-tb">
    <span class="sb-field-lbl">Tie-break <span class="sb-field-sub">{{ tb_text }}</span></span>
    <div class="sb-field-line"></div>
  </div>
  {% endif %}
  <div class="sb-tc-col">
    <div class="sb-tc-box"></div>
    <span class="sb-tc-lbl">Time Cap</span>
    <span class="sb-tc-sub">marcar se atingido</span>
  </div>
</div>
{% elif tipo == 'for_time_goal' %}
<div class="score-section">
  <span class="sc-t">Resultado</span>
  <span class="sc-s">Tempo se completou — ou reps acumuladas do goal se não</span>
</div>
<div class="score-box">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">For Time Goal</span>
    <span class="sb-lbl-name">Pontuação</span>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">Tempo Final <span class="sb-field-sub">se completou</span></span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-reps">
    <span class="sb-field-lbl">Reps Goal Total <span class="sb-field-sub">se não completou</span></span>
    <div class="sb-field-line"></div>
  </div>
  {% if tb_text %}
  <div class="sb-field sb-field-tb">
    <span class="sb-field-lbl">Tie-break <span class="sb-field-sub">{{ tb_text }}</span></span>
    <div class="sb-field-line"></div>
  </div>
  {% endif %}
  <div class="sb-tc-col">
    <div class="sb-tc-box"></div>
    <span class="sb-tc-lbl">Time Cap</span>
    <span class="sb-tc-sub">marcar se atingido</span>
  </div>
</div>
<div class="goal-score-note"><span class="gsn-mark">!</span> Não finalizou? Score = time cap + 1s por rep faltante do goal.</div>
{% elif tipo == 'amrap' %}
<div class="score-section">
  <span class="sc-t">Resultado</span>
  <span class="sc-s">Preencher após o workout</span>
</div>
<div class="score-box">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">AMRAP</span>
    <span class="sb-lbl-name">Pontuação</span>
  </div>
  {# Pontuação AMRAP/EMOM SEMPRE em REPS TOTAIS — nunca rounds. Regra fixa
     do produto: facilita comparação entre atletas e tiebreak. #}
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">Reps Totais</span>
    <div class="sb-field-line"></div>
  </div>
  {% if tb_text %}
  <div class="sb-field sb-field-tb">
    <span class="sb-field-lbl">Tie-break <span class="sb-field-sub">{{ tb_text }}</span></span>
    <div class="sb-field-line"></div>
  </div>
  {% endif %}
  <div class="sb-tc-col">
    <div class="sb-tc-box"></div>
    <span class="sb-tc-lbl">Time Cap</span>
    <span class="sb-tc-sub">marcar se atingido</span>
  </div>
</div>
{% elif tipo == 'express' %}
<div class="score-section">
  <span class="sc-t">Resultado</span>
  <span class="sc-s">Preencher após o workout</span>
</div>
<div class="score-box-dual">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">Express</span>
    <span class="sb-lbl-name">Pontuação</span>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">F1 · Reps</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">F2 · Tempo</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-reps">
    <span class="sb-field-lbl">F2 · Reps</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-tc-col">
    <div class="sb-tc-box"></div>
    <span class="sb-tc-lbl">Time Cap</span>
    <span class="sb-tc-sub">marcar se atingido</span>
  </div>
</div>
{% elif tipo == 'for_load' %}
<div class="score-section">
  <span class="sc-t">Maior Carga</span>
  <span class="sc-s">Maior tentativa válida</span>
</div>
<div class="score-box">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">For Load</span>
    <span class="sb-lbl-name">Pontuação</span>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">Melhor Carga</span>
    <div class="sb-field-line"></div>
  </div>
</div>
{% endif %}
{% endmacro %}
"""


FOR_LOAD_TEAM_SUMMARY_TMPL = r"""<div class="page">

<div class="a4-marker"></div>

{# ── HEADER ── #}
<div class="hdr">
  <div class="hdr-logo-col">
    {% if logo_src %}<img class="hdr-logo" src="{{ logo_src }}" alt="Digital Score">{% endif %}
  </div>
  <div class="hdr-body">
    <div class="hdr-event">{{ ev.nome|upper }}</div>
    {% if ev.categoria %}<div class="hdr-cat">{{ ev.categoria|upper }} · RESUMO DO TIME</div>{% endif %}
  </div>
  <div class="hdr-evento-col">
    {% if logo_evento_src %}<img class="hdr-evento-logo" src="{{ logo_evento_src }}" alt="{{ ev.nome|default('Evento') }}">{% endif %}
    {% if ev.data %}<div class="hdr-evento-date">{{ ev.data }}</div>{% endif %}
  </div>
</div>

{# ── HEADER WORKOUT ── #}
<div class="wkt-zone">
  <div class="wkt-badge">{{ wkt.numero }}</div>
  <div class="wkt-body">
    <div class="wkt-name">{{ wkt.nome }} · Soma do Time</div>
    <span class="wkt-type">For Load</span>
  </div>
</div>

{# ── ATLETAS DO TIME ── #}
<div class="fl-zone">
  <div class="fl-zone-hdr">
    <span class="fl-zone-t">Melhor carga por atleta</span>
    <span class="fl-zone-meta">{{ atletas|length }} atleta{% if atletas|length != 1 %}s{% endif %} · unidade {{ unidade }}</span>
  </div>
  {% for a in atletas %}
  <div class="fl-team-atleta">
    <div class="fl-team-info">
      <span class="fl-team-num">#{{ a.numero }}</span>
      <span class="fl-team-nome">{{ a.nome|upper }}</span>
      {% if a.box %}<span class="fl-team-box">{{ a.box }}</span>{% endif %}
    </div>
    <div class="fl-team-carga">
      <span class="fl-team-carga-lbl">Melhor</span>
      <div class="fl-team-carga-line"></div>
      <span class="fl-team-unidade">{{ unidade }}</span>
    </div>
  </div>
  {% endfor %}
  <div class="fl-melhor">
    <span class="fl-melhor-lbl">Soma do Time</span>
    <div class="fl-melhor-line"></div>
    <span class="fl-melhor-unidade">{{ unidade }}</span>
  </div>
</div>

{# ── ASSINATURAS ── #}
<div class="sign-zone">
  <div class="sign-cell sign-wide"><div class="fl">Assinatura do Capitão</div><div class="fline"></div></div>
  <div class="sign-cell sign-narrow"><div class="fl">Assinatura do Árbitro / Juiz</div><div class="fline"></div></div>
</div>
<div class="no-rasure">Não rasure a súmula — Qualquer correção deve ser registrada no campo de observações</div>

<div class="page-footer">
  <div class="obs-box">
    <div class="obs-lbl">Observações</div>
    <div class="obs-lines">
      <div class="obs-line"></div><div class="obs-line"></div>
      <div class="obs-line"></div>
    </div>
  </div>
  <div class="ds-credit">Gerada pelo sistema Digital Score · Todos os direitos reservados à Digital Score · Reprodução proibida sem autorização</div>
</div>

</div>
"""


FOR_LOAD_TABLE_MACRO = r"""
{# Macro de tentativa única: 2 linhas (régua/barra/régua) e (carga/validade/obs) #}
{% macro for_load_tentativa(idx, anilhas_ordem_grande_pequeno, barra_peso, unidade) %}
<div class="fl-row {% if idx is even %}fl-row-alt{% endif %}">
  <div class="fl-row-top">
    <div class="fl-row-hdr">T{{ idx }}</div>
    {# Anilhas esq: maior colada na barra → mais leve na ponta. Visual da
       extremidade pra barra: pequenas→grandes. #}
    <div class="fl-anilhas fl-anilhas-esq">
      {% for p in anilhas_ordem_grande_pequeno|reverse %}
      <div class="fl-anilha"><span>{{ p }}</span></div>
      {% endfor %}
    </div>
    <div class="fl-barra">{{ barra_peso }} {{ unidade }}</div>
    <div class="fl-anilhas fl-anilhas-dir">
      {% for p in anilhas_ordem_grande_pequeno %}
      <div class="fl-anilha"><span>{{ p }}</span></div>
      {% endfor %}
    </div>
  </div>
  <div class="fl-row-bottom">
    <div class="fl-carga">
      <span class="fl-carga-lbl">Carga</span>
      <div class="fl-carga-line"></div>
      <span class="fl-carga-unidade">{{ unidade }}</span>
    </div>
    <div class="fl-val">
      <div class="fl-val-opt">
        <div class="fl-val-box"></div>
        <span class="fl-val-lbl">Válida</span>
      </div>
      <div class="fl-val-opt">
        <div class="fl-val-box"></div>
        <span class="fl-val-lbl nr">No-Rep</span>
      </div>
    </div>
    <div class="fl-obs">
      <span class="fl-obs-lbl">Obs</span>
      <div class="fl-obs-line"></div>
    </div>
  </div>
</div>
{% endmacro %}

{# Sub-bloco For Load por atleta (dupla/trio/quarteto/time).
   Header em UMA linha: pos + gênero + nome + "Melhor Carga" inline.
   Economiza 1 row por atleta vs design anterior — garante 3 tentativas
   confortáveis em qualquer modalidade. #}
{% macro for_load_atleta_bloco(pos, anilhas, barra, unidade, tentativas, genero='') %}
<div class="fl-atleta-bloco">
  <div class="fl-atleta-hdr">
    <span class="fl-atleta-pos">Atleta {{ pos }}{% if genero %} <span class="fl-atleta-genero">({{ 'F' if genero == 'F' else 'M' }})</span>{% endif %}</span>
    <div class="fl-atleta-nome-line"></div>
    <div class="fl-atleta-melhor-inline">
      <span class="fl-atleta-melhor-lbl">Melhor Carga</span>
      <div class="fl-atleta-melhor-line"></div>
      <span class="fl-atleta-melhor-unidade">{{ unidade }}</span>
    </div>
  </div>
  {% for i in range(1, tentativas + 1) %}
    {{ for_load_tentativa(i, anilhas, barra, unidade) }}
  {% endfor %}
</div>
{% endmacro %}

{# Macro principal: header + N tentativas/atleta. Branch por modalidade —
   individual usa layout linear, team (dupla/trio/quarteto/time) usa
   sub-blocos por atleta com soma final. #}
{% macro for_load_table(wkt, atleta) %}
{% set unidade  = wkt.unidade | default('lb') %}
{% set genero   = wkt._genero | default('M') %}
{# Default conservador: só F usa barra feminina; M e MISTO usam masculina. #}
{% set barra    = wkt.barra_feminina if genero == 'F' else wkt.barra_masculina %}
{% set barra_label = 'Feminina' if genero == 'F' else 'Masculina' %}
{% set tentativas = wkt.tentativas | default(3) %}
{% set anilhas  = wkt.anilhas | default([25, 20, 15, 10, 5, 2.5, 1.25]) %}
{% set modalidade = wkt.modalidade | default('individual') %}
{% set n_atletas = wkt.n_atletas_time | default(wkt._n_atletas_time | default(1)) %}
{% set is_team = n_atletas > 1 %}
{% set genero_por_atleta = wkt._genero_por_atleta | default([]) %}
{% set is_misto = genero_por_atleta | length > 0 %}
{# Layout compacto:
     - individual (n=1): compacto quando tentativas >=5
     - team (n>=2): sempre super-compacto (4 atletas × 3 tents = 12 linhas,
       sem instrução nem Obs, caixinhas reduzidas).
   Muitas anilhas (libras): reduz caixinhas pra evitar overflow horizontal. #}
{% set is_compact = is_team or tentativas >= 5 %}
{% set is_super_compact = n_atletas >= 4 %}
{% set muitas_anilhas = anilhas|length > 7 %}
<div class="fl-zone{% if is_compact %} fl-zone-compact{% endif %}{% if is_super_compact %} fl-zone-super-compact{% endif %}{% if muitas_anilhas %} fl-zone-muitas-anilhas{% endif %}{% if is_team %} fl-zone-team{% endif %}">
  <div class="fl-zone-hdr">
    <span class="fl-zone-t">For Load{% if is_team %} · {{ n_atletas }} Atletas{% endif %}</span>
    {% if is_misto %}
      <span class="fl-zone-meta">Misto · Barras conforme atleta</span>
    {% else %}
      <span class="fl-zone-meta">Barra {{ barra_label }} {{ barra }} {{ unidade }}</span>
    {% endif %}
  </div>
  {# Lembrete pro árbitro: só buy-in (opcional) + complex.
     Strings preservadas como o organizador digitou. #}
  {% set seq = wkt.sequencia_movimentos | default({}) %}
  {% if seq.buy_in or seq.complex %}
  <div class="fl-sequencia">
    {% if seq.buy_in %}
    <div class="fl-sequencia-item">
      <span class="fl-sequencia-tag fl-sequencia-tag-buyin">Buy-in</span>
      <span class="fl-sequencia-text fl-sequencia-text-buyin">{{ seq.buy_in }}</span>
    </div>
    {% endif %}
    {% if seq.complex %}
    <div class="fl-sequencia-item">
      <span class="fl-sequencia-tag">Complex</span>
      <span class="fl-sequencia-text">{{ seq.complex }}</span>
    </div>
    {% endif %}
  </div>
  {% endif %}
  {% if not is_team %}
  <div class="fl-instrucao">
    Marque (✗) cada anilha usada em cada lado da barra, anote a carga total
    e marque <strong>Válida</strong> ou <strong>No-Rep</strong> após cada tentativa.
  </div>
  {% endif %}
  {% if is_team %}
    {% for pos in range(1, n_atletas + 1) %}
      {% if is_misto %}
        {% set g = genero_por_atleta[pos - 1] %}
        {% set barra_pos = wkt.barra_feminina if g == 'F' else wkt.barra_masculina %}
        {{ for_load_atleta_bloco(pos, anilhas, barra_pos, unidade, tentativas, g) }}
      {% else %}
        {{ for_load_atleta_bloco(pos, anilhas, barra, unidade, tentativas) }}
      {% endif %}
    {% endfor %}
    <div class="fl-melhor fl-soma-time">
      <span class="fl-melhor-lbl">Soma do Time</span>
      <div class="fl-melhor-line"></div>
      <span class="fl-melhor-unidade">{{ unidade }}</span>
    </div>
  {% else %}
    {% for i in range(1, tentativas + 1) %}
      {{ for_load_tentativa(i, anilhas, barra, unidade) }}
    {% endfor %}
    <div class="fl-melhor">
      <span class="fl-melhor-lbl">Melhor Carga</span>
      <div class="fl-melhor-line"></div>
      <span class="fl-melhor-unidade">{{ unidade }}</span>
      <div class="fl-melhor-ref">
        <span>Ref. T</span>
        <div class="fl-melhor-ref-box"></div>
      </div>
    </div>
  {% endif %}
</div>
{% endmacro %}
"""

DOC_TMPL_STR = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Súmula – {{ wkt.nome }}</title>
<style>
{% if fonts.black %}@font-face{font-family:'Lato';font-weight:900;src:url('{{ fonts.black }}') format('truetype')}{% endif %}
{% if fonts.bold  %}@font-face{font-family:'Lato';font-weight:700;src:url('{{ fonts.bold  }}') format('truetype')}{% endif %}
{% if fonts.reg   %}@font-face{font-family:'Lato';font-weight:400;src:url('{{ fonts.reg   }}') format('truetype')}{% endif %}
{% if fonts.light %}@font-face{font-family:'Lato';font-weight:300;src:url('{{ fonts.light }}') format('truetype')}{% endif %}
{{ css|safe }}
</style>
</head>
<body>
{% for page in pages %}{{ page|safe }}{% endfor %}
</body>
</html>
"""


PAGE_TMPL_STR = r"""<div class="page">

<div class="a4-marker"></div>

{# ── HEADER ── #}
<div class="hdr">
  <div class="hdr-logo-col">
    {% if logo_src %}<img class="hdr-logo" src="{{ logo_src }}" alt="Digital Score">{% endif %}
  </div>
  <div class="hdr-body">
    <div class="hdr-event">
      {{ ev.nome|upper }}{% if wkt.arena %}<span class="hdr-sep"> / </span>{{ wkt.arena|upper }}{% endif %}
    </div>
    {% if ev.categoria %}<div class="hdr-cat">{{ ev.categoria|upper }}</div>{% endif %}
  </div>
  <div class="hdr-evento-col">
    {% if logo_evento_src %}<img class="hdr-evento-logo" src="{{ logo_evento_src }}" alt="{{ ev.nome|default('Evento') }}">{% endif %}
    {% if wkt.data or ev.data %}<div class="hdr-evento-date">{{ wkt.data or ev.data }}</div>{% endif %}
  </div>
</div>

{# ── PRÉ-WORKOUT ZONE ── #}
{% set tipo = wkt.tipo|default('for_time') %}
{% set modalidade = wkt.modalidade|default('individual') %}
{% set lbl_nome = {'individual':'Nome do Atleta','dupla':'Nome da Dupla','trio':'Nome do Trio','quarteto':'Nome do Quarteto','time':'Nome do Time'}[modalidade]|default('Nome do Atleta') %}
{% set lbl_sign = {'individual':'Assinatura do Atleta','dupla':'Assinatura do Capitão','trio':'Assinatura do Capitão','quarteto':'Assinatura do Capitão','time':'Assinatura do Capitão'}[modalidade]|default('Assinatura do Atleta') %}

<div class="prekit">
  <div class="pk-header">
    <span class="pk-header-t">Pré-Workout</span>
    <span class="pk-header-s">{% if not atleta %}Preencher antes do início{% endif %}</span>
  </div>
  <div class="pk-athlete-row">
    <div class="fl">{{ lbl_nome }}</div>
    {% if atleta and atleta.nome %}
    <div class="fline fline-filled">{{ atleta.nome }}</div>
    {% else %}
    <div class="fline"></div>
    {% endif %}
  </div>
  <div class="pk-sub-row">
    <div class="pk-cell" style="flex:0 0 21mm">
      <div class="fl">Raia</div>
      {% if atleta and atleta.raia %}<div class="fline fline-filled">{{ atleta.raia }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
    <div class="pk-cell" style="flex:0 0 22%">
      <div class="fl">Nº Competidor</div>
      {% if atleta and atleta.numero %}<div class="fline fline-filled">{{ atleta.numero }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
    <div class="pk-cell" style="flex:1">
      <div class="fl">Box</div>
      {% if atleta and atleta.box %}<div class="fline fline-filled">{{ atleta.box }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
  </div>
  <div class="pk-ops-row">
    <div class="pk-cell" style="flex:0 0 58%">
      <div class="fl">Árbitro / Juiz</div><div class="fline"></div>
    </div>
    <div class="pk-cell" style="flex:1">
      <div class="fl">Bateria / Heat</div>
      {% if atleta and atleta.bateria %}<div class="fline fline-filled">{{ atleta.bateria }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
  </div>
</div>

{# ── WORKOUT ZONE ── #}
{% set tipo_labels = {'for_time':'For Time','for_time_goal':'For Time Goal','amrap':'AMRAP','express':'Express — AMRAP + For Time','for_load':'For Load'} %}
<div class="wkt-zone">
  {% if tipo == 'express' and wkt.numero_f2 is defined %}
  <div class="wkt-badge-dual">
    <span class="bd-num">{{ wkt.numero }}</span>
    <span class="bd-sep">·</span>
    <span class="bd-num">{{ wkt.numero_f2 }}</span>
  </div>
  {% else %}
  <div class="wkt-badge">{{ wkt.numero }}</div>
  {% endif %}
  <div class="wkt-body">
    <div class="wkt-name">{{ wkt.nome }}</div>
    <span class="wkt-type">{{ tipo_labels[tipo] | default(tipo) }}</span>
  </div>
  {% if wkt.time_cap %}
  <div class="wkt-tc-rail">
    <span class="wkt-tc-lbl">Time Cap</span>
    <span class="wkt-tc-val">{{ wkt.time_cap }}</span>
  </div>
  {% endif %}
</div>

{# Banner pré-balizamento: bateria existe mas atletas ainda não definidos
   (depende do resultado do dia anterior). Backend seta ev.aguardando_balizamento
   antes de chamar render. Avisa juiz de forma clara e visível. #}
{% if ev.aguardando_balizamento %}
<div class="aguardando-banner" role="status">
  <span class="aguardando-mark">PENDENTE</span>
  <span class="aguardando-txt">Aguardando balizamento <span class="aguardando-sub">— atletas e raias serão definidos após o resultado do dia anterior</span></span>
</div>
{% endif %}

{# ── WORKOUT CONTENT ── #}
{% if tipo == 'express' %}
  {% set f1 = wkt.formula1 %}
  <div class="section-banner">
    <div style="display:flex;align-items:center">
      <div class="sbn-badge">{{ wkt.numero }}</div>
      <span class="sbn-t">Fórmula 1 — AMRAP</span>
    </div>
    <span class="sbn-s">{{ f1.janela }}</span>
  </div>
  {% if f1.descricao %}<div class="desc">{% for l in f1.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {{ amrap_table(f1.movimentos, wkt.numero, f1.n_rounds|default(3)) }}
  <div class="rest-bar">Descanso de 1 Minuto &nbsp;·&nbsp; Reset Barbell / Equipment</div>
  {% set f2 = wkt.formula2 %}
  <div class="section-banner">
    <div style="display:flex;align-items:center">
      <div class="sbn-badge">{{ wkt.numero_f2 if wkt.numero_f2 is defined else wkt.numero }}</div>
      <span class="sbn-t">Fórmula 2 — For Time</span>
    </div>
    <span class="sbn-s">{{ f2.janela }}</span>
  </div>
  {% if f2.descricao %}<div class="desc">{% for l in f2.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {{ mov_table(f2.movimentos, wkt.numero) }}

{% elif tipo == 'amrap' %}
  {# Em EMOM, descrição é redundante (rítmo, movs, progressão e tiebreak já
     vão na tabela). Em AMRAP simples, descrição ajuda o juiz. #}
  {% if wkt.descricao and not wkt.emom_janela %}<div class="desc">{% for l in wkt.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {{ amrap_table(wkt.movimentos, wkt.numero, wkt.n_rounds|default(3), wkt) }}

{% elif tipo == 'for_load' %}
  {# Descrição NÃO é exibida pra For Load: a banda 'Sequência' dentro da
     tabela já é o lembrete oficial (buy-in + complex) e evita duplicação. #}
  {{ for_load_table(wkt, atleta) }}

{% else %}
  {% if wkt.descricao %}<div class="desc">{% for l in wkt.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {# For Time tipo Simple Dimension/Mind — alvo de reps total declarado.
     Atleta distribui reps livremente entre blocos; juiz conta por bloco. #}
  {% if tipo == 'for_time_goal' %}
    {# Banner For Time Goal v2: visual distinto, com carga e mensagem clara
       de que ao bater o goal o atleta corre pra chegada. #}
    <div class="goal-banner">
      <span class="gb-mark">GOAL</span>
      <span class="gb-target">{{ wkt.goal_reps or '?' }}</span>
      <span class="gb-mov">{{ wkt.goal_movimento or 'reps' }}</span>
      {% if wkt.goal_carga %}<span class="gb-carga">@ {{ wkt.goal_carga|upper }}</span>{% endif %}
      <span class="goal-banner-sub">+ rep de chegada · ao bater o goal, corra pra linha</span>
    </div>
  {% elif wkt.goal_reps %}
    {# Legado: For Time com goal_reps mas sem tipo explícito for_time_goal #}
    <div class="goal-banner">
      Alvo · {{ wkt.goal_reps }} {{ wkt.goal_movimento or 'reps' }} + Chegada
      <span class="goal-banner-sub">distribuído livremente · juiz conta reps por bloco</span>
    </div>
  {% endif %}
  {# 'N rounds for time' — expande a tabela N vezes com header 'Round N' antes
     de cada repetição. Cumulativo atravessa rounds. Score = tempo total. #}
  {% if wkt.rounds_fixos and wkt.rounds_fixos > 1 %}
    <div class="goal-banner">
      {{ wkt.rounds_fixos }} Rounds For Time
      <span class="goal-banner-sub">{{ wkt.rounds_fixos }} repetições · score = tempo total</span>
    </div>
  {% endif %}
  {# Relay (rounds_per_atleta): workout único de tempo contínuo. A info do
     formato relay vai como nota acima da tabela; reps + tempo total ficam
     numa tabela só (não duplica por atleta — score é da equipe). #}
  {% set _n_relay = wkt.n_atletas_time or ({'dupla':2,'trio':3,'quarteto':4,'time':3}).get(wkt.modalidade, 0) %}
  {% if wkt.rounds_per_atleta and _n_relay > 0 %}
    <div class="relay-note">Formato Relay · {{ wkt.rounds_per_atleta }} Round{% if wkt.rounds_per_atleta != 1 %}s{% endif %} por Atleta · {{ _n_relay }} atletas em sequência · Tempo total + reps acumuladas</div>
    {# Expande a lista: pra cada atleta, header + base_movs. Chegada só no fim.
       Cumulativo atravessa atletas — score é da equipe, não individual. #}
    {% set _base_movs = wkt.movimentos | rejectattr('chegada','defined') | list %}
    {% set ns_relay = namespace(out=[]) %}
    {% for pos in range(1, _n_relay + 1) %}
      {% set ns_relay.out = ns_relay.out + [{'atleta_header': pos}] + _base_movs %}
    {% endfor %}
    {% set ns_relay.out = ns_relay.out + [{'chegada': true}] %}
    {{ mov_table(ns_relay.out, wkt.numero) }}
  {% elif wkt.rounds_fixos and wkt.rounds_fixos > 1 %}
    {# 'N rounds for time' — expande mov_table N vezes com header 'Round N'
       antes de cada repetição. Cumulativo natural atravessa rounds.
       Visual = juiz marca cada round individualmente. Score = tempo total. #}
    {% set _base_movs = wkt.movimentos | rejectattr('chegada','defined') | list %}
    {% set ns_rd = namespace(out=[]) %}
    {% for r in range(1, wkt.rounds_fixos + 1) %}
      {% set ns_rd.out = ns_rd.out + [{'round_header': r}] + _base_movs %}
    {% endfor %}
    {% set ns_rd.out = ns_rd.out + [{'chegada': true}] %}
    {{ mov_table(ns_rd.out, wkt.numero) }}
  {% else %}
    {{ mov_table(wkt.movimentos, wkt.numero, goal_reps=(wkt.goal_reps | default(0)), hide_cum=(tipo == 'for_time_goal'), tb_col=(tipo == 'for_time_goal' and wkt.tiebreak)) }}
  {% endif %}
{% endif %}

{# ── SCORE BOX ── #}
{{ score_box(tipo, wkt) }}

{# ── ASSINATURAS — coladas logo abaixo do score box ── #}
<div class="sign-zone">
  <div class="sign-cell sign-wide"><div class="fl">{{ lbl_sign }}</div><div class="fline"></div></div>
  <div class="sign-cell sign-narrow"><div class="fl">Assinatura do Árbitro / Juiz</div><div class="fline"></div></div>
</div>
<div class="no-rasure">Não rasure a súmula — Qualquer correção deve ser registrada no campo de observações</div>

{# ── FOOTER — observações sempre no rodapé da página ── #}
<div class="page-footer">
  <div class="obs-box">
    <div class="obs-lbl">Observações</div>
    <div class="obs-lines">
      <div class="obs-line"></div><div class="obs-line"></div>
      <div class="obs-line"></div><div class="obs-line"></div>
      <div class="obs-line"></div>
    </div>
  </div>
  <div class="ds-credit">Gerada pelo sistema Digital Score · Todos os direitos reservados à Digital Score · Reprodução proibida sem autorização</div>
</div>

</div>
"""


# Templates compilados uma vez no import — recompilar a cada página de atleta
# custava ~115ms × N na produção (80 páginas = ~9s só de Jinja compile).
_PAGE_TMPL = Template(MOV_TABLE_MACRO + AMRAP_TABLE_MACRO + SCORE_BOX_MACRO
                      + FOR_LOAD_TABLE_MACRO + PAGE_TMPL_STR, autoescape=True)
_DOC_TMPL = Template(DOC_TMPL_STR, autoescape=True)
_FOR_LOAD_TEAM_SUMMARY_PAGE_TMPL = Template(FOR_LOAD_TEAM_SUMMARY_TMPL, autoescape=True)


def _render_page(ev, wkt, logo_src, logo_evento_src, atleta=None):
    # autoescape: nomes de evento/atleta/box/movimento são input do usuário e
    # podem conter `<`, `>`, `&` ou aspas — escapar previne quebra de layout e
    # XSS quando a súmula HTML é aberta no browser.
    # For Load precisa saber o gênero da categoria pra escolher barra M/F.
    if wkt.get('tipo') == 'for_load' and not wkt.get('_genero'):
        from types_ds import (detectar_genero_categoria, anilhas_default,
                              barra_default, n_atletas_da_modalidade)
        wkt = dict(wkt)
        wkt['_genero']  = detectar_genero_categoria(ev.get('categoria', ''))
        wkt.setdefault('unidade', ev.get('unidade_default', 'lb'))
        wkt.setdefault('tentativas', 3)
        wkt.setdefault('anilhas', anilhas_default(wkt['unidade']))
        wkt.setdefault('barra_masculina', barra_default('M', wkt['unidade']))
        wkt.setdefault('barra_feminina',  barra_default('F', wkt['unidade']))
        modalidade = wkt.get('modalidade', 'individual')
        wkt['_n_atletas_time'] = wkt.get('n_atletas_time') or n_atletas_da_modalidade(modalidade)
        # MISTO em team: define vetor de gênero por posição. Convenção CrossFit
        # BR — mulheres ocupam as primeiras posições. Trio misto = [F, M, M].
        # Dupla misto = [F, M]. Quarteto misto = [F, F, M, M].
        if wkt['_genero'] == 'MISTO' and wkt['_n_atletas_time'] > 1:
            n = wkt['_n_atletas_time']
            n_f = n // 2 if n % 2 == 0 else (n // 2) + (1 if n == 3 else 0)
            # 2 → [F,M] ; 3 → [F,M,M] ; 4 → [F,F,M,M]
            if n == 2:   n_f = 1
            elif n == 3: n_f = 1
            elif n == 4: n_f = 2
            wkt['_genero_por_atleta'] = ['F'] * n_f + ['M'] * (n - n_f)
        # Fallback: se workout não veio do parser de texto (criado direto na UI),
        # tenta inferir sequência do nome (ex: 'MAX CLEAN & JERK' → CLEAN, JERK).
        if not wkt.get('sequencia_movimentos'):
            from parsers import _extrair_sequencia_for_load
            lines = wkt.get('descricao') or []
            seq = _extrair_sequencia_for_load(lines, wkt.get('nome', ''))
            if seq:
                wkt['sequencia_movimentos'] = seq
    # Fallback For Time relay: se workout veio do front-end sem rounds_per_atleta
    # mas a descricao tem 'N round per athlete' / 'N round por atleta', infere.
    if wkt.get('tipo') == 'for_time' and not wkt.get('rounds_per_atleta'):
        desc = ' '.join(wkt.get('descricao') or []) + ' ' + (wkt.get('nome') or '')
        import re as _re
        from parsers import _safe_int
        m = (_re.search(r'(\d+)\s+rounds?\s+per\s+athletes?', desc, _re.I)
             or _re.search(r'(\d+)\s+rounds?\s+por\s+atleta', desc, _re.I))
        if m:
            n = _safe_int(m.group(1))
            if n is not None:
                wkt = dict(wkt)
                wkt['rounds_per_atleta'] = n

    # Trunca descrição em separadores (NOTAS, Observações, etc) — regulamento
    # não deve aparecer na súmula impressa, só prescrição core. Salvaguarda
    # caso a descrição venha cheia do parser ou da edição manual no front.
    if wkt.get('descricao'):
        from parsers import _truncar_descricao_em_notas
        wkt = dict(wkt)
        wkt['descricao'] = _truncar_descricao_em_notas(wkt['descricao'])

    return _PAGE_TMPL.render(ev=ev, wkt=wkt,
                             logo_src=logo_src, logo_evento_src=logo_evento_src,
                             atleta=atleta)


def render_workout(ev, wkt, fonts, logo_src, logo_evento="", atleta=None):
    """Renderiza uma súmula HTML completa (1 página) para um workout."""
    logo_evt_src = logo_evento or ""
    page = _render_page(ev, wkt, logo_src, logo_evt_src, atleta)
    return _DOC_TMPL.render(wkt=wkt, fonts=fonts, css=CSS, pages=[page])


def render_for_load_team_summary(ev, wkt, fonts, logo_src, logo_evento, atletas):
    """Renderiza HTML de uma página com 'Resumo do Time' — usado pra somar
    a melhor carga de cada atleta + total do time no fim do bloco.

    Sai como página única (sem combined). Caller normalmente concatena com
    as páginas individuais dos atletas no ZIP.
    """
    unidade = wkt.get('unidade') or ev.get('unidade_default') or 'lb'
    page = _FOR_LOAD_TEAM_SUMMARY_PAGE_TMPL.render(
        ev=ev, wkt=wkt, atletas=atletas, unidade=unidade,
        logo_src=logo_src, logo_evento_src=logo_evento or '',
    )
    return _DOC_TMPL.render(wkt=wkt, fonts=fonts, css=CSS, pages=[page])


def render_workout_combined(ev, wkt, fonts, logo_src, logo_evento, atletas):
    """Renderiza um único HTML com N páginas-súmula (1 por atleta).
    Fontes, logos e CSS aparecem só uma vez no documento; cada atleta vira
    uma página A4 separada via page-break-after. Ctrl+P imprime o lote inteiro.
    """
    logo_evt_src = logo_evento or ""
    pages = [_render_page(ev, wkt, logo_src, logo_evt_src, a) for a in atletas]
    return _DOC_TMPL.render(wkt=wkt, fonts=fonts, css=CSS, pages=pages)
